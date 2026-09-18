-- A session planned as a number of questions, not a number of minutes.
--
-- study_sessions has carried planned_minutes since the beginning, which is the right shape
-- for a timed practice run. A guided session is not that: it is "ten questions, however long
-- they take", because the loop stops to teach and a student who needed three explanations has
-- done more work in the same wall-clock time, not less. Recording the intent in minutes would
-- mean the server either cut a lesson short or ran past its own plan.
--
-- Both columns are nullable and a session may set either, or neither for one that runs until
-- the student stops.
BEGIN;
SET LOCAL search_path = stackprep, public;

ALTER TABLE study_sessions
  ADD COLUMN planned_items integer CHECK (planned_items > 0 AND planned_items <= 200);

COMMENT ON COLUMN study_sessions.planned_items IS
  'How many questions this session intends to ask. Set instead of planned_minutes when the '
  'session stops to teach, because time spent then depends on how much help was needed.';

COMMIT;
