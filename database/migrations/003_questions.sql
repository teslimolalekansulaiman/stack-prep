-- Question bank for the NECO objective POC (ADR-0014, docs/question-schema.md).
--
-- Questions attach to the curriculum through question_classifications, which the
-- database forces to point at an approved *skill* in the same subject and the same
-- syllabus version. Content is immutable once approved: corrections open a new
-- version, so a marked response always reflects what the candidate actually saw.
--
-- Marking is deliberately general (response_format + marking_method). The POC
-- delivers objective items only; anything else can be authored and stored, but is
-- excluded from adaptive practice by adaptive_eligible.
BEGIN;
SET LOCAL search_path = stackprep, public;

-- Lets a classification prove its target is a skill, not a topic, a subtopic or one
-- of the structural containers the syllabus import created.
ALTER TABLE curriculum_items
  ADD CONSTRAINT curriculum_items_id_type_key UNIQUE (id, item_type);

-- ---------------------------------------------------------------------------
-- Papers and ingestion
-- ---------------------------------------------------------------------------

-- One paper within a subject, e.g. NECO Mathematics Paper I (objective).
-- Scoring: each subject is reported out of score_out_of (100 for the POC), so
-- marks per question = score_out_of / question_count.
CREATE TABLE exam_papers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_id uuid NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
  paper_code text NOT NULL CHECK (btrim(paper_code) <> ''),
  name text NOT NULL CHECK (btrim(name) <> ''),
  response_mode text NOT NULL CHECK (response_mode IN
    ('objective', 'theory', 'practical', 'oral')),
  question_count integer CHECK (question_count > 0),
  duration_minutes integer CHECK (duration_minutes > 0),
  options_per_question smallint CHECK (options_per_question BETWEEN 2 AND 6),
  score_out_of numeric(6,2) NOT NULL DEFAULT 100 CHECK (score_out_of > 0),
  weight_percent numeric(5,2) CHECK (weight_percent > 0 AND weight_percent <= 100),
  -- Structure taken from an official source and checked by a reviewer, rather than
  -- assumed. Unconfirmed papers must not drive scoring or mock assembly.
  values_confirmed boolean NOT NULL DEFAULT false,
  confirmation_note text,
  pilot_support_status text NOT NULL DEFAULT 'undecided' CHECK (pilot_support_status IN
    ('undecided', 'supported', 'planned', 'unsupported')),
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'retired')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (subject_id, paper_code),
  UNIQUE (id, subject_id),
  CHECK (NOT values_confirmed OR (question_count IS NOT NULL
    AND duration_minutes IS NOT NULL AND options_per_question IS NOT NULL
    AND btrim(coalesce(confirmation_note, '')) <> '')),
  CHECK (pilot_support_status <> 'supported' OR values_confirmed)
);
CREATE INDEX exam_papers_subject_idx ON exam_papers(subject_id);

-- One ingestion run from one file. Re-importing the same file changes nothing.
CREATE TABLE question_import_batches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_id uuid NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
  source_document_id uuid REFERENCES source_documents(id) ON DELETE RESTRICT,
  import_file_uri text NOT NULL CHECK (btrim(import_file_uri) <> ''),
  import_file_sha256 text NOT NULL CHECK (import_file_sha256 ~ '^[0-9a-f]{64}$'),
  format_version text NOT NULL CHECK (btrim(format_version) <> ''),
  row_count integer NOT NULL DEFAULT 0 CHECK (row_count >= 0),
  created_count integer NOT NULL DEFAULT 0 CHECK (created_count >= 0),
  skipped_count integer NOT NULL DEFAULT 0 CHECK (skipped_count >= 0),
  rejected_count integer NOT NULL DEFAULT 0 CHECK (rejected_count >= 0),
  rejected_rows jsonb CHECK (rejected_rows IS NULL OR jsonb_typeof(rejected_rows) = 'array'),
  imported_by uuid REFERENCES academic_reviewers(id) ON DELETE RESTRICT,
  imported_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (import_file_sha256, format_version),
  CHECK (created_count + skipped_count + rejected_count <= row_count)
);

-- ---------------------------------------------------------------------------
-- Shared academic content
-- ---------------------------------------------------------------------------

