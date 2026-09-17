-- Exams are not practice.
--
-- A sitting has a form fixed before it starts, a deadline the server owns, no hints, and a
-- score in which an unanswered question is not the same as a wrong one. Practice has none
-- of that: items are chosen one at a time, hints are part of the point, and there is no
-- score. Putting both under one set of rules leaves the exam's rules unenforced.
--
-- What is NOT split is the evidence. `attempts` stays the single record of "this student
-- answered this item, this way, in this long", because mastery, item statistics and
-- calibration all read it. Splitting it would make every one of those queries a union, and
-- any query that forgot half would be quietly wrong.
--
-- So: assessments own the exam's structure and administration; attempts stay the evidence;
-- study_sessions becomes learning-only.
BEGIN;
SET LOCAL search_path = stackprep, public;

-- ---------------------------------------------------------------------------
-- The form
-- ---------------------------------------------------------------------------

-- One assembled paper: a check-up, a mini-mock, a full mock. Frozen at publication.
CREATE TABLE assessments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_id uuid NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
  exam_paper_id uuid,
  title text NOT NULL CHECK (btrim(title) <> ''),
  assessment_type text NOT NULL CHECK (assessment_type IN
    ('checkup', 'topic_quiz', 'mini_mock', 'full_mock')),
  -- Which pool its questions must come from. Mocks measure, so they draw on held-out
  -- items the student cannot have practised; a check-up uses its own pool.
  required_pool text NOT NULL CHECK (required_pool IN ('practice', 'diagnostic', 'held_out')),
  duration_minutes integer CHECK (duration_minutes BETWEEN 1 AND 300),
  -- Set at publication from the placements, so a score always has a denominator.
  total_marks numeric(8,2) CHECK (total_marks > 0),
  created_for_student_id uuid REFERENCES students(id) ON DELETE RESTRICT,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN
    ('draft', 'published', 'closed', 'archived')),
  published_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, subject_id),
  FOREIGN KEY (exam_paper_id, subject_id)
    REFERENCES exam_papers(id, subject_id) ON DELETE RESTRICT,
  CHECK (status = 'draft' OR (published_at IS NOT NULL AND total_marks IS NOT NULL))
);
CREATE INDEX assessments_subject_idx ON assessments(subject_id, assessment_type, status);

-- One question's placement in one assessment: its position, and what it is worth here.
CREATE TABLE assessment_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  assessment_id uuid NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
  question_version_id uuid NOT NULL REFERENCES question_versions(id) ON DELETE RESTRICT,
  position integer NOT NULL CHECK (position > 0),
  marks numeric(6,2) NOT NULL CHECK (marks > 0),
  required boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (assessment_id, position),
  -- The same question cannot appear twice in one paper.
  UNIQUE (assessment_id, question_version_id),
  -- Lets an attempt prove its placement belongs to its sitting's assessment …
  UNIQUE (id, assessment_id),
  -- … and that it answered the question actually placed there.
  UNIQUE (id, question_version_id)
);
CREATE INDEX assessment_items_question_idx ON assessment_items(question_version_id);

-- ---------------------------------------------------------------------------
-- The sitting
-- ---------------------------------------------------------------------------

-- One student taking one assessment once. The deadline belongs to the server: a device
-- clock is not evidence of when time ran out.
CREATE TABLE assessment_sittings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  assessment_id uuid NOT NULL REFERENCES assessments(id) ON DELETE RESTRICT,
  student_id uuid NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
  attempt_number integer NOT NULL DEFAULT 1 CHECK (attempt_number > 0),
  started_at timestamptz NOT NULL DEFAULT now(),
  deadline_at timestamptz NOT NULL,
  submitted_at timestamptz,
  auto_submitted boolean NOT NULL DEFAULT false,
  status text NOT NULL DEFAULT 'in_progress' CHECK (status IN
    ('in_progress', 'submitted', 'marked', 'abandoned')),
  raw_score numeric(8,2) CHECK (raw_score >= 0),
  max_score numeric(8,2) CHECK (max_score > 0),
  marked_at timestamptz,
  UNIQUE (assessment_id, student_id, attempt_number),
  UNIQUE (id, assessment_id),
  CHECK (deadline_at > started_at),
  CHECK (submitted_at IS NULL OR submitted_at >= started_at),
  CHECK (status <> 'in_progress' OR submitted_at IS NULL),
  CHECK (status IN ('in_progress', 'abandoned') OR submitted_at IS NOT NULL),
  CHECK (status <> 'marked' OR (raw_score IS NOT NULL AND max_score IS NOT NULL
         AND marked_at IS NOT NULL AND raw_score <= max_score))
);
CREATE INDEX sittings_student_idx ON assessment_sittings(student_id, started_at DESC);
CREATE INDEX sittings_open_idx ON assessment_sittings(status) WHERE status = 'in_progress';

