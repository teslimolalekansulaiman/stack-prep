-- Run after 017_explanations_are_improvable.sql in a disposable PostgreSQL database.
-- Local variables are prefixed v_ so they never collide with column names.
BEGIN;
SET LOCAL search_path = stackprep, public;

DO $$
DECLARE
  v_author uuid;
  v_reviewer uuid;
  v_exam uuid;
  v_subject uuid;
  v_question uuid;
  v_version uuid;
  v_rejected boolean;
  v_kept integer;
BEGIN
  INSERT INTO academic_reviewers(display_name) VALUES ('Prose author') RETURNING id INTO v_author;
  INSERT INTO academic_reviewers(display_name) VALUES ('Prose reviewer')
    RETURNING id INTO v_reviewer;
  INSERT INTO examinations(name, short_name, exam_body, country_code, status)
    VALUES ('Prose exam', 'TESTPR', 'Test body', 'NG', 'active') RETURNING id INTO v_exam;
  INSERT INTO subjects(examination_id, code, name, status)
    VALUES (v_exam, 'ENG', 'Use of English', 'active') RETURNING id INTO v_subject;
  INSERT INTO questions(subject_id, origin, usage_pool, created_by)
    VALUES (v_subject, 'authored', 'practice', v_author) RETURNING id INTO v_question;
  INSERT INTO question_versions(question_id, subject_id, version, stem, response_format,
    marking_method, solution_steps, hints, marks, expected_seconds, option_count,
    content_hash, authored_by, answer_source, mastery_level_number, level_source,
    solution_source)
    VALUES (v_question, v_subject, 1, 'A question needing a better explanation.', 'mcq_single',
      'auto_key', '["thin"]'::jsonb, '["thin hint"]'::jsonb, 1, 45, 4, repeat('7', 64),
      v_author, 'expert_verified', 3, 'expert_verified', 'model_proposed')
    RETURNING id INTO v_version;
  INSERT INTO question_options(question_version_id, subject_id, option_key, body, is_correct,
    display_order) VALUES (v_version, v_subject, 'A', 'first', true, 1);
  INSERT INTO question_options(question_version_id, subject_id, option_key, body, display_order)
    VALUES (v_version, v_subject, 'B', 'second', 2);
  INSERT INTO question_options(question_version_id, subject_id, option_key, body, display_order)
    VALUES (v_version, v_subject, 'C', 'third', 3);
  INSERT INTO question_options(question_version_id, subject_id, option_key, body, display_order)
    VALUES (v_version, v_subject, 'D', 'fourth', 4);
  UPDATE questions SET current_version_id = v_version WHERE id = v_question;
  UPDATE question_versions SET review_status = 'approved', reviewed_by = v_reviewer,
    reviewed_at = now() WHERE id = v_version;

  -- The explanation may be improved on an approved question. This is the whole point: 014
  -- created a queue of explanations to rewrite and 001 forbade the rewriting.
  UPDATE question_versions
     SET solution_steps = '["Prosperous means wealthy, so its opposite is unsuccessful."]'::jsonb,
         hints = '["Decide what the word means here, then look for its opposite."]'::jsonb,
         solution_source = 'expert_verified'
   WHERE id = v_version;
  IF (SELECT solution_source FROM question_versions WHERE id = v_version) <> 'expert_verified'
  THEN
    RAISE EXCEPTION 'an approved explanation could not be improved';
  END IF;

  -- The replaced text is kept, so the rewrite can be read against what it replaced.
  SELECT count(*) INTO v_kept FROM question_explanation_history
   WHERE question_version_id = v_version;
  IF v_kept <> 1 THEN
    RAISE EXCEPTION 'the replaced explanation was not kept: % rows', v_kept;
  END IF;
  IF (SELECT solution_steps FROM question_explanation_history
       WHERE question_version_id = v_version) <> '["thin"]'::jsonb THEN
    RAISE EXCEPTION 'the kept explanation is not the one that was replaced';
  END IF;

  -- Once it is checked, the same person may correct their own wording without flipping the
  -- provenance to something else and back. The history row is still written, which is what
  -- the audit actually rests on (018).
  UPDATE question_versions SET solution_steps = '["Prosperous means wealthy."]'::jsonb
   WHERE id = v_version;
  SELECT count(*) INTO v_kept FROM question_explanation_history
   WHERE question_version_id = v_version;
  IF v_kept <> 2 THEN
    RAISE EXCEPTION 'correcting a checked explanation did not keep the replaced text: % rows',
      v_kept;
  END IF;

  -- But replacing an UNCHECKED explanation still has to say who checked it.
  UPDATE question_versions SET solution_steps = '["thin again"]'::jsonb,
    solution_source = 'model_proposed' WHERE id = v_version;
  v_rejected := false;
  BEGIN
    UPDATE question_versions SET solution_steps = '["changed again"]'::jsonb WHERE id = v_version;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%where the new one came from%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN
    RAISE EXCEPTION 'an unchecked explanation changed without its provenance changing';
  END IF;
  UPDATE question_versions SET solution_source = 'expert_verified' WHERE id = v_version;

  -- Everything that defines the question is still frozen.
  v_rejected := false;
  BEGIN
    UPDATE question_versions SET stem = 'A different question.' WHERE id = v_version;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%immutable%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'the stem of an approved question was changed'; END IF;

  v_rejected := false;
  BEGIN
    UPDATE question_versions SET mastery_level_number = 5 WHERE id = v_version;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%immutable%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'the level of an approved question was changed'; END IF;

  -- And an explanation still cannot be emptied.
  v_rejected := false;
  BEGIN
    UPDATE question_versions SET solution_steps = '[]'::jsonb, solution_source = 'unverified'
     WHERE id = v_version;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%needs a worked solution%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an approved question was left with no solution'; END IF;
END $$;

ROLLBACK;
