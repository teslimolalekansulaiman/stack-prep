-- Students, consent, and the evidence the engine learns from.
--
-- Three rules shape this migration:
--
--   1. Attempts are append-only. Mastery, plans and score ranges are all derived from
--      them, so a rewritten attempt would silently change a student's history. Updates
--      and deletes are blocked; erasure needs an explicit, auditable escape hatch.
--   2. No consent, no storage. Most candidates are 16-18, so an attempt cannot be stored
--      for a student who needs guardian consent until that consent exists. The database
--      enforces it, not the application.
--   3. Derived state is disposable. skill_ratings and review_state can be rebuilt by
--      replaying attempts under a known engine_version, so they carry that version.
--
-- Plans, score ranges and mock sessions arrive with the planner (see docs/roadmap.md);
-- they are derived from these tables and are deliberately not invented here.
BEGIN;
SET LOCAL search_path = stackprep, public;

-- ---------------------------------------------------------------------------
-- People
-- ---------------------------------------------------------------------------

-- One learner. Deliberately thin: no address, no national identifier, and a birth date
-- only when the product needs one.
CREATE TABLE students (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  display_name text NOT NULL CHECK (btrim(display_name) <> ''),
  phone text CHECK (phone IS NULL OR phone ~ '^\+?[0-9]{7,15}$'),
  email text CHECK (email IS NULL OR email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'),
  -- A school's own identifier, for students enrolled through a school rather than directly.
  external_ref text,
  date_of_birth date CHECK (date_of_birth IS NULL OR date_of_birth > DATE '1950-01-01'),
  -- Defaults to true: assume a minor until someone establishes otherwise.
  requires_guardian_consent boolean NOT NULL DEFAULT true,
  country_code char(2) NOT NULL DEFAULT 'NG',
  timezone text NOT NULL DEFAULT 'Africa/Lagos',
  status text NOT NULL DEFAULT 'invited' CHECK (status IN
    ('invited', 'active', 'suspended', 'archived')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (phone),
  UNIQUE (email),
  CHECK (phone IS NOT NULL OR email IS NOT NULL OR external_ref IS NOT NULL)
);
CREATE INDEX students_status_idx ON students(status);

CREATE TABLE guardians (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  display_name text NOT NULL CHECK (btrim(display_name) <> ''),
  phone text CHECK (phone IS NULL OR phone ~ '^\+?[0-9]{7,15}$'),
  email text CHECK (email IS NULL OR email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'),
  preferred_contact_method text NOT NULL DEFAULT 'sms' CHECK (preferred_contact_method IN
    ('sms', 'whatsapp', 'email', 'in_app')),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (phone IS NOT NULL OR email IS NOT NULL)
);

-- One verified guardian-student pair. A pending or revoked link reveals nothing.
CREATE TABLE guardian_students (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  guardian_id uuid NOT NULL REFERENCES guardians(id) ON DELETE RESTRICT,
  student_id uuid NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
  relationship_type text NOT NULL CHECK (relationship_type IN
    ('mother', 'father', 'guardian', 'other')),
  can_view_progress boolean NOT NULL DEFAULT true,
  can_receive_reports boolean NOT NULL DEFAULT false,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'active', 'revoked')),
  verified_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (guardian_id, student_id),
  UNIQUE (id, student_id),
  CHECK (status <> 'active' OR verified_at IS NOT NULL)
);
CREATE INDEX guardian_students_student_idx ON guardian_students(student_id, status);

-- One recorded consent decision. Consent is never inferred from a preference or a click
-- somewhere else; it is a row, with who gave it and what evidence exists.
CREATE TABLE consents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id uuid NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
  consent_type text NOT NULL CHECK (consent_type IN
    ('data_processing', 'research', 'results_collection', 'guardian_digest')),
  granted boolean NOT NULL,
  granted_by_guardian_id uuid,
  source text NOT NULL CHECK (source IN ('school_form', 'guardian_link', 'in_app')),
  evidence_note text,
  granted_at timestamptz NOT NULL DEFAULT now(),
  revoked_at timestamptz,
  FOREIGN KEY (granted_by_guardian_id, student_id)
    REFERENCES guardian_students(id, student_id) ON DELETE RESTRICT,
  CHECK (revoked_at IS NULL OR revoked_at >= granted_at),
  CHECK (NOT granted OR source <> 'school_form' OR btrim(coalesce(evidence_note, '')) <> '')
);
-- One live consent of each type per student; revoking and re-granting is a new row.
CREATE UNIQUE INDEX consents_one_live_per_type_idx
  ON consents(student_id, consent_type) WHERE revoked_at IS NULL;

