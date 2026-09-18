-- Let an approved question's explanation be rewritten without re-versioning the question.
--
-- 014 created a queue of work — questions_awaiting_explanation_check, every question whose
-- worked solution and hints nobody has read — and the immutability trigger from 001 then
-- forbids doing it: solution_steps and hints are in the frozen set, so improving the prose of
-- an approved question means a new version of the question. Two migrations that disagree, and
-- the disagreement only shows up when someone tries to do the work.
--
-- The rule is relaxed here rather than the queue abandoned, because a question's identity is
-- its stem, its options and its key. Those stay frozen, along with its level, its timing and
-- where its answer came from. What changes is the explanation shown AFTER the student has
-- answered — it cannot alter what they were asked or how they were marked, and its statistics
-- should not be reset by a better sentence.
--
-- Two conditions come with it. Rewriting the explanation must also say where the new one came
-- from, so solution_source has to change with it: a rewrite that leaves the provenance alone
-- is refused. And the old text is kept, so a rewrite can be read against what it replaced.
BEGIN;
SET LOCAL search_path = stackprep, public;

CREATE TABLE question_explanation_history (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  question_version_id uuid NOT NULL REFERENCES question_versions(id) ON DELETE RESTRICT,
  solution_steps jsonb NOT NULL,
  hints jsonb NOT NULL,
  solution_source text NOT NULL,
  replaced_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX question_explanation_history_version_idx
  ON question_explanation_history(question_version_id, replaced_at DESC);

COMMENT ON TABLE question_explanation_history IS
  'What an approved question''s explanation said before it was rewritten. Kept so a rewrite '
  'can be read against what it replaced, and so a change nobody likes can be undone.';

CREATE OR REPLACE FUNCTION keep_replaced_explanation() RETURNS trigger AS $$
BEGIN
  IF OLD.review_status = 'approved'
     AND (NEW.solution_steps IS DISTINCT FROM OLD.solution_steps
          OR NEW.hints IS DISTINCT FROM OLD.hints) THEN
    IF NEW.solution_source IS NOT DISTINCT FROM OLD.solution_source THEN
      RAISE EXCEPTION
        'rewriting an approved explanation must also say where the new one came from: '
        'change solution_source as well';
    END IF;
    INSERT INTO question_explanation_history(question_version_id, solution_steps, hints,
      solution_source)
      VALUES (OLD.id, OLD.solution_steps, OLD.hints, OLD.solution_source);
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

-- Runs before the guard, so the old text is filed whether or not the guard then objects to
-- something else in the same statement.
CREATE TRIGGER question_version_explanation_history
  BEFORE UPDATE ON question_versions
  FOR EACH ROW EXECUTE FUNCTION keep_replaced_explanation();

CREATE OR REPLACE FUNCTION check_question_version() RETURNS trigger AS $$
DECLARE option_total integer; correct_total integer; p record;
BEGIN
  IF TG_OP = 'UPDATE' AND OLD.review_status = 'approved' THEN
    -- solution_steps and hints are deliberately absent from this list: an explanation is
    -- shown after the answer and cannot change what was asked or how it was marked, so it
    -- may be improved in place. Everything that defines the question stays frozen.
    IF ROW(NEW.question_id, NEW.subject_id, NEW.version, NEW.passage_id, NEW.stem,
           NEW.instructions, NEW.response_format, NEW.marking_method, NEW.numeric_answer,
           NEW.numeric_tolerance, NEW.numeric_unit, NEW.accepted_answers,
           NEW.marking_scheme, NEW.marks,
           NEW.expected_seconds, NEW.mastery_level_number, NEW.option_count,
           NEW.content_hash, NEW.answer_source, NEW.level_source)
       IS DISTINCT FROM
       ROW(OLD.question_id, OLD.subject_id, OLD.version, OLD.passage_id, OLD.stem,
           OLD.instructions, OLD.response_format, OLD.marking_method, OLD.numeric_answer,
           OLD.numeric_tolerance, OLD.numeric_unit, OLD.accepted_answers,
           OLD.marking_scheme, OLD.marks,
           OLD.expected_seconds, OLD.mastery_level_number, OLD.option_count,
           OLD.content_hash, OLD.answer_source, OLD.level_source) THEN
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
        RAISE EXCEPTION 'an approved objective question needs at least four options, found %',
          option_total;
      END IF;
      IF correct_total <> 1 THEN
        RAISE EXCEPTION 'an approved objective question needs exactly one correct option';
      END IF;
      IF NEW.option_count IS DISTINCT FROM option_total THEN
        RAISE EXCEPTION 'option_count (%) does not match the % options stored',
          NEW.option_count, option_total;
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
END $$ LANGUAGE plpgsql;

COMMIT;