-- One named, recurring reason students answer incorrectly.
CREATE TABLE misconceptions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_id uuid NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
  code text NOT NULL CHECK (code ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
  name text NOT NULL CHECK (btrim(name) <> ''),
  description text NOT NULL CHECK (btrim(description) <> ''),
  remediation_note text,
  curriculum_item_id uuid REFERENCES curriculum_items(id) ON DELETE RESTRICT,
  review_status text NOT NULL DEFAULT 'draft' CHECK (review_status IN
    ('draft', 'pending', 'approved', 'rejected', 'withdrawn')),
  reviewed_by uuid REFERENCES academic_reviewers(id) ON DELETE RESTRICT,
  reviewed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (subject_id, code),
  UNIQUE (id, subject_id),
  CHECK (review_status <> 'approved' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL))
);

-- One shared stimulus: a comprehension passage, data table or figure set.
CREATE TABLE passages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_id uuid NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
  source_document_id uuid,
  title text,
  body text NOT NULL CHECK (btrim(body) <> ''),
  passage_type text NOT NULL CHECK (passage_type IN
    ('prose', 'dialogue', 'data_table', 'figure_set')),
  word_count integer GENERATED ALWAYS AS
    (array_length(regexp_split_to_array(btrim(body), '\s+'), 1)) STORED,
  estimated_reading_seconds integer CHECK (estimated_reading_seconds > 0),
  reading_level_note text,
  licence_status text NOT NULL DEFAULT 'pending' CHECK (licence_status IN
    ('pending', 'verified', 'blocked')),
  review_status text NOT NULL DEFAULT 'draft' CHECK (review_status IN
    ('draft', 'pending', 'approved', 'rejected', 'withdrawn')),
  reviewed_by uuid REFERENCES academic_reviewers(id) ON DELETE RESTRICT,
  reviewed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, subject_id),
  FOREIGN KEY (source_document_id, subject_id)
    REFERENCES source_documents(id, subject_id) ON DELETE RESTRICT,
  CHECK (review_status <> 'approved' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)),
  -- A passage reaches students only with rights settled; extracts are the highest
  -- copyright risk in the bank.
  CHECK (review_status <> 'approved' OR licence_status = 'verified')
);
CREATE INDEX passages_subject_idx ON passages(subject_id);

-- ---------------------------------------------------------------------------
-- Questions
-- ---------------------------------------------------------------------------

-- One independently answerable item, with its provenance. Content lives in
-- question_versions.
CREATE TABLE questions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_id uuid NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
  exam_paper_id uuid,
  origin text NOT NULL CHECK (origin IN ('past_paper', 'authored', 'generated')),
  source_document_id uuid,
  exam_year integer CHECK (exam_year BETWEEN 1900 AND 2200),
  paper_code text,
  question_number text,
  part_label text,
  -- Reserved for Phase 2. The foreign key arrives with generation_profiles.
  generation_profile_id uuid,
  parent_question_id uuid REFERENCES questions(id) ON DELETE RESTRICT,
  import_batch_id uuid REFERENCES question_import_batches(id) ON DELETE RESTRICT,
  current_version_id uuid,
  -- Held-out items exist only to measure. They are never served in practice, and a
  -- score range built on practised items would overstate readiness.
  usage_pool text NOT NULL DEFAULT 'practice' CHECK (usage_pool IN
    ('practice', 'diagnostic', 'held_out')),
  retired_at timestamptz,
  retired_reason text,
  created_by uuid REFERENCES academic_reviewers(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, subject_id),
  FOREIGN KEY (exam_paper_id, subject_id)
    REFERENCES exam_papers(id, subject_id) ON DELETE RESTRICT,
  FOREIGN KEY (source_document_id, subject_id)
    REFERENCES source_documents(id, subject_id) ON DELETE RESTRICT,
  CHECK (origin <> 'past_paper' OR source_document_id IS NOT NULL),
  CHECK (origin <> 'generated' OR generation_profile_id IS NOT NULL),
  -- Assessments are measured on human-verified content only.
  CHECK (origin <> 'generated' OR usage_pool = 'practice'),
  CHECK (parent_question_id IS NULL OR btrim(coalesce(part_label, '')) <> ''),
  CHECK (retired_at IS NULL OR btrim(coalesce(retired_reason, '')) <> ''),
  CHECK (parent_question_id IS NULL OR parent_question_id <> id)
);
CREATE INDEX questions_subject_pool_idx ON questions(subject_id, usage_pool)
  WHERE retired_at IS NULL;
