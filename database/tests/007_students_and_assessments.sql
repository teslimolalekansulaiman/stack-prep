-- Run after 007_students_and_assessments.sql in a disposable PostgreSQL database.
-- Local variables are prefixed v_ so they never collide with column names.
--
-- These assert the rules the schema is supposed to enforce: a student cannot be
-- given a question that was not in their paper, a paper cannot be published with
-- content nobody approved, and a marked attempt cannot be quietly reopened.
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
  v_option_a uuid;
  v_draft_question uuid;
  v_draft_version uuid;
  v_student_user uuid;
  v_guardian_user uuid;
  v_student uuid;
  v_assessment uuid;
  v_draft_assessment uuid;
  v_placement uuid;
  v_attempt uuid;
  v_response uuid;
  v_rejected boolean;
BEGIN
  -- ------------------------------------------------ an approved question
  INSERT INTO academic_reviewers(display_name) VALUES ('Assessment test author')
    RETURNING id INTO v_author;
  INSERT INTO academic_reviewers(display_name) VALUES ('Assessment test reviewer')
    RETURNING id INTO v_reviewer;
  INSERT INTO examinations(name, short_name, exam_body, country_code, status)
    VALUES ('Assessment test exam', 'TESTS', 'Test body', 'NG', 'active')
    RETURNING id INTO v_exam;
  INSERT INTO subjects(examination_id, code, name, status)
    VALUES (v_exam, 'ENG', 'English Language', 'active') RETURNING id INTO v_subject;
  INSERT INTO source_documents(examination_id, subject_id, document_type, title,
    file_uri, file_sha256, mime_type, licence_status, storage_permission,
    student_delivery_permission, review_status, reviewed_by, reviewed_at)
    VALUES (v_exam, v_subject, 'syllabus', 'Assessment test syllabus', 'test://assessments',
      repeat('7', 64), 'application/pdf', 'verified', true, true, 'approved', v_reviewer, now())
    RETURNING id INTO v_doc;
  INSERT INTO syllabus_versions(subject_id, version_label, source_document_id, status,
    is_current, approved_by, approved_at)
    VALUES (v_subject, 'assessments-v1', v_doc, 'approved', true, v_reviewer, now())
    RETURNING id INTO v_syllabus_version;

  INSERT INTO curriculum_items(syllabus_version_id, subject_id, item_type, code, name,
    syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, 'topic', 'LEX', 'Lexis', 'explicit', 'supported')
    RETURNING id INTO v_topic;
  INSERT INTO curriculum_evidence(curriculum_item_id, source_document_id, evidence_kind,
    source_location, review_status, reviewed_by, reviewed_at)
    VALUES (v_topic, v_doc, 'inclusion', 'page 1', 'approved', v_reviewer, now());
  UPDATE curriculum_items SET review_status = 'approved', approved_by = v_reviewer,
    approved_at = now() WHERE id = v_topic;

  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type, code,
    name, syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, v_topic, 'subtopic', 'LEX.V', 'Vocabulary',
      'explicit', 'supported') RETURNING id INTO v_subtopic;
  INSERT INTO curriculum_evidence(curriculum_item_id, source_document_id, evidence_kind,
    source_location, review_status, reviewed_by, reviewed_at)
    VALUES (v_subtopic, v_doc, 'inclusion', 'page 2', 'approved', v_reviewer, now());
  UPDATE curriculum_items SET review_status = 'approved', approved_by = v_reviewer,
    approved_at = now() WHERE id = v_subtopic;

  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type, code,
    name, syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, v_subtopic, 'skill', 'LEX.V.1',
      'Choose the word that completes a sentence', 'explicit', 'supported')
    RETURNING id INTO v_skill;
  INSERT INTO curriculum_evidence(curriculum_item_id, source_document_id, evidence_kind,
    source_location, review_status, reviewed_by, reviewed_at)
    VALUES (v_skill, v_doc, 'inclusion', 'page 2', 'approved', v_reviewer, now());
  UPDATE curriculum_items SET review_status = 'approved', approved_by = v_reviewer,
    approved_at = now() WHERE id = v_skill;

  INSERT INTO questions(subject_id, origin, usage_pool, created_by)
    VALUES (v_subject, 'authored', 'practice', v_author) RETURNING id INTO v_question;
  INSERT INTO question_versions(question_id, subject_id, version, stem, response_format,
    marking_method, solution_steps, hints, marks, expected_seconds, mastery_level_number,
    option_count, content_hash, authored_by, answer_source, level_source)
    VALUES (v_question, v_subject, 1, 'The car crashed into a ______ vehicle.', 'mcq_single',
      'auto_key', '["stationary means not moving"]'::jsonb,
      '["Which word means not moving?"]'::jsonb,
      1, 45, 3, 4, repeat('7', 64), v_author, 'expert_verified', 'expert_verified')
    RETURNING id INTO v_qversion;
  INSERT INTO question_options(question_version_id, subject_id, option_key, body,
    is_correct, display_order)
    VALUES (v_qversion, v_subject, 'A', 'stationary', true, 1) RETURNING id INTO v_option_a;
  INSERT INTO question_options(question_version_id, subject_id, option_key, body, display_order)
    VALUES (v_qversion, v_subject, 'B', 'stagnant', 2),
           (v_qversion, v_subject, 'C', 'stationed', 3),
           (v_qversion, v_subject, 'D', 'stationery', 4);
  UPDATE question_versions SET review_status = 'approved', reviewed_by = v_reviewer,
    reviewed_at = now() WHERE id = v_qversion;
  UPDATE questions SET current_version_id = v_qversion WHERE id = v_question;
  INSERT INTO question_classifications(question_id, subject_id, curriculum_item_id,
    syllabus_version_id, classification_role, classification_reason,
    review_status, reviewed_by, reviewed_at)
    VALUES (v_question, v_subject, v_skill, v_syllabus_version, 'primary',
      'Tests vocabulary choice.', 'approved', v_reviewer, now());

  IF NOT EXISTS (SELECT 1 FROM deliverable_questions WHERE question_version_id = v_qversion) THEN
    RAISE EXCEPTION 'fixture error: the question under test is not deliverable';
  END IF;

  -- A second question that nobody approved.
  INSERT INTO questions(subject_id, origin, usage_pool, created_by)
    VALUES (v_subject, 'authored', 'practice', v_author) RETURNING id INTO v_draft_question;
  INSERT INTO question_versions(question_id, subject_id, version, stem, response_format,
    marking_method, marks, expected_seconds, mastery_level_number, option_count,
    content_hash, authored_by)
    VALUES (v_draft_question, v_subject, 1, 'An unreviewed question.', 'mcq_single',
      'auto_key', 1, 45, 3, 4, repeat('8', 64), v_author)
    RETURNING id INTO v_draft_version;

  -- ------------------------------------------------------------- identity
  INSERT INTO users(first_name, last_name, email, role, status)
    VALUES ('Ada', 'Obi', 'ada@example.test', 'student', 'active')
    RETURNING id INTO v_student_user;
  INSERT INTO student_profiles(user_id, class_level)
    VALUES (v_student_user, 'SS3') RETURNING id INTO v_student;

  INSERT INTO users(first_name, last_name, phone, role, status)
    VALUES ('Chidi', 'Obi', '+2348000000000', 'guardian', 'active')
    RETURNING id INTO v_guardian_user;

  -- A guardian's account cannot acquire a student profile.
  v_rejected := false;
  BEGIN
    INSERT INTO student_profiles(user_id) VALUES (v_guardian_user);
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%foreign key%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a guardian was given a student profile'; END IF;

  -- A person with no way to be contacted cannot exist.
  v_rejected := false;
  BEGIN
    INSERT INTO users(first_name, last_name, role) VALUES ('No', 'Contact', 'student');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a user with no email or phone was accepted'; END IF;

  -- ---------------------------------------------------------- assessments
  INSERT INTO assessments(examination_id, subject_id, title, assessment_type, duration_minutes)
    VALUES (v_exam, v_subject, 'English diagnostic', 'diagnostic', 30)
    RETURNING id INTO v_assessment;

  -- An empty paper cannot be published.
  v_rejected := false;
  BEGIN
    UPDATE assessments SET status = 'published', published_at = now() WHERE id = v_assessment;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%no questions%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an empty assessment was published'; END IF;

  -- Nor one holding content nobody approved.
  INSERT INTO assessment_questions(assessment_id, question_id, question_version_id,
    position, marks)
    VALUES (v_assessment, v_draft_question, v_draft_version, 1, 1);
  v_rejected := false;
  BEGIN
    UPDATE assessments SET status = 'published', published_at = now() WHERE id = v_assessment;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%not approved for delivery%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an unapproved question was published to students'; END IF;
  DELETE FROM assessment_questions WHERE assessment_id = v_assessment;

  INSERT INTO assessment_questions(assessment_id, question_id, question_version_id,
    position, marks)
    VALUES (v_assessment, v_question, v_qversion, 1, 1) RETURNING id INTO v_placement;
  UPDATE assessments SET status = 'published', published_at = now(), total_marks = 1
    WHERE id = v_assessment;

  -- Published content is frozen.
  v_rejected := false;
  BEGIN
    INSERT INTO assessment_questions(assessment_id, question_id, question_version_id,
      position, marks)
      VALUES (v_assessment, v_draft_question, v_draft_version, 2, 1);
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%frozen%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a question was added to a published assessment'; END IF;

  -- ------------------------------------------------------------- sittings
  INSERT INTO assessments(examination_id, subject_id, title, assessment_type)
    VALUES (v_exam, v_subject, 'Unpublished set', 'practice')
    RETURNING id INTO v_draft_assessment;
  v_rejected := false;
  BEGIN
    INSERT INTO assessment_attempts(assessment_id, student_id)
      VALUES (v_draft_assessment, v_student);
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%cannot sit%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a student sat an unpublished assessment'; END IF;

  INSERT INTO assessment_attempts(assessment_id, student_id, status, started_at)
    VALUES (v_assessment, v_student, 'in_progress', now()) RETURNING id INTO v_attempt;

  -- The marks on a response must match the marks the question was placed at.
  v_rejected := false;
  BEGIN
    INSERT INTO student_responses(attempt_id, assessment_id, assessment_question_id,
      selected_option_id, maximum_marks)
      VALUES (v_attempt, v_assessment, v_placement, v_option_a, 5);
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%does not match%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a response was worth more than its placement'; END IF;

  INSERT INTO student_responses(attempt_id, assessment_id, assessment_question_id,
    selected_option_id, maximum_marks, awarded_marks, is_correct, marking_status,
    response_ms, submitted_at, marked_at)
    VALUES (v_attempt, v_assessment, v_placement, v_option_a, 1, 1, true, 'auto_marked',
      31000, now(), now()) RETURNING id INTO v_response;

  -- One answer per question per sitting.
  v_rejected := false;
  BEGIN
    INSERT INTO student_responses(attempt_id, assessment_id, assessment_question_id,
      maximum_marks) VALUES (v_attempt, v_assessment, v_placement, 1);
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%duplicate key%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a question was answered twice in one sitting'; END IF;

  -- A student cannot be awarded more than the question was worth.
  v_rejected := false;
  BEGIN
    UPDATE student_responses SET awarded_marks = 2 WHERE id = v_response;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'awarded marks exceeded the maximum'; END IF;

  UPDATE assessment_attempts SET status = 'marked', submitted_at = now(),
    raw_score = 1, maximum_score = 1, percentage = 100, engine_version = '0.2.0'
    WHERE id = v_attempt;

  -- A marked paper cannot be quietly reopened.
  v_rejected := false;
  BEGIN
    UPDATE assessment_attempts SET status = 'in_progress' WHERE id = v_attempt;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%cannot be reopened%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a marked attempt was reopened'; END IF;

  -- And no answer can be added to it afterwards.
  v_rejected := false;
  BEGIN
    INSERT INTO student_responses(attempt_id, assessment_id, assessment_question_id,
      maximum_marks) VALUES (v_attempt, v_assessment, v_placement, 1);
  EXCEPTION WHEN OTHERS THEN
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an answer was added to a marked attempt'; END IF;
END $$;

ROLLBACK;
