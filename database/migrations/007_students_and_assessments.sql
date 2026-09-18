-- Students, the assessments we give them, and the answers they give back.
--
-- Section B of the data model (what the exam covers) is built. This is the first
-- slice of the student side: enough to run one learner through one assessment and
-- record every answer, with the evidence the engine needs to rate them.
--
-- Mastery state is deliberately NOT here. It follows packages/engine, not the
-- v1.1 data model document, which disagrees with the engine on how a rating is
-- stored -- see docs/data-model-divergences.md. It lands in its own migration.
--
-- Authentication is deliberately thin: ADR-0013 has not chosen a provider, so
-- users.auth_provider_id is a nullable placeholder rather than a guess.
BEGIN;
SET LOCAL search_path = stackprep, public;

-- ---------------------------------------------------------------- identity ---

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  first_name text NOT NULL CHECK (btrim(first_name) <> ''),
  last_name text NOT NULL CHECK (btrim(last_name) <> ''),
  email text CHECK (email IS NULL OR email LIKE '_%@_%._%'),
  phone text CHECK (phone IS NULL OR btrim(phone) <> ''),
  -- Set once ADR-0013 picks an identity provider. Until then a person exists in
  -- this table but cannot sign in, which is the honest state of the product.
  auth_provider_id text UNIQUE,
  role text NOT NULL CHECK (role IN ('student', 'guardian', 'reviewer', 'admin')),
  status text NOT NULL DEFAULT 'invited' CHECK (status IN
    ('invited', 'active', 'suspended', 'archived')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  -- A person we cannot contact cannot be invited or recovered.
  CHECK (email IS NOT NULL OR phone IS NOT NULL),
  UNIQUE (id, role)
);
CREATE UNIQUE INDEX users_email_idx ON users(lower(email)) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX users_phone_idx ON users(phone) WHERE phone IS NOT NULL;

CREATE TABLE student_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL UNIQUE,
  -- Constant, so the composite key below can only resolve against a student.
  user_role text NOT NULL GENERATED ALWAYS AS ('student') STORED,
  date_of_birth date CHECK (date_of_birth IS NULL OR date_of_birth > date '1900-01-01'),
  school_name text,
  class_level text,
  country_code char(2) NOT NULL DEFAULT 'NG',
  timezone text NOT NULL DEFAULT 'Africa/Lagos' CHECK (btrim(timezone) <> ''),
  onboarding_status text NOT NULL DEFAULT 'registered' CHECK (onboarding_status IN
    ('registered', 'goal_set', 'diagnosed', 'active')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  -- The database, not the application, is what stops a guardian's account
  -- acquiring a student profile.
  FOREIGN KEY (user_id, user_role) REFERENCES users(id, role) ON DELETE RESTRICT
);

-- ------------------------------------------------------------- assessments ---

CREATE TABLE assessments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  examination_id uuid NOT NULL REFERENCES examinations(id) ON DELETE RESTRICT,
  subject_id uuid NOT NULL,
  title text NOT NULL CHECK (btrim(title) <> ''),
  instructions text,
  assessment_type text NOT NULL CHECK (assessment_type IN
    ('diagnostic', 'practice', 'checkpoint', 'mock')),
  delivery_mode text NOT NULL DEFAULT 'fixed' CHECK (delivery_mode IN ('fixed', 'adaptive')),
  duration_minutes integer CHECK (duration_minutes > 0),
  total_marks numeric(8,2) CHECK (total_marks >= 0),
  -- A set built for one learner, e.g. their personal diagnostic.
  created_for_student_id uuid REFERENCES student_profiles(id) ON DELETE RESTRICT,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN
    ('draft', 'published', 'closed', 'archived')),
  created_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz,
  -- The subject has to belong to the examination; this is what enforces it.
  FOREIGN KEY (subject_id, examination_id) REFERENCES subjects(id, examination_id) ON DELETE RESTRICT,
  CHECK (status = 'draft' OR published_at IS NOT NULL),
  UNIQUE (id, subject_id)
);
CREATE INDEX assessments_subject_idx ON assessments(subject_id, status);
CREATE INDEX assessments_student_idx ON assessments(created_for_student_id)
  WHERE created_for_student_id IS NOT NULL;

