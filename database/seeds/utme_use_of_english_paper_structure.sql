-- UTME Use of English: the paper and what each of its parts examines.
--
-- Every number here is printed in "docs/syllabus/utme-english-syllabus 2027.pdf" page 3,
-- "D. THE STRUCTURE OF THE EXAMINATION", which itemises all sixty questions. Nothing is
-- inferred, and nothing is derived from our own question bank.
--
-- Two things page 3 does NOT print, so they are not claimed here:
--   * how long the paper lasts, and how many options each question has. duration_minutes
--     and options_per_question are therefore null and values_confirmed stays false, which
--     the schema enforces by refusing 'supported' to an unconfirmed paper.
--   * how the sixty questions are marked. score_out_of is left at the schema default of
--     100; it is NOT a printed value. Shares are unaffected either way, because with no
--     marks_total on any section the weight falls back to each part's share of the
--     questions — which is exactly what the document supports.
--
-- Each printed part gets its own row so the detail survives, but every row points at its
-- SECTION's topic, because topic_exam_weight and topic_weight_vs_coverage are keyed on
-- topics. The view sums them back up to: A 25 questions, B 25, C 10.
--
-- Rows are inserted as PENDING review. Topic weights only count approved sections, so a
-- subject lead has to agree with this reading before it steers anything:
--
--   UPDATE stackprep.exam_paper_sections
--      SET review_status = 'approved', reviewed_by = :reviewer_id, reviewed_at = now()
--    WHERE review_status = 'pending';
--
-- Safe to re-run.
BEGIN;
SET LOCAL search_path = stackprep, public;

WITH subject AS (
  SELECT s.id
  FROM subjects s
  JOIN examinations e ON e.id = s.examination_id
  WHERE s.code = 'ENG' AND e.short_name = 'UTME'
  LIMIT 1
),
version AS (
  SELECT v.id FROM syllabus_versions v, subject
  WHERE v.subject_id = subject.id AND v.version_label = 'utme-2027'
  LIMIT 1
),
papers AS (
  INSERT INTO exam_papers (subject_id, paper_code, name, response_mode, question_count,
    duration_minutes, options_per_question, values_confirmed, confirmation_note,
    pilot_support_status, status)
  SELECT subject.id, 'UTME-ENG', 'Use of English (objective)', 'objective', 60,
         NULL, NULL, false,
         'PDF page 3 itemises sixty questions across three sections. The document does not print the paper''s duration, its number of options per question, or any mark allocation; score_out_of is the schema default, not a printed value.',
         'planned', 'draft'
  FROM subject
  ON CONFLICT (subject_id, paper_code) DO NOTHING
  RETURNING id, paper_code, subject_id
),
all_papers AS (
  SELECT id, paper_code, subject_id FROM papers
  UNION
  SELECT p.id, p.paper_code, p.subject_id FROM exam_papers p, subject
  WHERE p.subject_id = subject.id AND p.paper_code = 'UTME-ENG'
)
INSERT INTO exam_paper_sections (exam_paper_id, subject_id, section_code, name,
  question_count, marks_total, curriculum_item_id, syllabus_version_id, source_location, review_status)
SELECT ap.id, ap.subject_id, s.code, s.name, s.questions, NULL, topic.id, version.id,
       s.location, 'pending'
FROM (VALUES
  -- Section A: Comprehension and Summary — 25 questions
  ('A-COMPREHENSION', 'Comprehension passage',   5, 'ENG.A', 'PDF page 3, Section A(a): "1comprehension passage - 5 questions"'),
  ('A-SUMMARY',       'Summary passage',         5, 'ENG.A', 'PDF page 3, Section A(b): "1 summary passage - 5 questions"'),
  ('A-CLOZE',         'Cloze passage',          10, 'ENG.A', 'PDF page 3, Section A(c): "1 cloze passage - 10 questions"'),
  ('A-READING-TEXT',  'Reading text',            5, 'ENG.A', 'PDF page 3, Section A(d): "1 reading text - 5 questions"'),
  -- Section B: Lexis and Structure — 25 questions
  ('B-SENTENCES',     'Sentence interpretation', 5, 'ENG.B', 'PDF page 3, Section B(a): "Sentence interpretation - 5 questions"'),
  ('B-ANTONYMS',      'Antonyms',                5, 'ENG.B', 'PDF page 3, Section B(b): "Antonyms - 5 questions"'),
  ('B-SYNONYMS',      'Synonyms',                5, 'ENG.B', 'PDF page 3, Section B(c): "Synonyms - 5questions"'),
  ('B-GRAMMAR',       'Basic grammar',          10, 'ENG.B', 'PDF page 3, Section B(d): "Basic Grammar - 10 questions"'),
  -- Section C: Oral Forms — 10 questions
  ('C-VOWELS',        'Vowels',                  2, 'ENG.C', 'PDF page 3, Section C(a): "Vowels - 2 questions"'),
  ('C-CONSONANTS',    'Consonants',              2, 'ENG.C', 'PDF page 3, Section C(b): "Consonants - 2 questions"'),
  ('C-RHYMES',        'Rhymes',                  2, 'ENG.C', 'PDF page 3, Section C(c): "Rhymes - 2 questions"'),
  ('C-WORD-STRESS',   'Word stress',             2, 'ENG.C', 'PDF page 3, Section C(d): "Word Stress - 2 questions"'),
  ('C-EMPHATIC',      'Emphatic stress',         2, 'ENG.C', 'PDF page 3, Section C(e): "Emphatic Stress - 2 questions"')
) AS s(code, name, questions, topic_code, location)
JOIN all_papers ap ON ap.paper_code = 'UTME-ENG'
CROSS JOIN version
JOIN curriculum_items topic
  ON topic.syllabus_version_id = version.id
 AND topic.code = s.topic_code
 AND topic.item_type = 'topic'
ON CONFLICT (exam_paper_id, section_code) DO NOTHING;

COMMIT;
