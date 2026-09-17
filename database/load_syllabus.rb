#!/usr/bin/env ruby
# Loads a reviewed extraction of one PDF into the draft curriculum tables.
# PostgreSQL is accessed through psql so the loader needs no Ruby gems.

require 'digest'
require 'json'
require 'open3'
require 'optparse'
require 'pathname'
require 'yaml'

ROOT = Pathname.new(__dir__).parent.realpath
DEFAULT_PDF = ROOT.join('docs/Math-syllabus.pdf')
DEFAULT_SEED = ROOT.join('database/seeds/neco_gce_mathematics.yaml')

def fail_with(message)
  warn "Loader error: #{message}"
  exit 1
end

def uuid_for(key)
  bytes = Digest::SHA1.digest("stackprep-curriculum-import-v1:#{key}").bytes.first(16)
  bytes[6] = (bytes[6] & 0x0f) | 0x50
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  hex = bytes.pack('C*').unpack1('H*')
  "#{hex[0, 8]}-#{hex[8, 4]}-#{hex[12, 4]}-#{hex[16, 4]}-#{hex[20, 12]}"
end

def sql_value(value)
  case value
  when nil then 'NULL'
  when true then 'TRUE'
  when false then 'FALSE'
  when Integer then value.to_s
  when Hash, Array then "'#{JSON.generate(value).gsub("'", "''")}'::jsonb"
  else "'#{value.to_s.gsub("'", "''")}'"
  end
end

def insert_statement(table, values)
  columns = values.keys.join(', ')
  literals = values.values.map { |value| sql_value(value) }.join(', ')
  "INSERT INTO #{table} (#{columns}) VALUES (#{literals}) ON CONFLICT (id) DO NOTHING;"
end

def run_psql(connection_args, sql: nil, file: nil)
  args = ['psql', '-X', '-v', 'ON_ERROR_STOP=1', '-q', '-t', '-A', *connection_args]
  args += ['-f', file.to_s] if file
  output, error, status = Open3.capture3(*args, stdin_data: sql)
  fail_with("PostgreSQL command failed:\n#{error.strip}") unless status.success?
  output.strip
end

options = {
  pdf: DEFAULT_PDF,
  seed: DEFAULT_SEED,
  database_url: ENV['DATABASE_URL'],
  dry_run: false
}
OptionParser.new do |parser|
  parser.banner = 'Usage: ruby database/load_syllabus.rb [options]'
  parser.on('--pdf PATH', 'PDF to validate against the seed SHA-256') { |v| options[:pdf] = Pathname.new(v) }
  parser.on('--seed PATH', 'Curated YAML extraction') { |v| options[:seed] = Pathname.new(v) }
  parser.on('--database-url URL', 'PostgreSQL connection URL; defaults to local project database') { |v| options[:database_url] = v }
  parser.on('--dry-run', 'Validate files and hierarchy without writing to PostgreSQL') { options[:dry_run] = true }
end.parse!

pdf_path = options[:pdf].expand_path
seed_path = options[:seed].expand_path
fail_with("PDF not found: #{pdf_path}") unless pdf_path.file?
fail_with("seed not found: #{seed_path}") unless seed_path.file?

begin
  seed = YAML.safe_load(seed_path.read)
rescue StandardError => error
  fail_with("cannot parse seed YAML: #{error.message}")
end
fail_with('unsupported seed format') unless seed['format_version'] == 1
documents = seed.fetch('source_documents')
versions = seed.fetch('syllabus_versions')
fail_with('this loader expects exactly one source document and one syllabus version') unless documents.length == 1 && versions.length == 1
document = documents.first
version = versions.first
pdf_hash = Digest::SHA256.file(pdf_path).hexdigest
fail_with("PDF SHA-256 mismatch; expected #{document['file_sha256']}, got #{pdf_hash}") unless pdf_hash == document['file_sha256']

exam = seed.fetch('examination')
subject = seed.fetch('subject')
defaults = seed.fetch('item_defaults')
items = seed.fetch('curriculum_items')
fail_with('the import must begin with unapproved records') unless
  exam['status'] == 'draft' && subject['status'] == 'draft' &&
  document['review_status'] == 'pending' && document['licence_status'] == 'pending' &&
  document['storage_permission'] == false && document['student_delivery_permission'] == false &&
  document['model_context_permission'] == false && version['status'] == 'draft' &&
  version['is_current'] == false && defaults['review_status'] == 'draft'
fail_with('document_year must be unknown unless printed as a syllabus year') unless document['document_year'].nil?
fail_with('no curriculum items found') if items.empty?

# Each syllabus states its own shape: which PDF pages the extraction may cite, and how
# many topics the reviewer counted. Both are checked so a mis-typed page or a dropped
# topic fails the import instead of quietly entering the database.
validation = seed.fetch('validation')
page_range = validation['source_page_range']
expected_topics = validation['expected_topic_count']
fail_with('validation.source_page_range must be [first_page, last_page]') unless
  page_range.is_a?(Array) && page_range.length == 2 &&
  page_range.all? { |value| value.is_a?(Integer) && value.positive? } &&
  page_range[0] <= page_range[1]
