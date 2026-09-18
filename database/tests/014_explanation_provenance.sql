-- Run after 014_explanation_provenance.sql in a disposable PostgreSQL database.
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
BEGIN
  INSERT INTO academic_reviewers(display_name) VALUES ('Explanation author')
    RETURNING id INTO v_author;
  INSERT INTO academic_reviewers(display_name) VALUES ('Explanation reviewer')
    RETURNING id INTO v_reviewer;
  INSERT INTO examinations(name, short_name, exam_body, country_code, status)
    VALUES ('Explanation exam', 'TESTEX', 'Test body', 'NG', 'active') RETURNING id INTO v_exam;
  INSERT INTO subjects(examination_id, code, name, status)
    VALUES (v_exam, 'ENG', 'Use of English', 'active') RETURNING id INTO v_subject;
  INSERT INTO questions(subject_id, origin, usage_pool, created_by)
    VALUES (v_subject, 'authored', 'practice', v_author) RETURNING id INTO v_question;

  INSERT INTO question_versions(question_id, subject_id, version, stem, response_format,
    marking_method, solution_steps, hints, marks, expected_seconds, option_count,
    content_hash, authored_by, answer_source, mastery_level_number, level_source,
    solution_source)
    VALUES (v_question, v_subject, 1, 'A question with a generated explanation.', 'mcq_single',
      'auto_key', '["the key gives B"]'::jsonb, '["read the whole sentence"]'::jsonb,
      1, 45, 4, repeat('c', 64), v_author, 'expert_verified', 3, 'expert_verified',
      'model_proposed')
    RETURNING id INTO v_version;
  INSERT INTO question_options(question_version_id, subject_id, option_key, body,
    is_correct, display_order)
    VALUES (v_version, v_subject, 'A', 'first option', true, 1);
  INSERT INTO question_options(question_version_id, subject_id, option_key, body, display_order)
    VALUES (v_version, v_subject, 'B', 'second option', 2);
  INSERT INTO question_options(question_version_id, subject_id, option_key, body, display_order)
    VALUES (v_version, v_subject, 'C', 'third option', 3);
  INSERT INTO question_options(question_version_id, subject_id, option_key, body, display_order)
    VALUES (v_version, v_subject, 'D', 'fourth option', 4);
  UPDATE questions SET current_version_id = v_version WHERE id = v_question;

  -- It shows up as work to do.
  IF NOT EXISTS (SELECT 1 FROM questions_awaiting_explanation_check
                  WHERE question_version_id = v_version) THEN
    RAISE EXCEPTION 'a model-proposed explanation is missing from the rewrite queue';
  END IF;

  -- And, unlike the answer, it does not stand in the way of approval: a correct question
  -- with a thin explanation is still a question worth asking.
  UPDATE question_versions SET review_status = 'approved', reviewed_by = v_reviewer,
    reviewed_at = now() WHERE id = v_version;
  IF (SELECT review_status FROM question_versions WHERE id = v_version) <> 'approved' THEN
    RAISE EXCEPTION 'a model-proposed explanation blocked approval, which it should not';
  END IF;

  -- Once it is approved it is in front of students, which makes it more urgent, not less.
  IF NOT EXISTS (SELECT 1 FROM questions_awaiting_explanation_check
                  WHERE question_version_id = v_version AND live) THEN
    RAISE EXCEPTION 'an approved question with a thin explanation dropped out of the queue';
  END IF;

  -- Once a person has written them it leaves the queue.
  UPDATE question_versions SET solution_source = 'expert_verified' WHERE id = v_version;
  IF EXISTS (SELECT 1 FROM questions_awaiting_explanation_check
              WHERE question_version_id = v_version) THEN
    RAISE EXCEPTION 'a checked explanation is still sitting in the rewrite queue';
  END IF;

  -- An invented source is refused.
  v_rejected := false;
  BEGIN
    UPDATE question_versions SET solution_source = 'written_by_a_friend' WHERE id = v_version;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an unknown solution_source was accepted'; END IF;
END $$;

ROLLBACK;