-- ---------------------------------------------------------------------------
-- What the student is preparing for
-- ---------------------------------------------------------------------------

CREATE TABLE student_exam_goals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id uuid NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
  subject_id uuid NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
  -- Objective papers are scored out of 100 in this product (ADR-0014, ADR-0015); a target
  -- is per subject, never a total across subjects we do not cover.
  target_score numeric(5,2) CHECK (target_score > 0 AND target_score <= 100),
  exam_date date,
  minutes_per_day integer CHECK (minutes_per_day BETWEEN 5 AND 600),
  study_days smallint[] CHECK (
    study_days IS NULL OR (
      array_length(study_days, 1) BETWEEN 1 AND 7
      AND study_days <@ ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[]
    )
  ),
  status text NOT NULL DEFAULT 'active' CHECK (status IN
    ('active', 'paused', 'completed', 'cancelled')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX student_goals_one_active_per_subject_idx
  ON student_exam_goals(student_id, subject_id) WHERE status = 'active';

-- One sitting: a practice run, a check-up, a mock. Groups attempts for reporting.
CREATE TABLE study_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id uuid NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
  subject_id uuid REFERENCES subjects(id) ON DELETE RESTRICT,
  session_type text NOT NULL CHECK (session_type IN
    ('checkup', 'practice', 'review', 'guided', 'mixed', 'timed', 'mini_mock', 'full_mock')),
  planned_minutes integer CHECK (planned_minutes BETWEEN 1 AND 300),
  started_at timestamptz NOT NULL DEFAULT now(),
  ended_at timestamptz,
  was_offline boolean NOT NULL DEFAULT false,
  app_version text,
  engine_version text,
  CHECK (ended_at IS NULL OR ended_at >= started_at)
);
CREATE INDEX study_sessions_student_idx ON study_sessions(student_id, started_at DESC);

-- ---------------------------------------------------------------------------
-- Evidence
-- ---------------------------------------------------------------------------

-- One answered question. Append-only: this is the record everything else is derived from.
-- The primary key is generated on the device, so a retried sync stores one row.
CREATE TABLE attempts (
  id uuid PRIMARY KEY,
  student_id uuid NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
  question_version_id uuid NOT NULL REFERENCES question_versions(id) ON DELETE RESTRICT,
  session_id uuid REFERENCES study_sessions(id) ON DELETE RESTRICT,
  context text NOT NULL CHECK (context IN
    ('checkup', 'practice', 'review', 'guided', 'mixed', 'timed', 'mini_mock', 'full_mock')),
  selected_option_key text CHECK (selected_option_key IS NULL OR selected_option_key ~ '^[A-F]$'),
  is_correct boolean,
  response_ms integer CHECK (response_ms >= 0),
  hint_count smallint NOT NULL DEFAULT 0 CHECK (hint_count >= 0),
  solution_viewed_before_answer boolean NOT NULL DEFAULT false,
  -- Both clocks are kept: the device's, because it is when the student answered, and the
  -- server's, because a device clock can be wrong or deliberately moved.
  answered_at_client timestamptz NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now(),
  was_offline boolean NOT NULL DEFAULT false,
  app_version text,
  engine_version text,
  CHECK (is_correct IS NULL OR selected_option_key IS NOT NULL)
);
CREATE INDEX attempts_student_time_idx ON attempts(student_id, answered_at_client DESC);
CREATE INDEX attempts_question_idx ON attempts(question_version_id);
CREATE INDEX attempts_session_idx ON attempts(session_id);

-- ---------------------------------------------------------------------------
-- Derived state (rebuildable by replaying attempts)
-- ---------------------------------------------------------------------------

