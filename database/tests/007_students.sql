-- Run after 007_students.sql in a disposable PostgreSQL database.
-- Local variables are prefixed v_ so they never collide with column names.
BEGIN;
SET LOCAL search_path = stackprep, public;

DO $$
DECLARE
  v_author uuid;
  v_reviewer uuid;
  v_exam uuid;
  v_subject uuid;
  v_doc uuid;
  v_syllabus_version uuid;
  v_topic uuid;
  v_subtopic uuid;
  v_skill uuid;
  v_question uuid;
  v_qversion uuid;
  v_minor uuid;
  v_adult uuid;
  v_guardian uuid;
  v_link uuid;
  v_session uuid;
  v_attempt uuid := gen_random_uuid();
  v_rejected boolean;
BEGIN
  -- ---------------------------------------------------------------- fixtures
  INSERT INTO academic_reviewers(display_name) VALUES ('Student test author') RETURNING id INTO v_author;
  INSERT INTO academic_reviewers(display_name) VALUES ('Student test reviewer') RETURNING id INTO v_reviewer;
  INSERT INTO examinations(name, short_name, exam_body, country_code, status)
    VALUES ('Student test exam', 'TESTS', 'Test body', 'NG', 'active') RETURNING id INTO v_exam;
  INSERT INTO subjects(examination_id, code, name, status)
    VALUES (v_exam, 'ENG', 'English Language', 'active') RETURNING id INTO v_subject;
  INSERT INTO source_documents(examination_id, subject_id, document_type, title, file_uri,
    file_sha256, mime_type, licence_status, storage_permission, student_delivery_permission,
    review_status, reviewed_by, reviewed_at)
    VALUES (v_exam, v_subject, 'syllabus', 'Student test syllabus', 'test://students',
      repeat('e', 64), 'application/pdf', 'verified', true, true, 'approved', v_reviewer, now())
    RETURNING id INTO v_doc;
  INSERT INTO syllabus_versions(subject_id, version_label, source_document_id, status,
    is_current, approved_by, approved_at)
    VALUES (v_subject, 'students-v1', v_doc, 'approved', true, v_reviewer, now())
    RETURNING id INTO v_syllabus_version;
  INSERT INTO curriculum_items(syllabus_version_id, subject_id, item_type, code, name,
    syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, 'topic', 'LEX', 'Lexis', 'explicit', 'supported')
    RETURNING id INTO v_topic;
  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type, code,
    name, syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, v_topic, 'subtopic', 'LEX.V', 'Vocabulary',
      'explicit', 'supported') RETURNING id INTO v_subtopic;
  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type, code,
    name, syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, v_subtopic, 'skill', 'LEX.V.1',
      'Choose the word that completes a sentence', 'explicit', 'supported')
    RETURNING id INTO v_skill;

  INSERT INTO questions(subject_id, origin, usage_pool, created_by)
    VALUES (v_subject, 'authored', 'practice', v_author) RETURNING id INTO v_question;
  INSERT INTO question_versions(question_id, subject_id, version, stem, response_format,
    marking_method, marks, expected_seconds, mastery_level_number, option_count,
    content_hash, authored_by)
    VALUES (v_question, v_subject, 1, 'The car crashed into a ______ vehicle.', 'mcq_single',
      'auto_key', 1, 45, 3, 4, repeat('5', 64), v_author) RETURNING id INTO v_qversion;
  UPDATE questions SET current_version_id = v_qversion WHERE id = v_question;

  -- ----------------------------------------------------------------- people
  INSERT INTO students(display_name, phone, requires_guardian_consent)
    VALUES ('Test minor', '+2348000000001', true) RETURNING id INTO v_minor;
  INSERT INTO students(display_name, phone, requires_guardian_consent)
    VALUES ('Test adult', '+2348000000002', false) RETURNING id INTO v_adult;

  -- A student needs some way of being contacted or identified.
  v_rejected := false;
  BEGIN
    INSERT INTO students(display_name) VALUES ('No contact details');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a student with no contact route was accepted'; END IF;

  INSERT INTO guardians(display_name, phone, preferred_contact_method)
    VALUES ('Test guardian', '+2348000000003', 'whatsapp') RETURNING id INTO v_guardian;

  -- An active guardian link has to record when it was verified.
  v_rejected := false;
  BEGIN
    INSERT INTO guardian_students(guardian_id, student_id, relationship_type, status)
      VALUES (v_guardian, v_minor, 'mother', 'active');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an unverified guardian link was made active'; END IF;

  INSERT INTO guardian_students(guardian_id, student_id, relationship_type, status, verified_at)
    VALUES (v_guardian, v_minor, 'mother', 'active', now()) RETURNING id INTO v_link;

  -- --------------------------------------------------------------- consent
  INSERT INTO study_sessions(student_id, subject_id, session_type, planned_minutes)
    VALUES (v_minor, v_subject, 'practice', 20) RETURNING id INTO v_session;

  -- No consent, no storage.
  v_rejected := false;
  BEGIN
    INSERT INTO attempts(id, student_id, question_version_id, session_id, context,
      selected_option_key, is_correct, response_ms, answered_at_client)
      VALUES (v_attempt, v_minor, v_qversion, v_session, 'practice', 'A', true, 41000, now());
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%no recorded consent%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an attempt was stored without consent'; END IF;

  -- A school-collected consent has to say what the evidence is.
  v_rejected := false;
  BEGIN
    INSERT INTO consents(student_id, consent_type, granted, source)
      VALUES (v_minor, 'data_processing', true, 'school_form');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a school consent without evidence was accepted'; END IF;

  INSERT INTO consents(student_id, consent_type, granted, granted_by_guardian_id, source,
    evidence_note)
    VALUES (v_minor, 'data_processing', true, v_link, 'school_form',
      'Signed consent form held by the school, reference CF-001.');

  -- Only one live consent of each type.
  v_rejected := false;
  BEGIN
    INSERT INTO consents(student_id, consent_type, granted, source, evidence_note)
      VALUES (v_minor, 'data_processing', true, 'in_app', 'Second live consent.');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%duplicate key%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a second live consent was accepted'; END IF;

  -- --------------------------------------------------------------- attempts
  INSERT INTO attempts(id, student_id, question_version_id, session_id, context,
    selected_option_key, is_correct, response_ms, answered_at_client, engine_version)
    VALUES (v_attempt, v_minor, v_qversion, v_session, 'practice', 'A', true, 41000, now(), '0.2.0');

  -- A retried sync carries the same client-generated id and must not double-count.
  v_rejected := false;
  BEGIN
    INSERT INTO attempts(id, student_id, question_version_id, session_id, context,
      selected_option_key, is_correct, response_ms, answered_at_client)
      VALUES (v_attempt, v_minor, v_qversion, v_session, 'practice', 'A', true, 41000, now());
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%duplicate key%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a resynced attempt was stored twice'; END IF;

  -- A marked attempt must say what was chosen.
  v_rejected := false;
  BEGIN
    INSERT INTO attempts(id, student_id, question_version_id, context, is_correct,
      answered_at_client)
      VALUES (gen_random_uuid(), v_minor, v_qversion, 'practice', true, now());
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an attempt was marked without an answer'; END IF;

  -- History cannot be edited …
  v_rejected := false;
  BEGIN
    UPDATE attempts SET is_correct = false WHERE id = v_attempt;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%append-only%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an attempt was edited'; END IF;

  -- … nor deleted by ordinary code …
  v_rejected := false;
  BEGIN
    DELETE FROM attempts WHERE id = v_attempt;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%append-only%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an attempt was deleted without the erasure setting'; END IF;

  -- … but an erasure request can remove it, deliberately and visibly.
  PERFORM set_config('scorepilot.allow_erasure', 'on', true);
  DELETE FROM attempts WHERE id = v_attempt;
  PERFORM set_config('scorepilot.allow_erasure', 'off', true);
  IF EXISTS (SELECT 1 FROM attempts WHERE id = v_attempt) THEN
    RAISE EXCEPTION 'the erasure path did not remove the attempt';
  END IF;

  -- A student who does not need guardian consent can answer straight away.
  INSERT INTO attempts(id, student_id, question_version_id, context, selected_option_key,
    is_correct, response_ms, answered_at_client)
    VALUES (gen_random_uuid(), v_adult, v_qversion, 'practice', 'B', false, 52000, now());

  -- ------------------------------------------------------------ derived state
  INSERT INTO skill_ratings(student_id, skill_id, theta, scored_attempts, levels_seen,
    confidence, last_attempt_at, engine_version)
    VALUES (v_adult, v_skill, 0.31, 1, ARRAY[3]::smallint[], 'low', now(), '0.2.0');
  INSERT INTO review_state(student_id, skill_id, next_review_at, engine_version)
    VALUES (v_adult, v_skill, now() + interval '3 days', '0.2.0');

  IF (SELECT count(*) FROM student_skill_state WHERE student_id = v_adult) <> 1 THEN
    RAISE EXCEPTION 'the planner view does not show the student''s skill state';
  END IF;
  IF (SELECT attempts FROM student_daily_activity WHERE student_id = v_adult) <> 1 THEN
    RAISE EXCEPTION 'daily activity does not count the attempt';
  END IF;

  -- Goals are per subject, out of 100, one active at a time.
  INSERT INTO student_exam_goals(student_id, subject_id, target_score, minutes_per_day,
    study_days)
    VALUES (v_adult, v_subject, 75, 45, ARRAY[1, 2, 3, 4, 5]::smallint[]);
  v_rejected := false;
  BEGIN
    INSERT INTO student_exam_goals(student_id, subject_id, target_score)
      VALUES (v_adult, v_subject, 80);
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%duplicate key%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a second active goal for one subject was accepted'; END IF;

  v_rejected := false;
  BEGIN
    INSERT INTO student_exam_goals(student_id, subject_id, target_score)
      VALUES (v_minor, v_subject, 420);
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a target above 100 was accepted'; END IF;
END $$;

ROLLBACK;
