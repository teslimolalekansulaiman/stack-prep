-- What a guided attempt has to record that a check-up attempt did not.
--
-- The check-up asks once and moves on. Teaching asks, helps, and asks again, and the two
-- things a plan built on those answers needs are already half here: hint_count and
-- solution_viewed_before_answer have been on attempts since the beginning. Two are missing.
--
-- HOW SURE THEY WERE. A four-option question is right one time in four by accident, so a
-- correct answer is not evidence of knowledge on its own. Asking — sure, think so, guessed —
-- costs the student one tap and separates a lucky guess from a settled skill. Without it the
-- mastery estimate counts luck, the projection built on it is optimistic, and a guarantee
-- resting on that projection is a liability. It is nullable because it is a question a
-- student may decline, and a declined answer is not a guess.
--
-- WHAT THEY WROTE. Mathematics is marked on method, not on the final line, and the method
-- has to be stored to be marked. Nothing writes this yet — the working pad is a later phase —
-- but the column lands now so that every attempt recorded from the first guided session
-- onwards already has the right shape, and the day the pad arrives there is no backfill and
-- no second attempts table.
BEGIN;
SET LOCAL search_path = stackprep, public;

ALTER TABLE attempts
  ADD COLUMN confidence text
    CHECK (confidence IS NULL OR confidence IN ('guessed', 'unsure', 'sure')),
  ADD COLUMN working jsonb
    CHECK (working IS NULL OR jsonb_typeof(working) = 'object');

COMMENT ON COLUMN attempts.confidence IS
  'How sure the student said they were, asked after they answered and before they were told. '
  'NULL means they were not asked or declined to say, which is not the same as a guess.';
COMMENT ON COLUMN attempts.working IS
  'The steps the student showed, when the question asked for them. An object rather than an '
  'array so the capture method (typed, photographed, spoken) travels with the content.';

-- A correct answer the student called a guess is not evidence, and neither is one they only
-- reached after being shown the answer. This is the set that mastery may be built from, and
-- it exists so that no query has to remember the rule.
CREATE OR REPLACE VIEW scoring_attempts AS
SELECT a.*
FROM attempts a
WHERE NOT a.solution_viewed_before_answer
  AND a.hint_count = 0
  AND (a.confidence IS NULL OR a.confidence <> 'guessed' OR a.is_correct IS NOT TRUE);

COMMENT ON VIEW scoring_attempts IS
  'Attempts that may move a mastery estimate: unaided, and not a correct answer the student '
  'called a guess. A wrong answer always counts, however it was arrived at.';

COMMIT;
