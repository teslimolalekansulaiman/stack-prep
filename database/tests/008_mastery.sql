-- Run after 008_mastery.sql in a disposable PostgreSQL database.
-- Local variables are prefixed v_ so they never collide with column names.
--
-- The claim under test: a student's mastery cannot change without a record of
-- why, because the number is derived from the history rather than written to.
BEGIN;
SET LOCAL search_path = stackprep, public;

DO $$
DECLARE
  v_reviewer uuid;
  v_exam uuid;
  v_subject uuid;
  v_doc uuid;
  v_syllabus_version uuid;
  v_topic uuid;
  v_subtopic uuid;
  v_skill uuid;
  v_student_user uuid;
  v_student uuid;
  v_mastery uuid;
  v_event uuid;
  v_theta double precision;
  v_band text;
  v_rejected boolean;
BEGIN
  INSERT INTO academic_reviewers(display_name) VALUES ('Mastery test reviewer')
    RETURNING id INTO v_reviewer;
  INSERT INTO examinations(name, short_name, exam_body, country_code, status)
    VALUES ('Mastery test exam', 'TESTM', 'Test body', 'NG', 'active')
    RETURNING id INTO v_exam;
  INSERT INTO subjects(examination_id, code, name, status)
    VALUES (v_exam, 'ENG', 'English Language', 'active') RETURNING id INTO v_subject;
  INSERT INTO source_documents(examination_id, subject_id, document_type, title,
    file_uri, file_sha256, mime_type, licence_status, storage_permission,
    student_delivery_permission, review_status, reviewed_by, reviewed_at)
    VALUES (v_exam, v_subject, 'syllabus', 'Mastery test syllabus', 'test://mastery',
      repeat('9', 64), 'application/pdf', 'verified', true, true, 'approved', v_reviewer, now())
    RETURNING id INTO v_doc;
  INSERT INTO syllabus_versions(subject_id, version_label, source_document_id, status,
    is_current, approved_by, approved_at)
    VALUES (v_subject, 'mastery-v1', v_doc, 'approved', true, v_reviewer, now())
    RETURNING id INTO v_syllabus_version;
  INSERT INTO curriculum_items(syllabus_version_id, subject_id, item_type, code, name,
    syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, 'topic', 'LEX', 'Lexis', 'explicit', 'supported')
    RETURNING id INTO v_topic;
  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type,
    code, name, syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, v_topic, 'subtopic', 'LEX.V', 'Vocabulary',
      'explicit', 'supported') RETURNING id INTO v_subtopic;
  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type,
    code, name, syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, v_subtopic, 'skill', 'LEX.V.1',
      'Choose the word that completes a sentence', 'explicit', 'supported')
    RETURNING id INTO v_skill;

  INSERT INTO users(first_name, last_name, email, role, status)
    VALUES ('Ada', 'Obi', 'ada.mastery@example.test', 'student', 'active')
    RETURNING id INTO v_student_user;
  INSERT INTO student_profiles(user_id) VALUES (v_student_user) RETURNING id INTO v_student;

  -- A mastery row cannot simply be asserted into existence.
  v_rejected := false;
  BEGIN
    INSERT INTO student_skill_mastery(student_id, curriculum_item_id, theta,
      scored_attempts, band, confidence, engine_version)
      VALUES (v_student, v_skill, 1.4, 9, 'strong', 'high', '0.2.0');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%derived%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'mastery was written without any evidence'; END IF;

  -- A first event cannot claim to follow a state that never existed.
  v_rejected := false;
  BEGIN
    INSERT INTO mastery_events(student_id, curriculum_item_id, previous_band,
      previous_theta, new_band, new_theta, scored_attempts, levels_seen, confidence,
      decision_reason, engine_version)
      VALUES (v_student, v_skill, 'weak', -0.4, 'developing', 0.1, 4,
        ARRAY[3]::smallint[], 'medium', 'Invented history.', '0.2.0');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%previous state%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an event invented a previous state'; END IF;

  -- The first real event brings the row into existence.
  INSERT INTO mastery_events(student_id, curriculum_item_id, new_band, new_theta,
    scored_attempts, levels_seen, mastery_score, confidence, decision_reason,
    engine_version)
    VALUES (v_student, v_skill, 'not_assessed', 0.16, 1, ARRAY[3]::smallint[],
      0.5399, 'low', 'First answer on this skill.', '0.2.0')
    RETURNING id, mastery_id INTO v_event, v_mastery;

  IF v_mastery IS NULL THEN
    RAISE EXCEPTION 'the event did not link itself to a mastery row';
  END IF;
  SELECT theta, band INTO v_theta, v_band FROM student_skill_mastery WHERE id = v_mastery;
  IF v_theta <> 0.16 OR v_band <> 'not_assessed' THEN
    RAISE EXCEPTION 'the derived row does not match the event that created it';
  END IF;

  -- An event that does not follow the current state is refused, because the
  -- history would stop reconstructing the present value.
  v_rejected := false;
  BEGIN
    INSERT INTO mastery_events(student_id, curriculum_item_id, previous_band,
      previous_theta, new_band, new_theta, scored_attempts, levels_seen, confidence,
      decision_reason, engine_version)
      VALUES (v_student, v_skill, 'not_assessed', 9.99, 'weak', 0.3, 2,
        ARRAY[3]::smallint[], 'low', 'Wrong starting point.', '0.2.0');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%does not follow%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an event skipped the current state'; END IF;

  -- One that does follow it moves the student on.
  INSERT INTO mastery_events(student_id, curriculum_item_id, previous_band,
    previous_theta, new_band, new_theta, scored_attempts, levels_seen, mastery_score,
    confidence, decision_reason, engine_version)
    VALUES (v_student, v_skill, 'not_assessed', 0.16, 'developing', 0.62, 3,
      ARRAY[2, 3]::smallint[], 0.6502, 'medium',
      'Two further correct answers at level 3.', '0.2.0');

  SELECT theta, band INTO v_theta, v_band FROM student_skill_mastery WHERE id = v_mastery;
  IF v_band <> 'developing' THEN
    RAISE EXCEPTION 'the derived row did not follow its second event';
  END IF;
  IF (SELECT count(*) FROM mastery_events WHERE mastery_id = v_mastery) <> 2 THEN
    RAISE EXCEPTION 'expected two events in this skill history';
  END IF;

  -- History cannot be rewritten.
  v_rejected := false;
  BEGIN
    UPDATE mastery_events SET decision_reason = 'Something else' WHERE id = v_event;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%append-only%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a past transition was edited'; END IF;

  v_rejected := false;
  BEGIN
    DELETE FROM mastery_events WHERE id = v_event;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%append-only%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a past transition was deleted'; END IF;

  -- Nor can the current value be nudged behind the history's back.
  v_rejected := false;
  BEGIN
    UPDATE student_skill_mastery SET band = 'maintained', theta = 3
      WHERE id = v_mastery;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%derived%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'mastery was edited without an event'; END IF;

  -- A band nobody has evidence for is refused. The previous state is correct
  -- here on purpose: BEFORE triggers run ahead of CHECK constraints, so the
  -- sequencing guard would otherwise mask the constraint under test.
  v_rejected := false;
  BEGIN
    INSERT INTO mastery_events(student_id, curriculum_item_id, previous_band,
      previous_theta, new_band, new_theta, scored_attempts, confidence,
      decision_reason, engine_version)
      VALUES (v_student, v_skill, 'developing', 0.62, 'strong', 2.0, 0, 'high',
        'No evidence.', '0.2.0');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a band was claimed with no attempts'; END IF;

  -- Levels outside the engine's 1..5 are refused.
  v_rejected := false;
  BEGIN
    INSERT INTO mastery_events(student_id, curriculum_item_id, previous_band,
      previous_theta, new_band, new_theta, scored_attempts, levels_seen, confidence,
      decision_reason, engine_version)
      VALUES (v_student, v_skill, 'developing', 0.62, 'developing', 0.63, 4,
        ARRAY[3, 7]::smallint[], 'medium', 'Impossible level.', '0.2.0');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a level outside 1..5 was accepted'; END IF;

  -- Mastery is only ever claimed against an assessable skill, never a topic.
  v_rejected := false;
  BEGIN
    INSERT INTO mastery_events(student_id, curriculum_item_id, new_band, new_theta,
      scored_attempts, confidence, decision_reason, engine_version)
      VALUES (v_student, v_topic, 'not_assessed', 0.0, 1, 'low',
        'Topics are not assessable.', '0.2.0');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%foreign key%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'mastery was recorded against a topic'; END IF;
END $$;

ROLLBACK;
