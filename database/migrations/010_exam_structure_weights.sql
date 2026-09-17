-- Topic weights, derived rather than stored.
--
-- How much a topic is worth is a fact about the exam, so it is computed from the exam's
-- structure every time it is asked for. There is no stored share to go stale, and no job
-- to remember to re-run.
--
-- What it must NOT be computed from is our own question bank. Our 200 transcribed
-- questions currently sit 81% Lexis to 19% Structure, while the syllabus states Paper 1 is
-- 40 lexical and 40 structural questions. That gap is our tagging, not the exam. Deriving
-- weights from the bank would feed our sampling back into the plan: transcribe more lexis,
-- weight lexis higher, teach more lexis, and never notice.
--
-- So the input is `exam_paper_sections`: what each paper examines and how many questions it
-- asks, taken from the syllabus with a page citation and reviewed like any other academic
-- claim. Everything downstream is a view over it.
BEGIN;
SET LOCAL search_path = stackprep, public;

-- One section of one paper: what it examines, and how much of the paper it is.
CREATE TABLE exam_paper_sections (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  exam_paper_id uuid NOT NULL,
  subject_id uuid NOT NULL,
  section_code text NOT NULL CHECK (btrim(section_code) <> ''),
  name text NOT NULL CHECK (btrim(name) <> ''),
  question_count integer NOT NULL CHECK (question_count > 0),
  marks_total numeric(6,2) CHECK (marks_total > 0),
  -- The syllabus topic this section examines. Null when a section spans several topics,
  -- in which case it contributes to no topic's weight rather than to an arbitrary one.
  topic_id uuid,
  syllabus_version_id uuid,
  -- This is a claim about the examination, so it carries where it came from.
  source_location text NOT NULL CHECK (btrim(source_location) <> ''),
  review_status text NOT NULL DEFAULT 'draft' CHECK (review_status IN
    ('draft', 'pending', 'approved', 'rejected', 'withdrawn')),
  reviewed_by uuid REFERENCES academic_reviewers(id) ON DELETE RESTRICT,
  reviewed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (exam_paper_id, section_code),
  FOREIGN KEY (exam_paper_id, subject_id)
    REFERENCES exam_papers(id, subject_id) ON DELETE RESTRICT,
  FOREIGN KEY (topic_id, syllabus_version_id)
    REFERENCES curriculum_items(id, syllabus_version_id) ON DELETE RESTRICT,
  CHECK ((topic_id IS NULL) = (syllabus_version_id IS NULL)),
  CHECK (review_status <> 'approved' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL))
);
CREATE INDEX exam_paper_sections_topic_idx ON exam_paper_sections(topic_id, review_status);

-- What each topic is worth, computed from the exam's structure.
--
-- Objective papers only: the adaptive engine cannot mark an essay, so weighting a topic by
-- marks it can never help a student earn would misdirect every plan. Shares are normalised
-- across the topics that remain, and the row carries the marks behind them so a caller can
-- see how much of the subject this actually covers.
CREATE VIEW topic_exam_weight AS
WITH sections AS (
  SELECT s.syllabus_version_id,
         s.topic_id,
         s.question_count,
         coalesce(
           s.marks_total,
           p.score_out_of * s.question_count / nullif(p.question_count, 0)
         ) AS marks
  FROM exam_paper_sections s
  JOIN exam_papers p ON p.id = s.exam_paper_id
  WHERE s.review_status = 'approved'
    AND s.topic_id IS NOT NULL
    AND p.response_mode = 'objective'
    AND p.status <> 'retired'
)
SELECT syllabus_version_id,
       topic_id,
       sum(question_count)                                    AS expected_questions,
       round(sum(marks), 2)                                   AS expected_marks,
       round(sum(marks) / sum(sum(marks)) OVER (PARTITION BY syllabus_version_id), 4)
                                                              AS share,
       'exam_structure'::text                                 AS source
FROM sections
GROUP BY syllabus_version_id, topic_id;

-- What our own bank happens to contain, per topic. Reported so the gap between the exam and
-- our coverage is visible — never used as a weight.
CREATE VIEW topic_bank_coverage AS
SELECT topic.syllabus_version_id,
       topic.id                                               AS topic_id,
       topic.name                                             AS topic_name,
       count(*)                                               AS questions_in_bank,
       count(*) FILTER (WHERE q.usage_pool = 'diagnostic')     AS diagnostic_pool,
       count(*) FILTER (WHERE q.usage_pool = 'practice')       AS practice_pool,
       count(*) FILTER (WHERE q.usage_pool = 'held_out')       AS held_out_pool,
       count(*) FILTER (WHERE d.question_version_id IS NOT NULL) AS deliverable,
       round(100.0 * count(*) / nullif(sum(count(*)) OVER (PARTITION BY topic.syllabus_version_id), 0), 1)
                                                              AS pct_of_bank
FROM question_classifications c
JOIN curriculum_items skill ON skill.id = c.curriculum_item_id
JOIN curriculum_items sub ON sub.id = skill.parent_id
JOIN curriculum_items topic ON topic.id = sub.parent_id
JOIN questions q ON q.id = c.question_id
LEFT JOIN deliverable_questions d ON d.question_id = q.id
WHERE c.classification_role = 'primary'
GROUP BY topic.syllabus_version_id, topic.id, topic.name;

-- The two side by side: what the exam is worth, and what we can currently ask about it.
-- A topic with weight and no deliverable questions is a hole in the product, and this is
-- where it shows up.
CREATE VIEW topic_weight_vs_coverage AS
SELECT coalesce(w.syllabus_version_id, b.syllabus_version_id) AS syllabus_version_id,
       coalesce(w.topic_id, b.topic_id)                       AS topic_id,
       ci.name                                                AS topic_name,
       w.expected_questions,
       w.expected_marks,
       w.share,
       coalesce(b.questions_in_bank, 0)                       AS questions_in_bank,
       coalesce(b.deliverable, 0)                             AS deliverable,
       coalesce(b.diagnostic_pool, 0)                         AS diagnostic_pool
FROM topic_exam_weight w
FULL OUTER JOIN topic_bank_coverage b
  ON b.topic_id = w.topic_id AND b.syllabus_version_id = w.syllabus_version_id
JOIN curriculum_items ci ON ci.id = coalesce(w.topic_id, b.topic_id);

COMMIT;
