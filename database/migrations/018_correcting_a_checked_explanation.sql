-- Let a checked explanation be corrected without pretending its provenance changed.
--
-- 017 made an approved question's explanation improvable, on one condition: a rewrite must
-- also change solution_source, so that replacing a generated explanation with a written one
-- says so. That is right for the case it was built for and wrong for the next one. Once an
-- explanation is 'expert_verified', a person correcting their own wording has nothing to
-- change it to — the provenance is already what it should be — and the rule forces either a
-- meaningless flip to another value and back, or leaving the correction unmade.
--
-- So the condition now applies only when the old source was NOT already expert_verified. The
-- audit does not rest on it either way: question_explanation_history keeps the replaced text
-- whatever the source says, and that is what lets a change be read against what it replaced.
BEGIN;
SET LOCAL search_path = stackprep, public;

CREATE OR REPLACE FUNCTION keep_replaced_explanation() RETURNS trigger AS $$
BEGIN
  IF OLD.review_status = 'approved'
     AND (NEW.solution_steps IS DISTINCT FROM OLD.solution_steps
          OR NEW.hints IS DISTINCT FROM OLD.hints) THEN
    -- Replacing something nobody had read has to say who read it now. Correcting something
    -- already checked does not: the provenance is unchanged and still true.
    IF OLD.solution_source <> 'expert_verified'
       AND NEW.solution_source IS NOT DISTINCT FROM OLD.solution_source THEN
      RAISE EXCEPTION
        'rewriting an unchecked explanation must also say where the new one came from: '
        'change solution_source as well';
    END IF;
    INSERT INTO question_explanation_history(question_version_id, solution_steps, hints,
      solution_source)
      VALUES (OLD.id, OLD.solution_steps, OLD.hints, OLD.solution_source);
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

COMMIT;