CREATE INDEX questions_parent_idx ON questions(parent_question_id);
CREATE UNIQUE INDEX questions_source_locator_idx ON questions
  (source_document_id, paper_code, question_number, coalesce(part_label, ''))
  WHERE source_document_id IS NOT NULL AND question_number IS NOT NULL;

-- One immutable snapshot of a question's content.
CREATE TABLE question_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  question_id uuid NOT NULL,
  subject_id uuid NOT NULL,
  version integer NOT NULL CHECK (version > 0),
  passage_id uuid,
  stem text NOT NULL CHECK (btrim(stem) <> ''),
  instructions text,
  response_format text NOT NULL CHECK (response_format IN
    ('mcq_single', 'numeric', 'short_text', 'structured', 'essay')),
  marking_method text NOT NULL CHECK (marking_method IN
    ('auto_key', 'auto_numeric', 'rubric', 'ai_assisted', 'human')),
  numeric_answer numeric,
  numeric_tolerance numeric CHECK (numeric_tolerance >= 0),
  numeric_unit text,
  accepted_answers jsonb CHECK (accepted_answers IS NULL OR
    jsonb_typeof(accepted_answers) = 'array'),
  solution_steps jsonb NOT NULL CHECK (jsonb_typeof(solution_steps) = 'array'
    AND jsonb_array_length(solution_steps) > 0),
  marking_scheme jsonb CHECK (marking_scheme IS NULL OR
    jsonb_typeof(marking_scheme) = 'object'),
  hints jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(hints) = 'array'),
  marks numeric(6,2) CHECK (marks > 0),
  expected_seconds integer CHECK (expected_seconds BETWEEN 10 AND 1800),
  mastery_level_number smallint CHECK (mastery_level_number BETWEEN 1 AND 5),
  -- Chance level for this item is 1 / option_count, so the engine must never assume
  -- four options. Validated against the option rows at approval.
  option_count smallint CHECK (option_count BETWEEN 2 AND 6),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  -- The adaptive engine can only use items it can mark itself.
  adaptive_eligible boolean GENERATED ALWAYS AS
    (response_format = 'mcq_single' AND marking_method = 'auto_key') STORED,
  review_status text NOT NULL DEFAULT 'draft' CHECK (review_status IN
    ('draft', 'pending', 'approved', 'rejected', 'withdrawn')),
  authored_by uuid REFERENCES academic_reviewers(id) ON DELETE RESTRICT,
  reviewed_by uuid REFERENCES academic_reviewers(id) ON DELETE RESTRICT,
  reviewed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (question_id, version),
  UNIQUE (id, question_id),
  UNIQUE (id, subject_id),
  UNIQUE (question_id, content_hash),
  FOREIGN KEY (question_id, subject_id) REFERENCES questions(id, subject_id) ON DELETE RESTRICT,
  FOREIGN KEY (passage_id, subject_id) REFERENCES passages(id, subject_id) ON DELETE RESTRICT,
  CHECK (response_format <> 'mcq_single' OR marking_method = 'auto_key'),
  CHECK (marking_method <> 'auto_numeric' OR numeric_answer IS NOT NULL),
  CHECK (numeric_tolerance IS NULL OR numeric_answer IS NOT NULL),
  CHECK (review_status <> 'approved' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)),
  -- Nobody approves their own question.
  CHECK (reviewed_by IS NULL OR authored_by IS NULL OR reviewed_by <> authored_by)
);
CREATE INDEX question_versions_question_idx ON question_versions(question_id, version);
CREATE INDEX question_versions_review_idx ON question_versions(review_status);
CREATE INDEX question_versions_passage_idx ON question_versions(passage_id);