-- ---------------------------------------------------------------------------
-- Attempts: one evidence stream, two contexts
-- ---------------------------------------------------------------------------

ALTER TABLE attempts
  ADD COLUMN sitting_id uuid,
  ADD COLUMN assessment_id uuid,
  ADD COLUMN assessment_item_id uuid,
  -- The sitting's placement is the authority on where this answer belongs …
  ADD CONSTRAINT attempts_sitting_fkey
    FOREIGN KEY (sitting_id, assessment_id)
    REFERENCES assessment_sittings(id, assessment_id) ON DELETE RESTRICT,
  ADD CONSTRAINT attempts_placement_fkey
    FOREIGN KEY (assessment_item_id, assessment_id)
    REFERENCES assessment_items(id, assessment_id) ON DELETE RESTRICT,
  -- … and the answer must be to the question actually placed there.
  ADD CONSTRAINT attempts_placement_question_fkey
    FOREIGN KEY (assessment_item_id, question_version_id)
    REFERENCES assessment_items(id, question_version_id) ON DELETE RESTRICT,
  -- An attempt is either learning or an exam response, never both and never neither.
  ADD CONSTRAINT attempts_one_home_check
    CHECK ((session_id IS NULL) <> (sitting_id IS NULL)),
  ADD CONSTRAINT attempts_exam_columns_check
    CHECK ((sitting_id IS NULL) = (assessment_item_id IS NULL)
       AND (sitting_id IS NULL) = (assessment_id IS NULL)),
  -- Hints and solutions exist to teach; in an exam they would be cheating.
  ADD CONSTRAINT attempts_no_help_in_exams_check
    CHECK (sitting_id IS NULL OR (hint_count = 0 AND NOT solution_viewed_before_answer));

CREATE INDEX attempts_sitting_idx ON attempts(sitting_id, assessment_item_id);

-- Learning sessions are for learning. Mock types move to assessments.
DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'stackprep.study_sessions'::regclass
      AND conname = 'study_sessions_session_type_check'
  ) THEN
    ALTER TABLE study_sessions DROP CONSTRAINT study_sessions_session_type_check;
  END IF;
END $$;
ALTER TABLE study_sessions
  ADD CONSTRAINT study_sessions_session_type_check
  CHECK (session_type IN ('checkup', 'practice', 'review', 'guided', 'mixed', 'timed'));

-- ---------------------------------------------------------------------------
-- Guards
-- ---------------------------------------------------------------------------

-- A published paper cannot change: two students' results must mean the same thing.
CREATE FUNCTION check_assessment_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE state text;
BEGIN
  SELECT status INTO state FROM assessments
   WHERE id = CASE TG_OP WHEN 'DELETE' THEN OLD.assessment_id ELSE NEW.assessment_id END;
  IF state IS NOT NULL AND state <> 'draft' THEN
    RAISE EXCEPTION 'this assessment is published; its questions and marks are frozen';
  END IF;
  RETURN CASE TG_OP WHEN 'DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER assessment_item_freeze BEFORE INSERT OR UPDATE OR DELETE ON assessment_items
  FOR EACH ROW EXECUTE FUNCTION check_assessment_frozen();

-- Publication is the moment the form becomes a promise: every question deliverable, every
-- question from the required pool, and the total marks fixed from the placements.
CREATE FUNCTION check_assessment_publication() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  placed integer;
  wrong_pool integer;
  undeliverable integer;
  placed_marks numeric(8,2);
