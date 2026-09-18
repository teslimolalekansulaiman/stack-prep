-- Where a question's worked solution and hints came from.
--
-- The answer has carried its provenance since the beginning, and the difficulty level since
-- 009. The explanation has not, and it is the part a student actually reads. Approval
-- requires a worked solution and at least one hint, so every approved question has them —
-- but nothing in the schema said whether a person wrote them, a model proposed them, or they
-- came with the source. A reviewer opening a question could not tell, and neither could a
-- query, which means the work of replacing thin explanations could not be found.
--
-- One column covers the solution and the hints together because they are written together
-- and are worth exactly as much as each other. Unlike the answer, this does NOT gate
-- approval: a model-proposed explanation on a verified answer is a question a student can
-- usefully sit, and blocking it would mean holding back correct questions over prose. What
-- it does is make the work visible, in a view that lists it.
BEGIN;
SET LOCAL search_path = stackprep, public;

ALTER TABLE question_versions
  ADD COLUMN solution_source text NOT NULL DEFAULT 'unverified'
    CHECK (solution_source IN ('unverified', 'model_proposed', 'published', 'expert_verified'));

COMMENT ON COLUMN question_versions.solution_source IS
  'Where solution_steps and hints came from. unverified: nothing written yet. '
  'model_proposed: generated, pending a human read. published: printed with the source '
  'document. expert_verified: a subject expert wrote or checked them. Unlike answer_source '
  'this does not gate approval; it makes the rewriting work findable.';

-- Questions carrying an explanation nobody has read. Deliberately includes approved ones:
-- that is the point — an approved question with a thin solution is in front of students now,
-- which makes it more urgent than a draft, not less.
CREATE VIEW questions_awaiting_explanation_check AS
SELECT q.id            AS question_id,
       v.id            AS question_version_id,
       q.subject_id,
       q.exam_year,
       q.question_number,
       v.stem,
       v.solution_source,
       v.review_status,
       jsonb_array_length(v.solution_steps) AS solution_steps,
       jsonb_array_length(v.hints)          AS hints,
       -- A question students are already being shown is the first one worth rewriting.
       (v.review_status = 'approved')       AS live
FROM question_versions v
JOIN questions q ON q.id = v.question_id
WHERE v.solution_source IN ('unverified', 'model_proposed')
  AND v.review_status <> 'withdrawn'
  AND q.retired_at IS NULL;

COMMIT;