-- The live version of a question, which must be one of its own versions.
ALTER TABLE questions
  ADD CONSTRAINT questions_current_version_fkey
  FOREIGN KEY (current_version_id, id)
  REFERENCES question_versions(id, question_id) ON DELETE RESTRICT;

-- One lettered choice. Rows, not JSON: each wrong option carries the misconception
-- it represents, and the database enforces exactly one correct answer.
CREATE TABLE question_options (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  question_version_id uuid NOT NULL,
  subject_id uuid NOT NULL,
  option_key text NOT NULL CHECK (option_key ~ '^[A-F]$'),
  body text NOT NULL CHECK (btrim(body) <> ''),
  is_correct boolean NOT NULL DEFAULT false,
  misconception_id uuid,
  distractor_note text,
  display_order smallint NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (question_version_id, option_key),
  FOREIGN KEY (question_version_id, subject_id)
    REFERENCES question_versions(id, subject_id) ON DELETE CASCADE,
  FOREIGN KEY (misconception_id, subject_id)
    REFERENCES misconceptions(id, subject_id) ON DELETE RESTRICT,
  CHECK (NOT is_correct OR misconception_id IS NULL)
);
CREATE UNIQUE INDEX question_options_single_correct_idx
  ON question_options(question_version_id) WHERE is_correct;
CREATE INDEX question_options_misconception_idx ON question_options(misconception_id);

-- One image or file. Rights and alt text are per file, not per question.
CREATE TABLE question_assets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  question_version_id uuid REFERENCES question_versions(id) ON DELETE CASCADE,
  passage_id uuid REFERENCES passages(id) ON DELETE CASCADE,
  storage_uri text NOT NULL CHECK (btrim(storage_uri) <> ''),
  mime_type text NOT NULL CHECK (btrim(mime_type) <> ''),
  byte_size integer CHECK (byte_size > 0),
  width integer CHECK (width > 0),
  height integer CHECK (height > 0),
  -- Required before approval: accessibility, and it is what an AI tutor can read.
  alt_text text,
  licence_status text NOT NULL DEFAULT 'pending' CHECK (licence_status IN
    ('pending', 'verified', 'blocked')),
  display_order smallint NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((question_version_id IS NULL) <> (passage_id IS NULL))
);
CREATE INDEX question_assets_version_idx ON question_assets(question_version_id);
CREATE INDEX question_assets_passage_idx ON question_assets(passage_id);

-- ---------------------------------------------------------------------------
-- Classification: the link to the syllabus
-- ---------------------------------------------------------------------------

CREATE TABLE question_classifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  question_id uuid NOT NULL,
  subject_id uuid NOT NULL,
  curriculum_item_id uuid NOT NULL,
  syllabus_version_id uuid NOT NULL,
  -- Fixed value, so the composite key below can reject a topic or subtopic.
  target_item_type text NOT NULL DEFAULT 'skill' CHECK (target_item_type = 'skill'),
  mastery_level_id uuid,
  classification_role text NOT NULL CHECK (classification_role IN ('primary', 'secondary')),
  cognitive_process text CHECK (cognitive_process IN
    ('recall', 'procedure', 'application', 'reasoning')),
  confidence numeric(5,4) CHECK (confidence >= 0 AND confidence <= 1),
  proposed_by text NOT NULL DEFAULT 'human' CHECK (proposed_by IN ('human', 'model')),
  classification_reason text NOT NULL CHECK (btrim(classification_reason) <> ''),
  review_status text NOT NULL DEFAULT 'draft' CHECK (review_status IN
    ('draft', 'pending', 'approved', 'rejected', 'withdrawn')),
  reviewed_by uuid REFERENCES academic_reviewers(id) ON DELETE RESTRICT,
  reviewed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (question_id, curriculum_item_id),
  FOREIGN KEY (question_id, subject_id) REFERENCES questions(id, subject_id) ON DELETE CASCADE,
  FOREIGN KEY (syllabus_version_id, subject_id)
    REFERENCES syllabus_versions(id, subject_id) ON DELETE RESTRICT,
  -- The skill belongs to this syllabus version …
  FOREIGN KEY (curriculum_item_id, syllabus_version_id)
    REFERENCES curriculum_items(id, syllabus_version_id) ON DELETE RESTRICT,
  -- … and is a skill, not a topic, subtopic or structural container …
  FOREIGN KEY (curriculum_item_id, target_item_type)
    REFERENCES curriculum_items(id, item_type) ON DELETE RESTRICT,
  -- … and the level, if given, is defined for that exact skill.
  FOREIGN KEY (mastery_level_id, curriculum_item_id)
    REFERENCES curriculum_mastery_levels(id, curriculum_item_id) ON DELETE RESTRICT,
  CHECK (proposed_by <> 'model' OR confidence IS NOT NULL),
  CHECK (review_status <> 'approved' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL))
);
CREATE UNIQUE INDEX question_one_approved_primary_idx ON question_classifications(question_id)
  WHERE classification_role = 'primary' AND review_status = 'approved';
