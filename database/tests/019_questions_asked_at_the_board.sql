-- Run after 019_questions_asked_at_the_board.sql in a disposable PostgreSQL database.
-- Local variables are prefixed v_ so they never collide with column names.
BEGIN;
SET LOCAL search_path = stackprep, public;

DO $$
DECLARE
  v_author uuid;
  v_exam uuid;
  v_subject uuid;
  v_student uuid;
  v_minor uuid;
  v_question uuid;
  v_version uuid;
  v_session uuid;
  v_minor_session uuid;
  v_turn uuid;
  v_rejected boolean;
BEGIN
  INSERT INTO academic_reviewers(display_name) VALUES ('Board author') RETURNING id INTO v_author;
  INSERT INTO examinations(name, short_name, exam_body, country_code, status)
    VALUES ('Board exam', 'TESTBD', 'Test body', 'NG', 'active') RETURNING id INTO v_exam;
  INSERT INTO subjects(examination_id, code, name, status)
    VALUES (v_exam, 'BRD', 'Board subject', 'active') RETURNING id INTO v_subject;
  INSERT INTO students(display_name, external_ref, status, requires_guardian_consent)
    VALUES ('Board student', 'test:board', 'active', false) RETURNING id INTO v_student;
  INSERT INTO study_sessions(student_id, subject_id, session_type, engine_version)
    VALUES (v_student, v_subject, 'guided', 'test') RETURNING id INTO v_session;
  INSERT INTO questions(subject_id, origin, usage_pool, created_by)
    VALUES (v_subject, 'authored', 'practice', v_author) RETURNING id INTO v_question;
  INSERT INTO question_versions(question_id, subject_id, version, stem, response_format,
    marking_method, marks, expected_seconds, option_count, content_hash, authored_by)
    VALUES (v_question, v_subject, 1, 'A question asked about.', 'mcq_single', 'auto_key', 1, 45,
      4, repeat('b', 64), v_author)
    RETURNING id INTO v_version;

  -- The ordinary turn: the tutor answered, and the row says which model did.
  INSERT INTO tutor_turns(student_id, session_id, question_version_id, step_index, asked, reply,
    source, model, input_tokens, output_tokens, latency_ms)
    VALUES (v_student, v_session, v_version, 1, 'why square both sides?',
      'Because the x is under the root, and squaring is what takes it out.', 'model',
      'claude-haiku-4-5-20251001', 900, 60, 1400)
    RETURNING id INTO v_turn;

  -- A turn that says a model answered must name it: a benchmark that cannot attribute its
  -- rows to a model is not a benchmark of anything.
  v_rejected := false;
  BEGIN
    INSERT INTO tutor_turns(student_id, session_id, question_version_id, asked, reply, source)
      VALUES (v_student, v_session, v_version, 'and this one?', 'Here is the step again.',
        'model');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a model turn was stored without naming the model'; END IF;

  -- The fallback and the spent budget are stored the same way and name no model, so the
  -- table can be read for how often the tutor actually answered.
  INSERT INTO tutor_turns(student_id, session_id, question_version_id, step_index, asked, reply,
    source)
    VALUES (v_student, v_session, v_version, 0, 'why?', 'Here is step 1 again.', 'fallback');
  INSERT INTO tutor_turns(student_id, session_id, question_version_id, asked, reply, source)
    VALUES (v_student, v_session, v_version, 'one more?', 'The working is still on the board.',
      'budget');

  -- An invented source is refused.
  v_rejected := false;
  BEGIN
    INSERT INTO tutor_turns(student_id, session_id, question_version_id, asked, reply, source)
      VALUES (v_student, v_session, v_version, 'why?', 'Because.', 'made_up');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an unknown source was accepted'; END IF;

  -- A question of blank space is not a question.
  v_rejected := false;
  BEGIN
    INSERT INTO tutor_turns(student_id, session_id, question_version_id, asked, reply, source)
      VALUES (v_student, v_session, v_version, '   ', 'Here is the step again.', 'fallback');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an empty question was stored'; END IF;

  -- What the student was told is not edited afterwards, and not quietly deleted either.
  v_rejected := false;
  BEGIN
    UPDATE tutor_turns SET reply = 'something else' WHERE id = v_turn;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%append-only%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a recorded turn was rewritten'; END IF;

  v_rejected := false;
  BEGIN
    DELETE FROM tutor_turns WHERE id = v_turn;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%append-only%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a recorded turn was deleted without asking'; END IF;

  -- Erasure on withdrawal of consent is the one exception, and it is asked for explicitly.
  SET LOCAL scorepilot.allow_erasure = 'on';
  DELETE FROM tutor_turns WHERE id = v_turn;
  SET LOCAL scorepilot.allow_erasure = 'off';

  -- A student's own words are held to the same consent rule as their answers: a student who
  -- needs guardian consent and has none cannot have their question stored.
  INSERT INTO students(display_name, external_ref, status, requires_guardian_consent)
    VALUES ('Board minor', 'test:board-minor', 'active', true) RETURNING id INTO v_minor;
  INSERT INTO study_sessions(student_id, subject_id, session_type, engine_version)
    VALUES (v_minor, v_subject, 'guided', 'test') RETURNING id INTO v_minor_session;
  v_rejected := false;
  BEGIN
    INSERT INTO tutor_turns(student_id, session_id, question_version_id, asked, reply, source)
      VALUES (v_minor, v_minor_session, v_version, 'why?', 'Here is the step again.', 'fallback');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%no recorded consent%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN
    RAISE EXCEPTION 'a question was stored for a student with no recorded consent';
  END IF;
END $$;

ROLLBACK;
