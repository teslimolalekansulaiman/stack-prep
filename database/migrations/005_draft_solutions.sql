-- Let a draft exist without a worked solution; require one before approval.
--
-- A past paper arrives as a stem, four options and (at best) a key. The worked solution is
-- written later by a subject expert. Demanding it at insert would force the importer to
-- invent one, which is exactly the kind of placeholder that later reads as real content.
BEGIN;
SET LOCAL search_path = stackprep, public;

ALTER TABLE question_versions
  ALTER COLUMN solution_steps SET DEFAULT '[]'::jsonb;

ALTER TABLE question_versions
  DROP CONSTRAINT question_versions_solution_steps_check;

ALTER TABLE question_versions
  ADD CONSTRAINT question_versions_solution_steps_check
    CHECK (jsonb_typeof(solution_steps) = 'array');

COMMENT ON COLUMN question_versions.solution_steps IS
  'Ordered worked solution. May be empty while the question is a draft; the approval '
  'trigger requires at least one step.';

-- The approval gate now checks the solution too, alongside hints and the option rules.
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
    IF jsonb_array_length(NEW.solution_steps) = 0 THEN
      RAISE EXCEPTION 'an approved question needs a worked solution';
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

-- What each imported question still needs before it can reach a student.
CREATE VIEW question_readiness AS
SELECT q.id   AS question_id,
       v.id   AS question_version_id,
       q.subject_id,
       q.exam_year,
       q.paper_code,
       q.question_number,
       v.review_status,
       v.answer_source,
       v.answer_confidence,
       jsonb_array_length(v.solution_steps) > 0                      AS has_solution,
       jsonb_array_length(v.hints) > 0                               AS has_hint,
       v.expected_seconds IS NOT NULL                                AS has_expected_time,
       v.mastery_level_number IS NOT NULL                            AS has_level,
       v.answer_source IN ('expert_verified', 'official_key')        AS answer_checked,
       EXISTS (
         SELECT 1 FROM question_classifications c
         WHERE c.question_id = q.id AND c.classification_role = 'primary'
           AND c.review_status = 'approved'
       )                                                             AS has_approved_skill
FROM question_versions v
JOIN questions q ON q.id = v.question_id
WHERE v.review_status <> 'withdrawn';

COMMIT;