CREATE TABLE assessment_questions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  assessment_id uuid NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
  question_id uuid NOT NULL,
  -- A placement freezes one *version*. Questions are versioned here (003), and a
  -- student marked against version 2 must never be re-read against version 3.
  question_version_id uuid NOT NULL,
  position integer NOT NULL CHECK (position > 0),
  marks numeric(6,2) NOT NULL CHECK (marks > 0),
  required boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (assessment_id, position),
  UNIQUE (assessment_id, question_id),
  UNIQUE (id, assessment_id),
  FOREIGN KEY (question_version_id, question_id)
    REFERENCES question_versions(id, question_id) ON DELETE RESTRICT
);
CREATE INDEX assessment_questions_question_idx ON assessment_questions(question_id);

-- ---------------------------------------------------------------- sittings ---

CREATE TABLE assessment_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  assessment_id uuid NOT NULL REFERENCES assessments(id) ON DELETE RESTRICT,
  student_id uuid NOT NULL REFERENCES student_profiles(id) ON DELETE RESTRICT,
  attempt_number integer NOT NULL DEFAULT 1 CHECK (attempt_number > 0),
  started_at timestamptz,
  submitted_at timestamptz,
  raw_score numeric(8,2) CHECK (raw_score >= 0),
  maximum_score numeric(8,2) CHECK (maximum_score >= 0),
  percentage numeric(5,2) CHECK (percentage BETWEEN 0 AND 100),
  status text NOT NULL DEFAULT 'not_started' CHECK (status IN
    ('not_started', 'in_progress', 'submitted', 'marked', 'abandoned')),
  -- Which engine rules were in force. Derived state is replayed under a known
  -- version (packages/engine/version.py), so it is part of the data.
  engine_version text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (student_id, assessment_id, attempt_number),
  UNIQUE (id, assessment_id),
  CHECK (submitted_at IS NULL OR started_at IS NOT NULL),
  CHECK (submitted_at IS NULL OR submitted_at >= started_at),
  CHECK (raw_score IS NULL OR maximum_score IS NULL OR raw_score <= maximum_score),
  CHECK (status <> 'marked' OR (raw_score IS NOT NULL AND maximum_score IS NOT NULL))
);
CREATE INDEX assessment_attempts_student_idx ON assessment_attempts(student_id, status);

CREATE TABLE student_responses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  attempt_id uuid NOT NULL,
  -- Carried so the two composite keys below can prove that this placement and
  -- this sitting belong to the same assessment. A response can never point at a
  -- question the student was not actually given.
  assessment_id uuid NOT NULL,
  assessment_question_id uuid NOT NULL,
  selected_option_id uuid REFERENCES question_options(id) ON DELETE RESTRICT,
  answer jsonb,
  working jsonb,
  awarded_marks numeric(6,2) CHECK (awarded_marks >= 0),
  maximum_marks numeric(6,2) NOT NULL CHECK (maximum_marks > 0),
  is_correct boolean,
  marking_status text NOT NULL DEFAULT 'unmarked' CHECK (marking_status IN
    ('unmarked', 'auto_marked', 'needs_review', 'reviewed')),
  marking_feedback text,
  -- The evidence packages/engine needs to fold this answer into a rating. Names
  -- match engine.mastery.Attempt so nothing is translated on the way in.
  response_ms integer CHECK (response_ms >= 0),
  hint_used boolean NOT NULL DEFAULT false,
  solution_viewed_before_answer boolean NOT NULL DEFAULT false,
  submitted_at timestamptz,
  marked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (attempt_id, assessment_question_id),
  FOREIGN KEY (attempt_id, assessment_id)
    REFERENCES assessment_attempts(id, assessment_id) ON DELETE CASCADE,
  FOREIGN KEY (assessment_question_id, assessment_id)
    REFERENCES assessment_questions(id, assessment_id) ON DELETE RESTRICT,
  CHECK (awarded_marks IS NULL OR awarded_marks <= maximum_marks),
  CHECK (marking_status = 'unmarked' OR (awarded_marks IS NOT NULL AND marked_at IS NOT NULL))
);
CREATE INDEX student_responses_attempt_idx ON student_responses(attempt_id);

-- ------------------------------------------------------------------ rules ---
-- Constraints cover what one row can say about itself. These cover the rest.

CREATE OR REPLACE FUNCTION check_assessment_publish() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  placed integer;
  undeliverable integer;
