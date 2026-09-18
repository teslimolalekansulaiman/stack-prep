-- Let an adaptive session grow while a fixed paper stays frozen.
--
-- 007 froze every assessment's questions at publication. That is right for a mock
-- or a fixed practice set, and wrong for adaptive delivery, where the next question
-- is chosen only after the last answer has been seen. The v1.1 data model document
-- flags the same gap: "adaptive delivery needs separately defined question-placement
-- policy."
--
-- The guarantee that actually matters is narrower than a freeze: work a student has
-- already done must not change underneath them. Appending a question they have not
-- seen does not breach that. Editing or removing one does, and stays forbidden.
BEGIN;
SET LOCAL search_path = stackprep, public;

CREATE OR REPLACE FUNCTION check_assessment_question() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  parent record;
  target uuid;
BEGIN
  target := CASE TG_OP WHEN 'DELETE' THEN OLD.assessment_id ELSE NEW.assessment_id END;
  SELECT * INTO parent FROM assessments WHERE id = target;

  IF parent.status <> 'draft' THEN
    -- An adaptive session may gain questions while it is open, and never anything
    -- else: a placement that exists has either been answered or is about to be.
    IF NOT (parent.delivery_mode = 'adaptive'
            AND parent.status = 'published'
            AND TG_OP = 'INSERT') THEN
      RAISE EXCEPTION 'the questions in a % % assessment are frozen',
        parent.status, parent.delivery_mode;
    END IF;
  END IF;

  IF TG_OP <> 'DELETE' THEN
    IF NOT EXISTS (
      SELECT 1 FROM question_versions v
      WHERE v.id = NEW.question_version_id AND v.subject_id = parent.subject_id
    ) THEN
      RAISE EXCEPTION 'that question belongs to a different subject than this assessment';
    END IF;

    -- Anything appended to a live session still has to be servable; the publish
    -- check cannot see a question that did not exist when it ran. A draft is
    -- exempt: holding not-yet-approved content is the normal state of one.
    IF parent.status = 'published' AND NOT EXISTS (
      SELECT 1 FROM deliverable_questions dq
      WHERE dq.question_version_id = NEW.question_version_id
    ) THEN
      RAISE EXCEPTION 'that question is not approved for delivery to a student';
    END IF;
  END IF;

  RETURN CASE TG_OP WHEN 'DELETE' THEN OLD ELSE NEW END;
END $$;

-- An adaptive set is one student's own session; it is not a paper several people
-- sit. Without this, one learner's next question would appear in another's.
ALTER TABLE assessments ADD CONSTRAINT assessments_adaptive_is_personal
  CHECK (delivery_mode <> 'adaptive' OR created_for_student_id IS NOT NULL);

-- Publishing an empty adaptive session is how one starts: its first question is
-- chosen after the student begins, not before.
CREATE OR REPLACE FUNCTION check_assessment_publish() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  placed integer;
  undeliverable integer;
BEGIN
  IF NEW.status = 'published' AND (TG_OP = 'INSERT' OR OLD.status <> 'published') THEN
    IF NEW.delivery_mode = 'fixed' THEN
      SELECT count(*) INTO placed FROM assessment_questions WHERE assessment_id = NEW.id;
      IF placed = 0 THEN
        RAISE EXCEPTION 'an assessment cannot be published with no questions in it';
      END IF;
    END IF;

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

COMMIT;
