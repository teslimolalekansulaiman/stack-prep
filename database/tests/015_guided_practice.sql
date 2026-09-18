-- Run after 015_guided_practice.sql in a disposable PostgreSQL database.
-- Local variables are prefixed v_ so they never collide with column names.
BEGIN;
SET LOCAL search_path = stackprep, public;

DO $$
DECLARE
  v_author uuid;
  v_exam uuid;
  v_subject uuid;
  v_student uuid;
  v_question uuid;
  v_version uuid;
  v_rejected boolean;
  v_counted integer;
  v_session uuid;
BEGIN
  INSERT INTO academic_reviewers(display_name) VALUES ('Guided author') RETURNING id INTO v_author;
  INSERT INTO examinations(name, short_name, exam_body, country_code, status)
    VALUES ('Guided exam', 'TESTGP', 'Test body', 'NG', 'active') RETURNING id INTO v_exam;
  INSERT INTO subjects(examination_id, code, name, status)
    VALUES (v_exam, 'GPR', 'Guided subject', 'active') RETURNING id INTO v_subject;
  INSERT INTO students(display_name, external_ref, status, requires_guardian_consent)
    VALUES ('Guided student', 'test:guided', 'active', false) RETURNING id INTO v_student;
  -- Every attempt belongs to exactly one of a study session or an exam sitting, so the
  -- guided loop needs a session before it can record anything.
  INSERT INTO study_sessions(student_id, subject_id, session_type, engine_version)
    VALUES (v_student, v_subject, 'guided', 'test') RETURNING id INTO v_session;
  INSERT INTO questions(subject_id, origin, usage_pool, created_by)
    VALUES (v_subject, 'authored', 'practice', v_author) RETURNING id INTO v_question;
  INSERT INTO question_versions(question_id, subject_id, version, stem, response_format,
    marking_method, marks, expected_seconds, option_count, content_hash, authored_by)
    VALUES (v_question, v_subject, 1, 'A guided question.', 'mcq_single', 'auto_key', 1, 45, 4,
      repeat('d', 64), v_author)
    RETURNING id INTO v_version;

  -- An invented confidence is refused; the three the product asks for are accepted.
  v_rejected := false;
  BEGIN
    INSERT INTO attempts(id, student_id, question_version_id, session_id, context, selected_option_key,
      is_correct, answered_at_client, confidence)
      VALUES (gen_random_uuid(), v_student, v_version, v_session, 'guided', 'A', true, now(), 'quite sure');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an unknown confidence was accepted'; END IF;

  -- Unaided and sure: this is evidence.
  INSERT INTO attempts(id, student_id, question_version_id, session_id, context, selected_option_key,
    is_correct, answered_at_client, confidence)
    VALUES (gen_random_uuid(), v_student, v_version, v_session, 'guided', 'A', true, now(), 'sure');
  -- Right, but the student says they guessed: not evidence of anything.
  INSERT INTO attempts(id, student_id, question_version_id, session_id, context, selected_option_key,
    is_correct, answered_at_client, confidence)
    VALUES (gen_random_uuid(), v_student, v_version, v_session, 'guided', 'A', true, now(), 'guessed');
  -- Right after a hint: not unaided.
  INSERT INTO attempts(id, student_id, question_version_id, session_id, context, selected_option_key,
    is_correct, answered_at_client, hint_count, confidence)
    VALUES (gen_random_uuid(), v_student, v_version, v_session, 'guided', 'A', true, now(), 1, 'sure');
  -- Right after being shown the answer: not evidence either.
  INSERT INTO attempts(id, student_id, question_version_id, session_id, context, selected_option_key,
    is_correct, answered_at_client, solution_viewed_before_answer, confidence)
    VALUES (gen_random_uuid(), v_student, v_version, v_session, 'guided', 'A', true, now(), true, 'sure');
  -- Wrong, and the student guessed. A wrong answer counts however it was arrived at:
  -- not knowing is not something a student can be lucky about.
  INSERT INTO attempts(id, student_id, question_version_id, session_id, context, selected_option_key,
    is_correct, answered_at_client, confidence)
    VALUES (gen_random_uuid(), v_student, v_version, v_session, 'guided', 'B', false, now(), 'guessed');

  SELECT count(*) INTO v_counted FROM scoring_attempts WHERE student_id = v_student;
  IF v_counted <> 2 THEN
    RAISE EXCEPTION 'scoring_attempts kept % of the five attempts, expected the unaided sure '
      'one and the wrong guess', v_counted;
  END IF;

  -- Working is an object, so the capture method can travel with the content.
  v_rejected := false;
  BEGIN
    INSERT INTO attempts(id, student_id, question_version_id, session_id, context, selected_option_key,
      is_correct, answered_at_client, working)
      VALUES (gen_random_uuid(), v_student, v_version, v_session, 'guided', 'A', true, now(),
        '["4x = 20"]'::jsonb);
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'working accepted a bare array'; END IF;

  INSERT INTO attempts(id, student_id, question_version_id, session_id, context, selected_option_key,
    is_correct, answered_at_client, working)
    VALUES (gen_random_uuid(), v_student, v_version, v_session, 'guided', 'A', true, now(),
      '{"captured_as": "typed", "steps": ["4x - 6 = 14", "4x = 20", "x = 5"]}'::jsonb);
END $$;

ROLLBACK;
