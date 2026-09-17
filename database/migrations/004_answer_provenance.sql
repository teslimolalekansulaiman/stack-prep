-- Where a question's answer came from.
--
-- Past papers arrive without their marking schemes, so the key is often proposed by a
-- model or read off a third-party site. That is fine for a draft, and unacceptable for a
-- student: a wrong key teaches the wrong thing and corrupts the mastery estimate that
-- everything else is built on.
--
-- This migration makes the origin explicit and refuses to approve a question whose answer
-- no person has verified.
BEGIN;
SET LOCAL search_path = stackprep, public;

ALTER TABLE question_versions
  ADD COLUMN answer_source text NOT NULL DEFAULT 'unverified'
    CHECK (answer_source IN ('unverified', 'model_proposed', 'expert_verified', 'official_key')),
  ADD COLUMN answer_confidence text
    CHECK (answer_confidence IS NULL OR answer_confidence IN ('low', 'medium', 'high')),
  ADD CONSTRAINT question_versions_answer_verified_before_approval
    CHECK (review_status <> 'approved' OR answer_source IN ('expert_verified', 'official_key'));

COMMENT ON COLUMN question_versions.answer_source IS
  'unverified: no key yet. model_proposed: proposed by a model, pending human check. '
  'expert_verified: a subject expert confirmed it. official_key: taken from an official '
  'marking scheme. Approval requires one of the last two.';

-- The frozen-content check has to cover the new columns too, so an approved question's
-- answer provenance cannot be rewritten afterwards.
CREATE OR REPLACE FUNCTION check_question_version() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  option_total integer;
  correct_total integer;
  p record;
BEGIN
  IF TG_OP = 'UPDATE' AND OLD.review_status = 'approved' THEN
    IF ROW(NEW.question_id, NEW.subject_id, NEW.version, NEW.passage_id, NEW.stem,
           NEW.instructions, NEW.response_format, NEW.marking_method, NEW.numeric_answer,
           NEW.numeric_tolerance, NEW.numeric_unit, NEW.accepted_answers,
           NEW.solution_steps, NEW.marking_scheme, NEW.hints, NEW.marks,
           NEW.expected_seconds, NEW.mastery_level_number, NEW.option_count,
           NEW.content_hash, NEW.answer_source)
       IS DISTINCT FROM
       ROW(OLD.question_id, OLD.subject_id, OLD.version, OLD.passage_id, OLD.stem,
           OLD.instructions, OLD.response_format, OLD.marking_method, OLD.numeric_answer,
           OLD.numeric_tolerance, OLD.numeric_unit, OLD.accepted_answers,
           OLD.solution_steps, OLD.marking_scheme, OLD.hints, OLD.marks,
           OLD.expected_seconds, OLD.mastery_level_number, OLD.option_count,
           OLD.content_hash, OLD.answer_source) THEN
      RAISE EXCEPTION 'approved question content is immutable; create a new version';
    END IF;
    IF NEW.review_status NOT IN ('approved', 'withdrawn') THEN
      RAISE EXCEPTION 'approved question cannot return to draft; withdraw it instead';
    END IF;
  END IF;

  IF NEW.review_status = 'approved' THEN
    IF NEW.authored_by IS NULL THEN
      RAISE EXCEPTION 'an approved question must record its author';
    END IF;
    IF NEW.expected_seconds IS NULL OR NEW.mastery_level_number IS NULL THEN
      RAISE EXCEPTION 'an approved question needs expected_seconds and a mastery level';
    END IF;
    IF jsonb_array_length(NEW.hints) = 0 THEN
      RAISE EXCEPTION 'an approved question needs at least one hint';
    END IF;

    IF NEW.response_format = 'mcq_single' THEN
      SELECT count(*), count(*) FILTER (WHERE is_correct)
        INTO option_total, correct_total
        FROM question_options WHERE question_version_id = NEW.id;
      IF option_total < 4 THEN
        RAISE EXCEPTION 'an approved objective question needs at least four options, found %', option_total;
      END IF;
      IF correct_total <> 1 THEN
        RAISE EXCEPTION 'an approved objective question needs exactly one correct option';
      END IF;
      IF NEW.option_count IS DISTINCT FROM option_total THEN
        RAISE EXCEPTION 'option_count (%) does not match the % options stored', NEW.option_count, option_total;
      END IF;
    END IF;

    IF EXISTS (
      SELECT 1 FROM question_assets a
      WHERE a.question_version_id = NEW.id
        AND (a.licence_status <> 'verified' OR btrim(coalesce(a.alt_text, '')) = '')
    ) THEN
      RAISE EXCEPTION 'every asset needs alt text and a verified licence before approval';
    END IF;

    IF NEW.passage_id IS NOT NULL THEN
      SELECT * INTO p FROM passages WHERE id = NEW.passage_id;
      IF p.review_status <> 'approved' OR p.licence_status <> 'verified' THEN
        RAISE EXCEPTION 'the passage must be approved with a verified licence first';
      END IF;
    END IF;
  END IF;

  RETURN NEW;
END $$;

-- Questions whose answer is still waiting on a person. This is the review queue.
CREATE VIEW questions_awaiting_answer_check AS
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
WHERE v.answer_source IN ('unverified', 'model_proposed')
  AND v.review_status <> 'withdrawn';

COMMIT;