CREATE TABLE skill_ratings (
  student_id uuid NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
  skill_id uuid NOT NULL REFERENCES curriculum_items(id) ON DELETE RESTRICT,
  -- The Elo-style ability estimate from packages/engine.
  theta numeric(8,5) NOT NULL DEFAULT 0,
  scored_attempts integer NOT NULL DEFAULT 0 CHECK (scored_attempts >= 0),
  levels_seen smallint[] NOT NULL DEFAULT '{}',
  confidence text NOT NULL DEFAULT 'low' CHECK (confidence IN ('low', 'medium', 'high')),
  last_attempt_at timestamptz,
  last_success_at timestamptz,
  half_life_days numeric(6,2) NOT NULL DEFAULT 3 CHECK (half_life_days BETWEEN 1 AND 60),
  engine_version text NOT NULL,
  computed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (student_id, skill_id)
);
CREATE INDEX skill_ratings_skill_idx ON skill_ratings(skill_id);

CREATE TABLE review_state (
  student_id uuid NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
  skill_id uuid NOT NULL REFERENCES curriculum_items(id) ON DELETE RESTRICT,
  last_review_at timestamptz,
  next_review_at timestamptz,
  successful_reviews integer NOT NULL DEFAULT 0 CHECK (successful_reviews >= 0),
  failed_reviews integer NOT NULL DEFAULT 0 CHECK (failed_reviews >= 0),
  engine_version text NOT NULL,
  computed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (student_id, skill_id)
);
CREATE INDEX review_state_due_idx ON review_state(next_review_at) WHERE next_review_at IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Guards
-- ---------------------------------------------------------------------------

-- An attempt may only be stored once the student's consent exists.
CREATE FUNCTION check_attempt_consent() RETURNS trigger LANGUAGE plpgsql AS $$
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
    RAISE EXCEPTION 'this student has no recorded consent for data processing; the attempt cannot be stored';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER attempt_consent_guard BEFORE INSERT ON attempts
  FOR EACH ROW EXECUTE FUNCTION check_attempt_consent();

-- Attempts are the record of what a student actually did. Correcting marks happens by
-- recording a new row, never by editing history. Erasure is the one exception, and it has
-- to be asked for explicitly:
--   SET LOCAL scorepilot.allow_erasure = 'on';
CREATE FUNCTION protect_attempt_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF coalesce(current_setting('scorepilot.allow_erasure', true), 'off') <> 'on' THEN
    RAISE EXCEPTION 'attempts are append-only; record a correction instead of changing history';
  END IF;
  RETURN CASE TG_OP WHEN 'DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER attempt_history_guard BEFORE UPDATE OR DELETE ON attempts
  FOR EACH ROW EXECUTE FUNCTION protect_attempt_history();

-- A student's own answers cannot outlive their consent being withdrawn without someone
-- deciding what happens; the job that acts on a withdrawal uses the erasure setting above.

-- ---------------------------------------------------------------------------
-- Views
-- ---------------------------------------------------------------------------

-- What the planner reads: one row per student and skill, with its review position.
CREATE VIEW student_skill_state AS
SELECT r.student_id,
       r.skill_id,
       ci.code        AS skill_code,
       ci.name        AS skill_name,
       ci.subject_id,
       r.theta,
       r.scored_attempts,
       r.confidence,
       r.last_attempt_at,
       r.last_success_at,
       r.half_life_days,
       rs.next_review_at,
       rs.successful_reviews,
       rs.failed_reviews,
       r.engine_version
FROM skill_ratings r
JOIN curriculum_items ci ON ci.id = r.skill_id
LEFT JOIN review_state rs ON rs.student_id = r.student_id AND rs.skill_id = r.skill_id;

-- Daily activity, for the teacher list and the guardian digest. Counts only; no answers.
CREATE VIEW student_daily_activity AS
SELECT a.student_id,
       (a.answered_at_client AT TIME ZONE 'UTC')::date AS activity_date,
       count(*)                                        AS attempts,
       count(*) FILTER (WHERE a.is_correct)            AS correct,
       round(avg(a.response_ms))                       AS mean_response_ms,
       count(DISTINCT a.session_id)                    AS sessions
FROM attempts a
GROUP BY 1, 2;

COMMIT;