CREATE INDEX question_classifications_skill_idx
  ON question_classifications(curriculum_item_id, review_status);

-- ---------------------------------------------------------------------------
-- Derived statistics and problem reports
-- ---------------------------------------------------------------------------

-- Recomputed by a nightly job from attempts. Never written by the request path.
CREATE TABLE question_statistics (
  question_version_id uuid PRIMARY KEY REFERENCES question_versions(id) ON DELETE CASCADE,
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  correct_count integer NOT NULL DEFAULT 0 CHECK (correct_count >= 0),
  correct_rate numeric(6,4) GENERATED ALWAYS AS
    (CASE WHEN attempt_count > 0 THEN correct_count::numeric / attempt_count END) STORED,
  median_response_ms integer CHECK (median_response_ms > 0),
  p90_response_ms integer CHECK (p90_response_ms > 0),
  discrimination numeric(6,4),
  -- Empirical difficulty replaces the authored level prior once evidence exists.
  calibrated_difficulty numeric(6,4),
  option_share jsonb CHECK (option_share IS NULL OR jsonb_typeof(option_share) = 'object'),
  flag_state text NOT NULL DEFAULT 'none' CHECK (flag_state IN
    ('none', 'too_easy', 'too_hard', 'low_discrimination', 'reported')),
  stats_version text NOT NULL CHECK (btrim(stats_version) <> ''),
  computed_at timestamptz NOT NULL DEFAULT now(),
  CHECK (correct_count <= attempt_count)
);
CREATE INDEX question_statistics_flag_idx ON question_statistics(flag_state)
  WHERE flag_state <> 'none';

CREATE TABLE question_reports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  question_version_id uuid NOT NULL REFERENCES question_versions(id) ON DELETE RESTRICT,
  reporter_kind text NOT NULL CHECK (reporter_kind IN ('student', 'reviewer', 'system')),
  reporter_reviewer_id uuid REFERENCES academic_reviewers(id) ON DELETE RESTRICT,
  -- Student accounts do not exist yet; the foreign key lands with those tables.
  reporter_student_id uuid,
  reason text NOT NULL CHECK (reason IN
    ('wrong_answer', 'ambiguous', 'typo', 'image_missing', 'off_syllabus', 'other')),
  detail text,
  attempt_context jsonb CHECK (attempt_context IS NULL OR
    jsonb_typeof(attempt_context) = 'object'),
  status text NOT NULL DEFAULT 'open' CHECK (status IN
    ('open', 'triaged', 'fixed', 'rejected')),
  resolved_by uuid REFERENCES academic_reviewers(id) ON DELETE RESTRICT,
  resolved_at timestamptz,
  resolution_note text,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (reporter_kind <> 'reviewer' OR reporter_reviewer_id IS NOT NULL),
  CHECK (reporter_kind <> 'student' OR reporter_student_id IS NOT NULL),
  CHECK (status IN ('open', 'triaged') OR
    (resolved_by IS NOT NULL AND resolved_at IS NOT NULL
     AND btrim(coalesce(resolution_note, '')) <> ''))
);
CREATE INDEX question_reports_open_idx ON question_reports(status, created_at)
  WHERE status IN ('open', 'triaged');
CREATE INDEX question_reports_version_idx ON question_reports(question_version_id);

-- ---------------------------------------------------------------------------
-- Guards
-- ---------------------------------------------------------------------------

