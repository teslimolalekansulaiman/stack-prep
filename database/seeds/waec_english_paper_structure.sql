-- WAEC English Language 2027: the papers and what each section examines.
--
-- Every number here is printed in "docs/syllabus/waec - English 2027.pdf" and cited to its
-- page. Nothing is inferred, and nothing is derived from our own question bank.
--
-- Rows are inserted as PENDING review. Topic weights only count approved sections, so a
-- subject lead has to agree with this reading of the syllabus before it steers anything:
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
  WHERE s.code = 'ENG' AND e.short_name = 'WASSCE'
  LIMIT 1
),
version AS (
  SELECT v.id FROM syllabus_versions v, subject
  WHERE v.subject_id = subject.id AND v.version_label = 'waec-2027'
  LIMIT 1
),
papers AS (
  INSERT INTO exam_papers (subject_id, paper_code, name, response_mode, question_count,
    duration_minutes, options_per_question, score_out_of, values_confirmed,
    confirmation_note, pilot_support_status, status)
  SELECT subject.id, p.code, p.name, p.mode, p.questions, p.minutes, p.options, p.marks,
         p.confirmed, p.note, p.support, 'draft'
  FROM subject, (VALUES
    ('2027-P1', 'Paper 1 (objective)', 'objective', 80, 60, 4::smallint, 40::numeric, true,
     'PDF page 1: "eighty multiple choice questions, all of which should be answered within 1 hour for 40 marks"; page 2: four options lettered A to D.',
     'supported'),
    ('2027-P2', 'Paper 2 (essay, comprehension, summary)', 'theory', NULL, 120, NULL, 100::numeric, false,
     'PDF page 1: two hours, 100 marks. Question count varies by section and is not fixed in the syllabus.',
     'unsupported'),
    ('2027-P3', 'Paper 3 (Test of Orals / Listening Comprehension)', 'objective', 60, 45, 4::smallint, 30::numeric, true,
     'PDF page 1: "sixty multiple choice items ... answered in 45 minutes for 30 marks".',
     'planned')
  ) AS p(code, name, mode, questions, minutes, options, marks, confirmed, note, support)
  ON CONFLICT (subject_id, paper_code) DO NOTHING
  RETURNING id, paper_code, subject_id
),
all_papers AS (
  SELECT id, paper_code, subject_id FROM papers
  UNION
  SELECT p.id, p.paper_code, p.subject_id FROM exam_papers p, subject
  WHERE p.subject_id = subject.id AND p.paper_code IN ('2027-P1', '2027-P2', '2027-P3')
)
INSERT INTO exam_paper_sections (exam_paper_id, subject_id, section_code, name,
  question_count, marks_total, topic_id, syllabus_version_id, source_location, review_status)
SELECT ap.id, ap.subject_id, s.code, s.name, s.questions, s.marks, topic.id, version.id,
       s.location, 'pending'
FROM (VALUES
  ('2027-P1', 'LEXIS', 'Lexis', 40, 20::numeric, 'ENG.1',
   'PDF page 2: "forty lexical and forty structural questions"'),
  ('2027-P1', 'STRUCTURE', 'Structure', 40, 20::numeric, 'ENG.2',
   'PDF page 2: "forty lexical and forty structural questions"'),
  ('2027-P3', 'ORALS', 'Test of Orals', 60, 30::numeric, 'ENG.6',
   'PDF page 9: sixty multiple choice questions on vowels, consonants, rhymes, stress, intonation and phonetic symbols')
) AS s(paper_code, code, name, questions, marks, topic_code, location)
JOIN all_papers ap ON ap.paper_code = s.paper_code
CROSS JOIN version
JOIN curriculum_items topic
  ON topic.syllabus_version_id = version.id
 AND topic.code = s.topic_code
 AND topic.item_type = 'topic'
ON CONFLICT (exam_paper_id, section_code) DO NOTHING;

COMMIT;