BEGIN
  IF NEW.status = 'published' AND (TG_OP = 'INSERT' OR OLD.status <> 'published') THEN
    SELECT count(*) INTO placed FROM assessment_questions WHERE assessment_id = NEW.id;
    IF placed = 0 THEN
      RAISE EXCEPTION 'an assessment cannot be published with no questions in it';
    END IF;

    -- deliverable_questions (003) is the view that already decides what a
    -- candidate may be shown: approved, licensed, answer verified.
    SELECT count(*) INTO undeliverable
      FROM assessment_questions aq
      WHERE aq.assessment_id = NEW.id
        AND NOT EXISTS (
          SELECT 1 FROM deliverable_questions dq
          WHERE dq.question_version_id = aq.question_version_id
        );
    IF undeliverable > 0 THEN
      RAISE EXCEPTION
        'cannot publish: % placed question(s) are not approved for delivery', undeliverable;
    END IF;
  END IF;

  IF TG_OP = 'UPDATE' AND OLD.status = 'published' AND NEW.status = 'draft' THEN
    RAISE EXCEPTION 'a published assessment cannot return to draft; close it instead';
  END IF;

  RETURN NEW;
END $$;

CREATE TRIGGER assessments_publish_guard
  BEFORE INSERT OR UPDATE ON assessments
  FOR EACH ROW EXECUTE FUNCTION check_assessment_publish();

CREATE OR REPLACE FUNCTION check_assessment_question() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  parent record;
  target uuid;
BEGIN
  target := CASE TG_OP WHEN 'DELETE' THEN OLD.assessment_id ELSE NEW.assessment_id END;
  SELECT * INTO parent FROM assessments WHERE id = target;

  -- Content freezes at publication. Otherwise a student's marked paper could be
  -- edited underneath them after the fact.
  IF parent.status <> 'draft' THEN
    RAISE EXCEPTION 'the questions in a % assessment are frozen', parent.status;
  END IF;

  IF TG_OP <> 'DELETE' THEN
    IF NOT EXISTS (
      SELECT 1 FROM question_versions v
      WHERE v.id = NEW.question_version_id AND v.subject_id = parent.subject_id
    ) THEN
      RAISE EXCEPTION 'that question belongs to a different subject than this assessment';
    END IF;
  END IF;

  RETURN CASE TG_OP WHEN 'DELETE' THEN OLD ELSE NEW END;
END $$;

CREATE TRIGGER assessment_questions_guard
  BEFORE INSERT OR UPDATE OR DELETE ON assessment_questions
  FOR EACH ROW EXECUTE FUNCTION check_assessment_question();

CREATE OR REPLACE FUNCTION check_assessment_attempt() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  parent record;
BEGIN
  SELECT * INTO parent FROM assessments WHERE id = NEW.assessment_id;
  IF TG_OP = 'INSERT' AND parent.status <> 'published' THEN
    RAISE EXCEPTION 'a student cannot sit a % assessment', parent.status;
  END IF;

  -- Rescoring happens by recording a correction, never by quietly overwriting a
  -- result the student has already been given.
  IF TG_OP = 'UPDATE' AND OLD.status = 'marked' AND NEW.status <> 'marked' THEN
    RAISE EXCEPTION 'a marked attempt cannot be reopened; record a correction instead';
  END IF;

  RETURN NEW;
END $$;

CREATE TRIGGER assessment_attempts_guard
  BEFORE INSERT OR UPDATE ON assessment_attempts
  FOR EACH ROW EXECUTE FUNCTION check_assessment_attempt();

CREATE OR REPLACE FUNCTION check_student_response() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  placement record;
  attempt record;
BEGIN
  SELECT * INTO placement FROM assessment_questions WHERE id = NEW.assessment_question_id;
  SELECT * INTO attempt FROM assessment_attempts WHERE id = NEW.attempt_id;

  IF NEW.maximum_marks IS DISTINCT FROM placement.marks THEN
    RAISE EXCEPTION 'maximum_marks (%) does not match the % marks this question is placed at',
      NEW.maximum_marks, placement.marks;
  END IF;

  -- A chosen option must be one of the options actually shown for the exact
  -- version the student was given.
  IF NEW.selected_option_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM question_options o
    WHERE o.id = NEW.selected_option_id
      AND o.question_version_id = placement.question_version_id
  ) THEN
    RAISE EXCEPTION 'that option does not belong to the question version the student was given';
  END IF;

  IF TG_OP = 'INSERT' AND attempt.status NOT IN ('not_started', 'in_progress') THEN
    RAISE EXCEPTION 'cannot add an answer to a % attempt', attempt.status;
  END IF;

  RETURN NEW;
END $$;

CREATE TRIGGER student_responses_guard
  BEFORE INSERT OR UPDATE ON student_responses
  FOR EACH ROW EXECUTE FUNCTION check_student_response();

COMMIT;