-- Approved content is frozen, and approval has its own completeness gate.
CREATE FUNCTION check_question_version() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  option_total integer;
  correct_total integer;
  p record;
BEGIN
  IF TG_OP = 'UPDATE' AND OLD.review_status = 'approved' THEN
    IF ROW(NEW.question_id, NEW.subject_id, NEW.version, NEW.passage_id, NEW.stem,
           NEW.instructions, NEW.response_format, NEW.marking_method, NEW.numeric_answer,
           NEW.numeric_tolerance, NEW.numeric_unit, NEW.accepted_answers,
           NEW.solution_steps, NEW.marking_scheme, NEW.hints, NEW.marks,
           NEW.expected_seconds, NEW.mastery_level_number, NEW.option_count,
           NEW.content_hash)
       IS DISTINCT FROM
       ROW(OLD.question_id, OLD.subject_id, OLD.version, OLD.passage_id, OLD.stem,
           OLD.instructions, OLD.response_format, OLD.marking_method, OLD.numeric_answer,
           OLD.numeric_tolerance, OLD.numeric_unit, OLD.accepted_answers,
           OLD.solution_steps, OLD.marking_scheme, OLD.hints, OLD.marks,
           OLD.expected_seconds, OLD.mastery_level_number, OLD.option_count,
           OLD.content_hash) THEN
      RAISE EXCEPTION 'approved question content is immutable; create a new version';
    END IF;
    IF NEW.review_status NOT IN ('approved', 'withdrawn') THEN
      RAISE EXCEPTION 'approved question cannot return to draft; withdraw it instead';
    END IF;
  END IF;

  IF NEW.review_status = 'approved' THEN
    IF NEW.authored_by IS NULL THEN
      RAISE EXCEPTION 'an approved question must record its author';
    END IF;
    IF NEW.expected_seconds IS NULL OR NEW.mastery_level_number IS NULL THEN
      RAISE EXCEPTION 'an approved question needs expected_seconds and a mastery level';
    END IF;
    IF jsonb_array_length(NEW.hints) = 0 THEN
      RAISE EXCEPTION 'an approved question needs at least one hint';
    END IF;

    IF NEW.response_format = 'mcq_single' THEN
      SELECT count(*), count(*) FILTER (WHERE is_correct)
        INTO option_total, correct_total
        FROM question_options WHERE question_version_id = NEW.id;
      IF option_total < 4 THEN
        RAISE EXCEPTION 'an approved objective question needs at least four options, found %', option_total;
      END IF;
      IF correct_total <> 1 THEN
        RAISE EXCEPTION 'an approved objective question needs exactly one correct option';
      END IF;
      IF NEW.option_count IS DISTINCT FROM option_total THEN
        RAISE EXCEPTION 'option_count (%) does not match the % options stored', NEW.option_count, option_total;
      END IF;
    END IF;

    IF EXISTS (
      SELECT 1 FROM question_assets a
      WHERE a.question_version_id = NEW.id
        AND (a.licence_status <> 'verified' OR btrim(coalesce(a.alt_text, '')) = '')
    ) THEN
      RAISE EXCEPTION 'every asset needs alt text and a verified licence before approval';
    END IF;

    IF NEW.passage_id IS NOT NULL THEN
      SELECT * INTO p FROM passages WHERE id = NEW.passage_id;
      IF p.review_status <> 'approved' OR p.licence_status <> 'verified' THEN
        RAISE EXCEPTION 'the passage must be approved with a verified licence first';
      END IF;
    END IF;
  END IF;

  RETURN NEW;
END $$;
CREATE TRIGGER question_version_guard BEFORE INSERT OR UPDATE ON question_versions
  FOR EACH ROW EXECUTE FUNCTION check_question_version();

-- Options belong to their version's snapshot, so they freeze with it.
CREATE FUNCTION check_question_option() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target uuid; state text;
BEGIN
  target := CASE TG_OP WHEN 'DELETE' THEN OLD.question_version_id
                       ELSE NEW.question_version_id END;
  SELECT review_status INTO state FROM question_versions WHERE id = target;
  IF state = 'approved' THEN
    RAISE EXCEPTION 'options of an approved question are immutable; create a new version';
  END IF;
  RETURN CASE TG_OP WHEN 'DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER question_option_guard BEFORE INSERT OR UPDATE OR DELETE ON question_options
  FOR EACH ROW EXECUTE FUNCTION check_question_option();

