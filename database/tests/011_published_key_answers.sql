-- Run after 011_published_key_answers.sql in a disposable PostgreSQL database.
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
  INSERT INTO academic_reviewers(display_name) VALUES ('Key author') RETURNING id INTO v_author;
  INSERT INTO academic_reviewers(display_name) VALUES ('Key reviewer') RETURNING id INTO v_reviewer;
  INSERT INTO examinations(name, short_name, exam_body, country_code, status)
    VALUES ('Published key exam', 'TESTPK', 'Test body', 'NG', 'active') RETURNING id INTO v_exam;
  INSERT INTO subjects(examination_id, code, name, status)
    VALUES (v_exam, 'ENG', 'Use of English', 'active') RETURNING id INTO v_subject;
  INSERT INTO questions(subject_id, origin, usage_pool, created_by)
    VALUES (v_subject, 'authored', 'practice', v_author) RETURNING id INTO v_question;

  -- A published key is an accepted source for a draft.
  INSERT INTO question_versions(question_id, subject_id, version, stem, response_format,
    marking_method, solution_steps, hints, marks, expected_seconds, option_count,
    content_hash, authored_by, answer_source, answer_confidence, mastery_level_number,
    level_source)
    -- Everything else approval needs is already in place — worked solution, hints, timing,
    -- a verified level — so the only thing that can stop the approval below is where the
    -- answer came from.
    VALUES (v_question, v_subject, 1, 'A question with a published key.', 'mcq_single',
      'auto_key', '["the key prints B"]'::jsonb, '["read the whole sentence"]'::jsonb,
      1, 45, 4, repeat('e', 64), v_author, 'published_key', 'medium', 3, 'expert_verified')
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

  -- ...but it is not a substitute for a person. This is the whole point of the new value:
  -- it records where the answer came from without unlocking delivery to a student.
  v_rejected := false;
  BEGIN
    UPDATE question_versions SET review_status = 'approved', reviewed_by = v_reviewer,
      reviewed_at = now() WHERE id = v_version;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN
    RAISE EXCEPTION 'a question answered only by a published key was approved';
  END IF;

  -- It has to show up in the queue of things a human still has to check.
  IF NOT EXISTS (SELECT 1 FROM questions_awaiting_answer_check
                  WHERE question_version_id = v_version) THEN
    RAISE EXCEPTION 'a published-key answer is missing from the answer review queue';
  END IF;

  -- Once a person has checked the answer, the ordinary route to approval still works:
  -- the new source changes nothing about what approval demands.
  UPDATE question_versions SET answer_source = 'expert_verified' WHERE id = v_version;
  UPDATE question_versions SET review_status = 'approved', reviewed_by = v_reviewer,
    reviewed_at = now() WHERE id = v_version;
  IF (SELECT review_status FROM question_versions WHERE id = v_version) <> 'approved' THEN
    RAISE EXCEPTION 'an expert-verified answer could not be approved';
  END IF;
  IF EXISTS (SELECT 1 FROM questions_awaiting_answer_check
              WHERE question_version_id = v_version) THEN
    RAISE EXCEPTION 'a verified answer is still sitting in the review queue';
  END IF;

  -- An invented source is still refused.
  v_rejected := false;
  BEGIN
    INSERT INTO question_versions(question_id, subject_id, version, stem, response_format,
      marking_method, marks, expected_seconds, option_count, content_hash, authored_by,
      answer_source)
      VALUES (v_question, v_subject, 2, 'Another question.', 'mcq_single', 'auto_key', 1, 45,
        4, repeat('f', 64), v_author, 'toppers_dot_com');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an unknown answer_source was accepted'; END IF;
END $$;

ROLLBACK;
