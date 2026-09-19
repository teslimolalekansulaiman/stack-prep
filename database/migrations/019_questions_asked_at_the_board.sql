-- What the student asked the coach, and what the coach said back.
--
-- The board has been one-way since it was built: it writes the reviewed `solution_steps` and
-- the student reads them. A student who follows four steps and loses the fifth has nowhere to
-- put "why did we square both sides?", and the loop's answer — miss it again, read the same
-- five steps again — is not teaching. This is the table behind letting them ask.
--
-- WHY THE ASKING IS STORED AT ALL. Three reasons, and each one would be enough on its own.
--
-- REQ-16 says a review request carries the explanation the student was shown. Once part of
-- that explanation is generated per student, the reviewed steps no longer describe what they
-- read, and a reviewer judging a complaint about a lesson has to be able to see the lesson
-- that actually happened rather than the one in the question bank.
--
-- REQ-05 says assistance is recorded. A question asked at the board is assistance. It changes
-- no mastery estimate — the board is only reached after the item is already taught rather
-- than answered, and nothing here is scored — but "this student needed four explanations to
-- get through one item" is exactly the evidence a plan should see, and it cannot see what was
-- never written down.
--
-- And the daily budget is counted from here. `ai_daily_calls_per_student` cannot be enforced
-- by a browser that has every reason to lose count, so the count is the number of rows a
-- student already has today, in their own timezone, and the cap is applied by the server that
-- writes them.
--
-- WHY THE FALLBACK IS STORED TOO. When the tutor is unavailable the student still gets an
-- answer — the reviewed steps, said plainly, per REQ-24 — and that turn is recorded with
-- `source = 'fallback'`. If the failures are not in the same table as the successes, the only
-- reading of this table is a flattering one, and the cost and reliability question that
-- Expansion B is supposed to settle cannot be answered from it.
--
-- WHAT IS DELIBERATELY NOT HERE. No audio and no transcript column: student voice is out of
-- scope for the pilot and stays out until the legal review has ruled on recording a minor.
-- This table holds typed text the student chose to send.
BEGIN;
SET LOCAL search_path = stackprep, public;

CREATE TABLE tutor_turns (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id uuid NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
  session_id uuid NOT NULL REFERENCES study_sessions(id) ON DELETE RESTRICT,
  -- The item version, not the question: the steps that were on the board belong to a version,
  -- and a later correction to the explanation must not rewrite what this student was told.
  question_version_id uuid NOT NULL REFERENCES question_versions(id) ON DELETE RESTRICT,
  -- Which line of the working was showing when they asked. Null means the board had finished
  -- writing. It is what makes "why did you do that?" answerable at all.
  step_index smallint CHECK (step_index IS NULL OR step_index >= 0),
  asked text NOT NULL CHECK (btrim(asked) <> ''),
  reply text NOT NULL CHECK (btrim(reply) <> ''),
  source text NOT NULL CHECK (source IN ('model', 'fallback', 'budget')),
  model text,
  input_tokens integer CHECK (input_tokens IS NULL OR input_tokens >= 0),
  output_tokens integer CHECK (output_tokens IS NULL OR output_tokens >= 0),
  -- Measured here rather than in the browser, so the 15-second service target is read from
  -- the thing being promised and not from the student's connection.
  latency_ms integer CHECK (latency_ms IS NULL OR latency_ms >= 0),
  asked_at timestamptz NOT NULL DEFAULT now(),
  -- A turn that says a model answered has to say which one: a benchmark of 100 interactions
  -- means nothing if the rows cannot be attributed to the model that produced them.
  CHECK ((source = 'model') = (model IS NOT NULL))
);

COMMENT ON TABLE tutor_turns IS
  'One question a student asked the coach at the board, and the answer they were given. '
  'Append-only. The daily AI budget is counted from it, and a review request reads it to see '
  'the lesson the student actually had rather than the reviewed steps alone.';
COMMENT ON COLUMN tutor_turns.source IS
  'model: the tutor answered. fallback: the tutor was unavailable or refused, and the '
  'reviewed steps were served instead. budget: the student had spent their daily allowance, '
  'and the reviewed steps were served instead.';

CREATE INDEX tutor_turns_student_day_idx ON tutor_turns(student_id, asked_at DESC);
CREATE INDEX tutor_turns_session_idx ON tutor_turns(session_id);
CREATE INDEX tutor_turns_question_idx ON tutor_turns(question_version_id);

-- A student's own words about what they do not understand are more personal than the option
-- key that sits next to them in `attempts`, so they are held to the same consent rule and not
-- a weaker one.
CREATE FUNCTION check_tutor_turn_consent() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE needs_consent boolean;
BEGIN
  SELECT requires_guardian_consent INTO needs_consent FROM students WHERE id = NEW.student_id;
  IF needs_consent IS NULL THEN
    RAISE EXCEPTION 'unknown student';
  END IF;
  IF needs_consent AND NOT EXISTS (
    SELECT 1 FROM consents
    WHERE student_id = NEW.student_id AND consent_type = 'data_processing'
      AND granted AND revoked_at IS NULL
  ) THEN
    RAISE EXCEPTION 'this student has no recorded consent for data processing; the question cannot be stored';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER tutor_turn_consent_guard BEFORE INSERT ON tutor_turns
  FOR EACH ROW EXECUTE FUNCTION check_tutor_turn_consent();

-- Same rule as attempts: this is a record of what happened, so it is not edited. Erasure on
-- withdrawal of consent is the one exception and has to be asked for:
--   SET LOCAL scorepilot.allow_erasure = 'on';
CREATE FUNCTION protect_tutor_turn_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF coalesce(current_setting('scorepilot.allow_erasure', true), 'off') <> 'on' THEN
    RAISE EXCEPTION 'tutor turns are append-only; they record what a student was actually told';
  END IF;
  RETURN CASE TG_OP WHEN 'DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER tutor_turn_history_guard BEFORE UPDATE OR DELETE ON tutor_turns
  FOR EACH ROW EXECUTE FUNCTION protect_tutor_turn_history();

COMMIT;
