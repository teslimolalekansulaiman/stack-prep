-- Run after 009_learning_profile.sql in a disposable PostgreSQL database.
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
  v_subtopic_a uuid;
  v_subtopic_b uuid;
  v_skill_a uuid;
  v_skill_b uuid;
  v_skill_untouched uuid;
  v_misconception uuid;
  v_question uuid;
  v_version uuid;
  v_student uuid;
  v_session uuid;
  v_row record;
BEGIN
  -- ---------------------------------------------------------------- fixtures
  INSERT INTO academic_reviewers(display_name) VALUES ('Profile author') RETURNING id INTO v_author;
  INSERT INTO academic_reviewers(display_name) VALUES ('Profile reviewer') RETURNING id INTO v_reviewer;
  INSERT INTO examinations(name, short_name, exam_body, country_code, status)
    VALUES ('Profile test exam', 'TESTP', 'Test body', 'NG', 'active') RETURNING id INTO v_exam;
  INSERT INTO subjects(examination_id, code, name, status)
    VALUES (v_exam, 'ENG', 'English Language', 'active') RETURNING id INTO v_subject;
  INSERT INTO source_documents(examination_id, subject_id, document_type, title, file_uri,
    file_sha256, mime_type, licence_status, storage_permission, student_delivery_permission,
    review_status, reviewed_by, reviewed_at)
    VALUES (v_exam, v_subject, 'syllabus', 'Profile syllabus', 'test://profile',
      repeat('9', 64), 'application/pdf', 'verified', true, true, 'approved', v_reviewer, now())
    RETURNING id INTO v_doc;
  INSERT INTO syllabus_versions(subject_id, version_label, source_document_id, status,
    is_current, approved_by, approved_at)
    VALUES (v_subject, 'profile-v1', v_doc, 'approved', true, v_reviewer, now())
    RETURNING id INTO v_syllabus_version;

  INSERT INTO curriculum_items(syllabus_version_id, subject_id, item_type, code, name,
    syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, 'topic', 'LEX', 'Lexis', 'explicit', 'supported')
    RETURNING id INTO v_topic;
  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type, code,
    name, syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, v_topic, 'subtopic', 'LEX.V', 'Vocabulary',
      'explicit', 'supported') RETURNING id INTO v_subtopic_a;
  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type, code,
    name, syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, v_topic, 'subtopic', 'LEX.I', 'Idioms',
      'explicit', 'supported') RETURNING id INTO v_subtopic_b;
  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type, code,
    name, syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, v_subtopic_a, 'skill', 'LEX.V.1',
      'Choose the word that completes a sentence', 'explicit', 'supported')
    RETURNING id INTO v_skill_a;
  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type, code,
    name, syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, v_subtopic_a, 'skill', 'LEX.V.2',
      'Distinguish confusable words', 'explicit', 'supported')
    RETURNING id INTO v_skill_b;
  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type, code,
    name, syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, v_subtopic_b, 'skill', 'LEX.I.1',
      'Interpret an idiom', 'explicit', 'supported') RETURNING id INTO v_skill_untouched;

  INSERT INTO misconceptions(subject_id, code, name, description, review_status, reviewed_by,
    reviewed_at)
    VALUES (v_subject, 'homophone-confusion', 'Homophone confusion',
      'Chooses a word that sounds the same but means something else.', 'approved',
      v_reviewer, now()) RETURNING id INTO v_misconception;

  INSERT INTO questions(subject_id, origin, usage_pool, created_by)
    VALUES (v_subject, 'authored', 'practice', v_author) RETURNING id INTO v_question;
  INSERT INTO question_versions(question_id, subject_id, version, stem, response_format,
    marking_method, marks, expected_seconds, mastery_level_number, option_count,
    content_hash, authored_by)
    VALUES (v_question, v_subject, 1, 'The car crashed into a ______ vehicle.', 'mcq_single',
      'auto_key', 1, 45, 3, 4, repeat('a', 64), v_author) RETURNING id INTO v_version;
  INSERT INTO question_options(question_version_id, subject_id, option_key, body, is_correct,
    display_order)
    VALUES (v_version, v_subject, 'A', 'stationary', true, 1);
  INSERT INTO question_options(question_version_id, subject_id, option_key, body,
    misconception_id, display_order)
    VALUES (v_version, v_subject, 'D', 'stationery', v_misconception, 4);
  INSERT INTO question_options(question_version_id, subject_id, option_key, body, display_order)
    VALUES (v_version, v_subject, 'B', 'stagnant', 2),
           (v_version, v_subject, 'C', 'stationed', 3);
  UPDATE questions SET current_version_id = v_version WHERE id = v_question;
  INSERT INTO question_classifications(question_id, subject_id, curriculum_item_id,
    syllabus_version_id, classification_role, classification_reason, review_status,
    reviewed_by, reviewed_at)
    VALUES (v_question, v_subject, v_skill_a, v_syllabus_version, 'primary',
      'Tests everyday vocabulary.', 'approved', v_reviewer, now());

  INSERT INTO students(display_name, phone, requires_guardian_consent)
    VALUES ('Profile student', '+2348000000021', false) RETURNING id INTO v_student;
  INSERT INTO student_exam_goals(student_id, subject_id, target_score, minutes_per_day)
    VALUES (v_student, v_subject, 70, 45);
  INSERT INTO study_sessions(student_id, subject_id, session_type)
    VALUES (v_student, v_subject, 'practice') RETURNING id INTO v_session;

  -- Two answers on the same question: the wrong one first, then a correct retry.
  INSERT INTO attempts(id, student_id, question_version_id, session_id, context,
    selected_option_key, is_correct, response_ms, answered_at_client)
    VALUES (gen_random_uuid(), v_student, v_version, v_session, 'practice', 'D', false,
      52000, now() - interval '10 minutes');
  INSERT INTO attempts(id, student_id, question_version_id, session_id, context,
    selected_option_key, is_correct, response_ms, answered_at_client)
    VALUES (gen_random_uuid(), v_student, v_version, v_session, 'practice', 'A', true,
      31000, now() - interval '5 minutes');

  INSERT INTO skill_ratings(student_id, skill_id, theta, scored_attempts, levels_seen,
    confidence, last_attempt_at, last_success_at, engine_version)
    VALUES (v_student, v_skill_a, 0.4, 2, ARRAY[3]::smallint[], 'low',
      now() - interval '5 minutes', now() - interval '5 minutes', '0.2.0');

  -- ------------------------------------------------- the whole syllabus is linked
  IF (SELECT count(*) FROM student_syllabus_map WHERE student_id = v_student) <> 6 THEN
    RAISE EXCEPTION 'the map does not cover every topic, subtopic and skill';
  END IF;
  IF (SELECT count(*) FROM student_syllabus_map
        WHERE student_id = v_student AND item_type = 'skill' AND attempts = 0) <> 2 THEN
    RAISE EXCEPTION 'untouched skills are missing from the map';
  END IF;

  SELECT * INTO v_row FROM student_syllabus_map
   WHERE student_id = v_student AND curriculum_item_id = v_skill_a;
  IF v_row.attempts <> 2 OR v_row.correct <> 1 OR v_row.wrong <> 1 THEN
    RAISE EXCEPTION 'the skill row does not count what the student actually did';
  END IF;
  IF v_row.subtopic_name <> 'Vocabulary' OR v_row.topic_name <> 'Lexis' THEN
    RAISE EXCEPTION 'the skill is not placed under its subtopic and topic';
  END IF;
  IF round(v_row.mastery_estimate, 3) <> round((1 / (1 + exp(-0.4)))::numeric, 3) THEN
    RAISE EXCEPTION 'mastery_estimate does not follow the rating';
  END IF;

  -- ------------------------------------------------------------ subtopic state
  SELECT * INTO v_row FROM student_subtopic_state
   WHERE student_id = v_student AND subtopic_id = v_subtopic_a;
  IF v_row.skills_total <> 2 OR v_row.skills_assessed <> 1 OR v_row.skills_untouched <> 1 THEN
    RAISE EXCEPTION 'subtopic coverage is wrong';
  END IF;
  IF v_row.attempts <> 2 OR v_row.correct <> 1 THEN
    RAISE EXCEPTION 'subtopic evidence is wrong';
  END IF;

  SELECT * INTO v_row FROM student_subtopic_state
   WHERE student_id = v_student AND subtopic_id = v_subtopic_b;
  IF v_row.skills_assessed <> 0 OR v_row.attempts <> 0 THEN
    RAISE EXCEPTION 'an untouched subtopic should still appear, with nothing recorded';
  END IF;

  -- --------------------------------------------------------- question history
  SELECT * INTO v_row FROM student_question_history
   WHERE student_id = v_student AND question_version_id = v_version;
  IF v_row.times_attempted <> 2 OR NOT v_row.ever_correct OR NOT v_row.last_outcome THEN
    RAISE EXCEPTION 'question history does not reflect the retry';
  END IF;
  IF v_row.last_choice <> 'A' THEN
    RAISE EXCEPTION 'question history does not keep the latest choice';
  END IF;

  -- ------------------------------------------------------- context for the tutor
  SELECT * INTO v_row FROM student_recent_answers
   WHERE student_id = v_student AND recency = 2;
  IF v_row.selected_option_key <> 'D' OR v_row.is_correct THEN
    RAISE EXCEPTION 'the earlier wrong answer is not second in the recent list';
  END IF;
  IF v_row.misconception_code <> 'homophone-confusion' THEN
    RAISE EXCEPTION 'the wrong answer does not carry its misconception';
  END IF;
  IF v_row.correct_option_key <> 'A' OR v_row.skill_code <> 'LEX.V.1' THEN
    RAISE EXCEPTION 'the tutor context is missing the correct answer or the skill';
  END IF;

  -- A paused goal drops out of the map: it is what the student is preparing for now.
  UPDATE student_exam_goals SET status = 'paused' WHERE student_id = v_student;
  IF EXISTS (SELECT 1 FROM student_syllabus_map WHERE student_id = v_student) THEN
    RAISE EXCEPTION 'a paused goal still appears in the map';
  END IF;
END $$;

ROLLBACK;