fail_with('validation.expected_topic_count must be a positive integer') unless
  expected_topics.is_a?(Integer) && expected_topics.positive?
allowed_pages = (page_range[0]..page_range[1])

seen = {}
counts = Hash.new(0)
order_by_parent = Hash.new(0)
items.each do |item|
  code = item.fetch('code')
  type = item.fetch('type')
  parent = item['parent']
  fail_with("duplicate item code #{code}") if seen.key?(code)
  fail_with("invalid item type at #{code}") unless %w[topic subtopic skill].include?(type)
  expected_parent_type = { 'topic' => nil, 'subtopic' => 'topic', 'skill' => 'subtopic' }.fetch(type)
  fail_with("invalid or out-of-order parent at #{code}") unless
    (expected_parent_type.nil? && parent.nil?) || (seen[parent] == expected_parent_type)
  fail_with("missing name/location/excerpt at #{code}") if
    %w[name location excerpt].any? { |field| item[field].to_s.strip.empty? }
  page = item['location'][/PDF page (\d+)/, 1]&.to_i
  fail_with("source page outside syllabus section at #{code}") unless page && allowed_pages.cover?(page)
  seen[code] = type
  counts[type] += 1
  order_by_parent[parent] += 1
  item['__display_order'] = order_by_parent[parent]
end
fail_with("unexpected topic count: #{counts['topic']}") unless counts['topic'] == expected_topics

puts "Validated PDF SHA-256 #{pdf_hash}"
puts "Validated #{counts['topic']} topics, #{counts['subtopic']} subtopics, #{counts['skill']} skills."
if options[:dry_run]
  puts 'Dry run complete; no database changes.'
  exit 0
end

connection_args = if options[:database_url] && !options[:database_url].empty?
  ['--dbname', options[:database_url]]
else
  ['--host', ROOT.join('.local/run').to_s, '--port', '55439', '--dbname', 'scorepilot']
end

existing_schema = run_psql(connection_args, sql: "SELECT to_regclass('stackprep.examinations') IS NOT NULL;")
unless existing_schema == 't'
  puts 'Applying curriculum schema...'
  run_psql(connection_args, file: ROOT.join('database/migrations/001_curriculum.sql'))
end
run_psql(connection_args, file: ROOT.join('database/migrations/002_pilot_support_undecided.sql'))

exam_id = uuid_for("exam:#{exam.fetch('exam_body')}:#{exam.fetch('short_name')}:#{exam.fetch('country_code')}")
subject_id = uuid_for("subject:#{exam_id}:#{subject.fetch('code')}")
document_id = uuid_for("document:#{pdf_hash}")
version_id = uuid_for("version:#{subject_id}:#{version.fetch('version_label')}")

sql = ["BEGIN;", "SET LOCAL search_path = stackprep, public;", "SET LOCAL standard_conforming_strings = on;"]
sql << "UPDATE curriculum_items SET pilot_support_status = 'undecided' WHERE syllabus_version_id = #{sql_value(version_id)} AND review_status = 'draft' AND syllabus_status = 'uncertain' AND pilot_support_status = 'unsupported';"
sql << insert_statement('examinations', {
  id: exam_id, name: exam.fetch('name'), short_name: exam.fetch('short_name'),
  exam_body: exam.fetch('exam_body'), country_code: exam.fetch('country_code'),
  description: exam['description'], grading_system: nil, status: 'draft'
})
sql << insert_statement('subjects', {
  id: subject_id, examination_id: exam_id, code: subject.fetch('code'),
  name: subject.fetch('name'), status: 'draft'
})
sql << insert_statement('source_documents', {
  id: document_id, examination_id: exam_id, subject_id: subject_id,
  document_type: document.fetch('document_type'), title: document.fetch('title'),
  issuer: document['issuer'], publication_date: nil, document_year: nil,
  file_uri: document.fetch('file_uri'), file_sha256: pdf_hash,
  mime_type: document.fetch('mime_type'), page_count: document.fetch('page_count'),
  licence_status: 'pending', storage_permission: false,
  student_delivery_permission: false, model_context_permission: false,
  processing_status: document.fetch('processing_status'), review_status: 'pending'
})
sql << insert_statement('syllabus_versions', {
  id: version_id, subject_id: subject_id,
  version_label: version.fetch('version_label'), authority_identifier: nil,
  valid_from: nil, valid_to: nil, source_document_id: document_id,
  status: 'draft', is_current: false
})