BEGIN
  IF NEW.status = 'published' AND (TG_OP = 'INSERT' OR OLD.status = 'draft') THEN
    SELECT count(*), coalesce(sum(i.marks), 0) INTO placed, placed_marks
      FROM assessment_items i WHERE i.assessment_id = NEW.id;
    IF placed = 0 THEN
      RAISE EXCEPTION 'an assessment cannot be published with no questions';
    END IF;

    SELECT count(*) INTO wrong_pool
      FROM assessment_items i
      JOIN question_versions v ON v.id = i.question_version_id
      JOIN questions q ON q.id = v.question_id
     WHERE i.assessment_id = NEW.id AND q.usage_pool <> NEW.required_pool;
    IF wrong_pool > 0 THEN
      RAISE EXCEPTION '% question(s) are not from the % pool this assessment requires',
        wrong_pool, NEW.required_pool;
    END IF;

    SELECT count(*) INTO undeliverable
      FROM assessment_items i
      WHERE i.assessment_id = NEW.id
        AND NOT EXISTS (
          SELECT 1 FROM deliverable_questions d
          WHERE d.question_version_id = i.question_version_id
        );
    IF undeliverable > 0 THEN
      RAISE EXCEPTION '% question(s) are not approved for delivery', undeliverable;
    END IF;

    IF NEW.total_marks IS DISTINCT FROM placed_marks THEN
      RAISE EXCEPTION 'total_marks (%) does not match the % marks placed', NEW.total_marks, placed_marks;
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER assessment_publication_guard BEFORE INSERT OR UPDATE ON assessments
  FOR EACH ROW EXECUTE FUNCTION check_assessment_publication();

-- An exam response has to belong to a sitting that is still open.
CREATE FUNCTION check_exam_response() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE sitting record;
BEGIN
  IF NEW.sitting_id IS NULL THEN
    RETURN NEW;
  END IF;
  SELECT * INTO sitting FROM assessment_sittings WHERE id = NEW.sitting_id;
  IF sitting.student_id <> NEW.student_id THEN
    RAISE EXCEPTION 'this sitting belongs to another student';
  END IF;
  IF sitting.status <> 'in_progress' THEN
    RAISE EXCEPTION 'this sitting is already %; no further answers can be recorded', sitting.status;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER exam_response_guard BEFORE INSERT ON attempts
  FOR EACH ROW EXECUTE FUNCTION check_exam_response();

-- ---------------------------------------------------------------------------
-- Views
-- ---------------------------------------------------------------------------

-- The candidate's final answer to each placement. A student may change an answer before
-- submitting, and each change is its own attempt, so the last one before the deadline is
-- the one that counts — and the earlier ones remain as evidence of changing their mind.
CREATE VIEW sitting_final_answers AS
SELECT DISTINCT ON (a.sitting_id, a.assessment_item_id)
       a.sitting_id,
       a.assessment_item_id,
       a.id                AS attempt_id,
       a.question_version_id,
       a.selected_option_key,
       a.is_correct,
       a.response_ms,
       a.answered_at_client,
       a.received_at,
       s.deadline_at,
       a.received_at > s.deadline_at + interval '60 seconds' AS after_deadline,
       count(*) OVER (PARTITION BY a.sitting_id, a.assessment_item_id) AS answer_count
FROM attempts a
JOIN assessment_sittings s ON s.id = a.sitting_id
ORDER BY a.sitting_id, a.assessment_item_id, a.answered_at_client DESC, a.received_at DESC;

-- One row per sitting: what was placed, what was answered, and what it scores. Unanswered
-- questions are counted as unanswered, never as wrong.
CREATE VIEW sitting_results AS
SELECT s.id                                   AS sitting_id,
       s.assessment_id,
       s.student_id,
       s.status,
       s.started_at,
       s.submitted_at,
       s.auto_submitted,
       count(i.id)                            AS questions_placed,
       count(f.attempt_id)                    AS questions_answered,
       count(i.id) - count(f.attempt_id)      AS questions_unanswered,
       count(*) FILTER (WHERE f.is_correct)   AS questions_correct,
       count(*) FILTER (WHERE f.answer_count > 1) AS answers_changed,
       coalesce(sum(i.marks) FILTER (WHERE f.is_correct), 0) AS raw_score,
       sum(i.marks)                           AS max_score,
       round(
         100 * coalesce(sum(i.marks) FILTER (WHERE f.is_correct), 0) / nullif(sum(i.marks), 0),
         2
       )                                      AS percentage
FROM assessment_sittings s
JOIN assessment_items i ON i.assessment_id = s.assessment_id
LEFT JOIN sitting_final_answers f
  ON f.sitting_id = s.id AND f.assessment_item_id = i.id AND NOT f.after_deadline
GROUP BY s.id, s.assessment_id, s.student_id, s.status, s.started_at, s.submitted_at,
         s.auto_submitted;

COMMIT;
