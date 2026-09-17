-- A fourth kind of answer: one the source document supplied, from a publisher we have not
-- established as authoritative.
--
-- Until now an answer was either nobody's ('unverified'), ours ('model_proposed'), a
-- reviewer's ('expert_verified') or the examining board's ('official_key'). The JAMB
-- past-question compilation fits none of them: it prints an answer key for every year, so
-- the answer is not our guess — but the key is a third-party compiler's (toppers.com.ng),
-- not JAMB's marking scheme, and it visibly contains gaps ("71. NO ANSWER") and typographic
-- damage. Calling it 'official_key' would be a lie that the approval constraint accepts,
-- and calling it 'model_proposed' would be a lie that hides a real, citable source.
--
-- So: 'published_key'. It carries more weight than a proposal when a reviewer is checking a
-- question, and none at all when the database decides whether a student may see it —
-- approval still requires 'expert_verified' or 'official_key', unchanged below.
BEGIN;
SET LOCAL search_path = stackprep, public;

ALTER TABLE question_versions
  DROP CONSTRAINT question_versions_answer_source_check,
  ADD CONSTRAINT question_versions_answer_source_check CHECK (answer_source IN
    ('unverified', 'model_proposed', 'published_key', 'expert_verified', 'official_key'));

COMMENT ON COLUMN question_versions.answer_source IS
  'unverified: no key yet. model_proposed: proposed by a model, pending human check. '
  'published_key: printed with the source document by a publisher whose authority we have '
  'not established. expert_verified: a subject expert confirmed it. official_key: taken '
  'from an official marking scheme. Approval requires one of the last two.';

-- The review queue exists to show a human what still needs checking, so a published key
-- belongs in it exactly like a proposal. Same view, same columns, one more source.
CREATE OR REPLACE VIEW questions_awaiting_answer_check AS
SELECT q.id            AS question_id,
       v.id            AS question_version_id,
       q.subject_id,
       q.exam_year,
       q.paper_code,
       q.question_number,
       v.stem,
       v.answer_source,
       v.answer_confidence,
       (SELECT o.option_key FROM question_options o
         WHERE o.question_version_id = v.id AND o.is_correct) AS proposed_key,
       v.review_status,
       v.created_at
FROM question_versions v
JOIN questions q ON q.id = v.question_id
WHERE v.answer_source IN ('unverified', 'model_proposed', 'published_key')
  AND v.review_status <> 'withdrawn';

COMMIT;