expected_items = []
expected_evidence = []
items.each do |item|
  item_id = uuid_for("item:#{version_id}:#{item.fetch('code')}")
  parent_id = item['parent'] && uuid_for("item:#{version_id}:#{item['parent']}")
  note = item['boundary_notes'] || defaults['boundary_notes']
  structural = item['type'] == 'subtopic' && item['syllabus_status'] == 'implied'
  sql << insert_statement('curriculum_items', {
    id: item_id, syllabus_version_id: version_id, subject_id: subject_id,
    parent_id: parent_id, item_type: item.fetch('type'), code: item.fetch('code'),
    name: item.fetch('name'), learning_objective: item.fetch('learning_objective', defaults['learning_objective']),
    examinable_scope: item.fetch('examinable_scope', defaults['examinable_scope']),
    expected_depth: item.fetch('expected_depth', defaults['expected_depth']),
    boundary_notes: note, syllabus_status: 'uncertain', pilot_support_status: 'undecided',
    display_order: item.fetch('__display_order'), review_status: 'draft'
  })
  evidence_id = uuid_for("evidence:#{item_id}:#{document_id}:#{item.fetch('location')}")
  evidence_kind = structural ? 'academic_boundary' : 'inclusion'
  sql << insert_statement('curriculum_evidence', {
    id: evidence_id, curriculum_item_id: item_id, source_document_id: document_id,
    evidence_kind: evidence_kind, source_location: item.fetch('location'),
    source_excerpt: item.fetch('excerpt'),
    decision_rationale: structural ? (note || 'Structural subtopic inferred for the schema.') : nil,
    decision_evidence_reference: structural ? item.fetch('location') : nil,
    review_status: 'pending'
  })
  expected_items << "(#{[item_id, version_id, parent_id, item['type'], item['code'], item['name']].map { |v| sql_value(v) }.join(', ')})"
  expected_evidence << "(#{[evidence_id, item_id, document_id, evidence_kind, item['location'], item['excerpt']].map { |v| sql_value(v) }.join(', ')})"
end

sql << 'CREATE TEMP TABLE expected_items (id uuid, syllabus_version_id uuid, parent_id uuid, item_type text, code text, name text) ON COMMIT DROP;'
sql << "INSERT INTO expected_items VALUES #{expected_items.join(",\n")};"
sql << 'CREATE TEMP TABLE expected_evidence (id uuid, curriculum_item_id uuid, source_document_id uuid, evidence_kind text, source_location text, source_excerpt text) ON COMMIT DROP;'
sql << "INSERT INTO expected_evidence VALUES #{expected_evidence.join(",\n")};"
sql << <<~SQL
  DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM examinations WHERE id = #{sql_value(exam_id)} AND status = 'draft')
       OR NOT EXISTS (SELECT 1 FROM subjects WHERE id = #{sql_value(subject_id)} AND examination_id = #{sql_value(exam_id)})
       OR NOT EXISTS (SELECT 1 FROM source_documents WHERE id = #{sql_value(document_id)}
         AND file_sha256 = #{sql_value(pdf_hash)} AND subject_id = #{sql_value(subject_id)})
       OR NOT EXISTS (SELECT 1 FROM syllabus_versions WHERE id = #{sql_value(version_id)}
         AND subject_id = #{sql_value(subject_id)} AND source_document_id = #{sql_value(document_id)}) THEN
      RAISE EXCEPTION 'existing root record conflicts with this PDF import';
    END IF;
    IF EXISTS (
      SELECT 1 FROM expected_items x LEFT JOIN curriculum_items c ON c.id = x.id
      WHERE c.id IS NULL OR ROW(c.syllabus_version_id, c.parent_id, c.item_type, c.code, c.name)
        IS DISTINCT FROM ROW(x.syllabus_version_id, x.parent_id, x.item_type, x.code, x.name)
    ) OR (SELECT count(*) FROM curriculum_items WHERE syllabus_version_id = #{sql_value(version_id)}) <> #{items.length} THEN
      RAISE EXCEPTION 'existing curriculum differs from this PDF extraction; create a new draft version';
    END IF;
    IF EXISTS (
      SELECT 1 FROM expected_evidence x LEFT JOIN curriculum_evidence e ON e.id = x.id
      WHERE e.id IS NULL OR ROW(e.curriculum_item_id, e.source_document_id, e.evidence_kind,
        e.source_location, e.source_excerpt) IS DISTINCT FROM
        ROW(x.curriculum_item_id, x.source_document_id, x.evidence_kind,
        x.source_location, x.source_excerpt)
    ) THEN
      RAISE EXCEPTION 'existing evidence differs from this PDF extraction';
    END IF;
  END $$;
SQL
sql << "SELECT 'topics=' || count(*) FROM curriculum_items WHERE syllabus_version_id = #{sql_value(version_id)} AND item_type = 'topic';"
sql << "SELECT 'subtopics=' || count(*) FROM curriculum_items WHERE syllabus_version_id = #{sql_value(version_id)} AND item_type = 'subtopic';"
sql << "SELECT 'skills=' || count(*) FROM curriculum_items WHERE syllabus_version_id = #{sql_value(version_id)} AND item_type = 'skill';"
sql << "SELECT 'evidence=' || count(*) FROM curriculum_evidence e JOIN curriculum_items c ON c.id = e.curriculum_item_id WHERE c.syllabus_version_id = #{sql_value(version_id)};"
sql << "SELECT 'published=' || count(*) FROM published_curriculum_scope WHERE syllabus_version_id = #{sql_value(version_id)};"
sql << 'COMMIT;'

puts run_psql(connection_args, sql: sql.join("\n"))
puts 'Import complete. All imported academic content remains draft or pending.'