-- Multipart questions are one level deep and stay inside one subject and paper.
CREATE FUNCTION check_question_parent() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent record;
BEGIN
  IF NEW.parent_question_id IS NOT NULL THEN
    SELECT * INTO parent FROM questions WHERE id = NEW.parent_question_id;
    IF parent.id IS NULL OR parent.subject_id <> NEW.subject_id THEN
      RAISE EXCEPTION 'a question part must belong to the same subject as its parent';
    END IF;
    IF parent.parent_question_id IS NOT NULL THEN
      RAISE EXCEPTION 'question parts nest one level only';
    END IF;
    IF parent.exam_paper_id IS DISTINCT FROM NEW.exam_paper_id THEN
      RAISE EXCEPTION 'a question part must sit in the same paper as its parent';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER question_parent_guard BEFORE INSERT OR UPDATE ON questions
  FOR EACH ROW EXECUTE FUNCTION check_question_parent();

-- ---------------------------------------------------------------------------
-- Views
-- ---------------------------------------------------------------------------

-- Everything a question needs before it may reach a student: approved content, an
-- approved primary skill on the current syllabus, and settled rights.
CREATE VIEW deliverable_questions AS
SELECT q.id                        AS question_id,
       v.id                        AS question_version_id,
       q.subject_id,
       q.exam_paper_id,
       q.usage_pool,
       q.origin,
       v.version,
       v.response_format,
       v.marking_method,
       v.adaptive_eligible,
       v.mastery_level_number,
       v.expected_seconds,
       v.option_count,
       v.marks,
       v.passage_id,
       c.curriculum_item_id        AS primary_skill_id,
       c.mastery_level_id,
       ts.name                     AS skill_name,
       ts.syllabus_version_id
FROM questions q
JOIN question_versions v
  ON v.id = q.current_version_id AND v.review_status = 'approved'
JOIN question_classifications c
  ON c.question_id = q.id
 AND c.classification_role = 'primary'
 AND c.review_status = 'approved'
JOIN teachable_skills ts
  ON ts.curriculum_item_id = c.curriculum_item_id
LEFT JOIN source_documents d ON d.id = q.source_document_id
LEFT JOIN passages p ON p.id = v.passage_id
WHERE q.retired_at IS NULL
  AND (q.origin <> 'past_paper' OR (d.review_status = 'approved'
       AND d.licence_status = 'verified' AND d.student_delivery_permission))
  AND (v.passage_id IS NULL OR (p.review_status = 'approved'
       AND p.licence_status = 'verified'))
  AND NOT EXISTS (
    SELECT 1 FROM question_assets a
    WHERE (a.question_version_id = v.id OR a.passage_id = v.passage_id)
      AND (a.licence_status <> 'verified' OR btrim(coalesce(a.alt_text, '')) = '')
  );

-- What the adaptive engine may serve: deliverable, in the practice pool, and
-- markable without a human.
CREATE VIEW adaptive_practice_questions AS
SELECT * FROM deliverable_questions
WHERE usage_pool = 'practice' AND adaptive_eligible;

-- What a candidate may receive. No key, no solution, no marking scheme, no
-- misconception: marking happens server-side.
CREATE VIEW candidate_question_payload AS
SELECT dq.question_id,
       dq.question_version_id,
       dq.subject_id,
       dq.response_format,
       dq.option_count,
       dq.marks,
       dq.expected_seconds,
       v.stem,
       v.instructions,
       v.passage_id,
       p.title       AS passage_title,
       p.body        AS passage_body
FROM deliverable_questions dq
JOIN question_versions v ON v.id = dq.question_version_id
LEFT JOIN passages p ON p.id = v.passage_id;

CREATE VIEW candidate_question_options AS
SELECT o.question_version_id,
       o.id AS option_id,
       o.option_key,
       o.body,
       o.display_order
FROM question_options o
JOIN deliverable_questions dq ON dq.question_version_id = o.question_version_id;

COMMIT;
