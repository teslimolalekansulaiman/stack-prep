-- Run after 008_assessments.sql in a disposable PostgreSQL database.
-- Local variables are prefixed v_ so they never collide with column names.
BEGIN;
SET LOCAL search_path = stackprep, public;

DO $$
DECLARE
  v_author uuid;
  v_reviewer uuid;
  v_exam uuid;
  v_subject uuid;
  v_syllabus_doc uuid;
  v_syllabus_version uuid;
  v_topic uuid;
  v_subtopic uuid;
  v_skill uuid;
  v_level uuid;
  v_student uuid;
  v_other_student uuid;
  v_session uuid;
  v_assessment uuid;
  v_practice_question uuid;
  v_practice_version uuid;
  v_placement_a uuid;
  v_placement_b uuid;
  v_sitting uuid;
  v_question uuid;
  v_version uuid;
  v_second_question uuid;
  v_second_version uuid;
  v_rejected boolean;
BEGIN
  INSERT INTO academic_reviewers(display_name) VALUES ('Assessment author') RETURNING id INTO v_author;
  INSERT INTO academic_reviewers(display_name) VALUES ('Assessment reviewer') RETURNING id INTO v_reviewer;
  INSERT INTO examinations(name, short_name, exam_body, country_code, status)
    VALUES ('Assessment test exam', 'TESTX', 'Test body', 'NG', 'active') RETURNING id INTO v_exam;
  INSERT INTO subjects(examination_id, code, name, status)
    VALUES (v_exam, 'ENG', 'English Language', 'active') RETURNING id INTO v_subject;
  INSERT INTO source_documents(examination_id, subject_id, document_type, title, file_uri,
    file_sha256, mime_type, licence_status, storage_permission, student_delivery_permission,
    review_status, reviewed_by, reviewed_at)
    VALUES (v_exam, v_subject, 'syllabus', 'Assessment test syllabus', 'test://assessments',
      repeat('f', 64), 'application/pdf', 'verified', true, true, 'approved', v_reviewer, now())
    RETURNING id INTO v_syllabus_doc;
  INSERT INTO syllabus_versions(subject_id, version_label, source_document_id, status,
    is_current, approved_by, approved_at)
    VALUES (v_subject, 'assessments-v1', v_syllabus_doc, 'approved', true, v_reviewer, now())
    RETURNING id INTO v_syllabus_version;

  INSERT INTO curriculum_items(syllabus_version_id, subject_id, item_type, code, name,
    syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, 'topic', 'LEX', 'Lexis', 'explicit', 'supported')
    RETURNING id INTO v_topic;
  INSERT INTO curriculum_evidence(curriculum_item_id, source_document_id, evidence_kind,
    source_location, review_status, reviewed_by, reviewed_at)
    VALUES (v_topic, v_syllabus_doc, 'inclusion', 'page 1', 'approved', v_reviewer, now());
  UPDATE curriculum_items SET review_status = 'approved', approved_by = v_reviewer,
    approved_at = now() WHERE id = v_topic;

  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type, code,
    name, syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, v_topic, 'subtopic', 'LEX.V', 'Vocabulary',
      'explicit', 'supported') RETURNING id INTO v_subtopic;
  INSERT INTO curriculum_evidence(curriculum_item_id, source_document_id, evidence_kind,
    source_location, review_status, reviewed_by, reviewed_at)
    VALUES (v_subtopic, v_syllabus_doc, 'inclusion', 'page 2', 'approved', v_reviewer, now());
  UPDATE curriculum_items SET review_status = 'approved', approved_by = v_reviewer,
    approved_at = now() WHERE id = v_subtopic;

  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type, code,
    name, syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, v_subtopic, 'skill', 'LEX.V.1',
      'Choose the word that completes a sentence', 'explicit', 'supported')
    RETURNING id INTO v_skill;
  INSERT INTO curriculum_evidence(curriculum_item_id, source_document_id, evidence_kind,
    source_location, review_status, reviewed_by, reviewed_at)
    VALUES (v_skill, v_syllabus_doc, 'inclusion', 'page 3', 'approved', v_reviewer, now());
  UPDATE curriculum_items SET review_status = 'approved', approved_by = v_reviewer,
    approved_at = now() WHERE id = v_skill;
  INSERT INTO curriculum_mastery_levels(curriculum_item_id, level_number, name, description,
    review_status, reviewed_by, reviewed_at)
    VALUES (v_skill, 3, 'Exam standard', 'Answers a standard exam item unaided.',
      'approved', v_reviewer, now()) RETURNING id INTO v_level;

  -- Two approved, deliverable held-out questions.
  INSERT INTO questions(subject_id, origin, usage_pool, created_by)
    VALUES (v_subject, 'authored', 'held_out', v_author) RETURNING id INTO v_question;
  INSERT INTO question_versions(question_id, subject_id, version, stem, response_format,
    marking_method, solution_steps, hints, marks, expected_seconds, mastery_level_number,
    option_count, content_hash, authored_by, answer_source, level_source)
    VALUES (v_question, v_subject, 1, 'The car crashed into a ______ vehicle.', 'mcq_single',
      'auto_key', '["Stationary means not moving."]'::jsonb, '["Which word means not moving?"]'::jsonb,
      1, 45, 3, 4, repeat('6', 64), v_author, 'expert_verified', 'expert_verified')
    RETURNING id INTO v_version;
  INSERT INTO question_options(question_version_id, subject_id, option_key, body, is_correct, display_order)
    VALUES (v_version, v_subject, 'A', 'stationary', true, 1);
  INSERT INTO question_options(question_version_id, subject_id, option_key, body, display_order)
    VALUES (v_version, v_subject, 'B', 'stagnant', 2),
           (v_version, v_subject, 'C', 'stationed', 3),
           (v_version, v_subject, 'D', 'stationery', 4);
  UPDATE question_versions SET review_status = 'approved', reviewed_by = v_reviewer,
    reviewed_at = now() WHERE id = v_version;
  UPDATE questions SET current_version_id = v_version WHERE id = v_question;
  INSERT INTO question_classifications(question_id, subject_id, curriculum_item_id,
    syllabus_version_id, mastery_level_id, classification_role, classification_reason,
    review_status, reviewed_by, reviewed_at)
    VALUES (v_question, v_subject, v_skill, v_syllabus_version, v_level, 'primary',
      'Tests everyday vocabulary.', 'approved', v_reviewer, now());

  INSERT INTO questions(subject_id, origin, usage_pool, created_by)
    VALUES (v_subject, 'authored', 'held_out', v_author) RETURNING id INTO v_second_question;
  INSERT INTO question_versions(question_id, subject_id, version, stem, response_format,
    marking_method, solution_steps, hints, marks, expected_seconds, mastery_level_number,
    option_count, content_hash, authored_by, answer_source, level_source)
    VALUES (v_second_question, v_subject, 1, 'She was ______ about the result.', 'mcq_single',
      'auto_key', '["Anxious fits the sentence."]'::jsonb, '["Which word describes worry?"]'::jsonb,
      1, 45, 3, 4, repeat('7', 64), v_author, 'expert_verified', 'expert_verified')
    RETURNING id INTO v_second_version;
  INSERT INTO question_options(question_version_id, subject_id, option_key, body, is_correct, display_order)
    VALUES (v_second_version, v_subject, 'B', 'anxious', true, 2);
  INSERT INTO question_options(question_version_id, subject_id, option_key, body, display_order)
    VALUES (v_second_version, v_subject, 'A', 'anxiety', 1),
           (v_second_version, v_subject, 'C', 'anxiously', 3),
           (v_second_version, v_subject, 'D', 'anxieties', 4);
  UPDATE question_versions SET review_status = 'approved', reviewed_by = v_reviewer,
    reviewed_at = now() WHERE id = v_second_version;
  UPDATE questions SET current_version_id = v_second_version WHERE id = v_second_question;
  INSERT INTO question_classifications(question_id, subject_id, curriculum_item_id,
    syllabus_version_id, mastery_level_id, classification_role, classification_reason,
    review_status, reviewed_by, reviewed_at)
    VALUES (v_second_question, v_subject, v_skill, v_syllabus_version, v_level, 'primary',
      'Tests word form.', 'approved', v_reviewer, now());

  -- A practice-pool question, for the pool rule.
  INSERT INTO questions(subject_id, origin, usage_pool, created_by)
    VALUES (v_subject, 'authored', 'practice', v_author) RETURNING id INTO v_practice_question;
  INSERT INTO question_versions(question_id, subject_id, version, stem, response_format,
    marking_method, marks, expected_seconds, option_count, content_hash, authored_by)
    VALUES (v_practice_question, v_subject, 1, 'A practice item.', 'mcq_single', 'auto_key',
      1, 45, 4, repeat('8', 64), v_author) RETURNING id INTO v_practice_version;
  UPDATE questions SET current_version_id = v_practice_version WHERE id = v_practice_question;

  INSERT INTO students(display_name, phone, requires_guardian_consent)
    VALUES ('Sitting student', '+2348000000011', false) RETURNING id INTO v_student;
  INSERT INTO students(display_name, phone, requires_guardian_consent)
    VALUES ('Another student', '+2348000000012', false) RETURNING id INTO v_other_student;

  -- ------------------------------------------------------------- publication
  INSERT INTO assessments(subject_id, title, assessment_type, required_pool, duration_minutes)
    VALUES (v_subject, 'Week 0 mini-mock', 'mini_mock', 'held_out', 20)
    RETURNING id INTO v_assessment;

  v_rejected := false;
  BEGIN
    UPDATE assessments SET status = 'published', published_at = now(), total_marks = 2
      WHERE id = v_assessment;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%no questions%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an empty assessment was published'; END IF;

  INSERT INTO assessment_items(assessment_id, question_version_id, position, marks)
    VALUES (v_assessment, v_version, 1, 1) RETURNING id INTO v_placement_a;
  INSERT INTO assessment_items(assessment_id, question_version_id, position, marks)
    VALUES (v_assessment, v_second_version, 2, 1) RETURNING id INTO v_placement_b;

  -- The same question cannot be placed twice.
  v_rejected := false;
  BEGIN
    INSERT INTO assessment_items(assessment_id, question_version_id, position, marks)
      VALUES (v_assessment, v_version, 3, 1);
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%duplicate key%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a question was placed twice in one paper'; END IF;

  -- A mock measures, so it cannot contain a question students practise on.
  INSERT INTO assessment_items(assessment_id, question_version_id, position, marks)
    VALUES (v_assessment, v_practice_version, 3, 1);
  v_rejected := false;
  BEGIN
    UPDATE assessments SET status = 'published', published_at = now(), total_marks = 3
      WHERE id = v_assessment;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%not from the held_out pool%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a practice question was published inside a mock'; END IF;
  DELETE FROM assessment_items WHERE assessment_id = v_assessment AND position = 3;

  -- The declared total has to match what is actually placed.
  v_rejected := false;
  BEGIN
    UPDATE assessments SET status = 'published', published_at = now(), total_marks = 40
      WHERE id = v_assessment;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%does not match%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a wrong mark total was published'; END IF;

  UPDATE assessments SET status = 'published', published_at = now(), total_marks = 2
    WHERE id = v_assessment;

  -- A published paper is frozen.
  v_rejected := false;
  BEGIN
    UPDATE assessment_items SET marks = 5 WHERE id = v_placement_a;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%frozen%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a published paper was edited'; END IF;

  -- --------------------------------------------------------------- the sitting
  INSERT INTO assessment_sittings(assessment_id, student_id, deadline_at)
    VALUES (v_assessment, v_student, now() + interval '20 minutes') RETURNING id INTO v_sitting;

  -- An exam answer belongs to a sitting, not a study session.
  INSERT INTO study_sessions(student_id, subject_id, session_type)
    VALUES (v_student, v_subject, 'practice') RETURNING id INTO v_session;
  v_rejected := false;
  BEGIN
    INSERT INTO attempts(id, student_id, question_version_id, session_id, sitting_id,
      assessment_id, assessment_item_id, context, selected_option_key, is_correct,
      response_ms, answered_at_client)
      VALUES (gen_random_uuid(), v_student, v_version, v_session, v_sitting, v_assessment,
        v_placement_a, 'mini_mock', 'A', true, 30000, now());
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an attempt belonged to both a session and a sitting'; END IF;

  -- Hints do not exist in an exam.
  v_rejected := false;
  BEGIN
    INSERT INTO attempts(id, student_id, question_version_id, sitting_id, assessment_id,
      assessment_item_id, context, selected_option_key, is_correct, response_ms,
      hint_count, answered_at_client)
      VALUES (gen_random_uuid(), v_student, v_version, v_sitting, v_assessment, v_placement_a,
        'mini_mock', 'A', true, 30000, 1, now());
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a hint was used inside an exam'; END IF;

  -- An answer must match the question actually placed at that position.
  v_rejected := false;
  BEGIN
    INSERT INTO attempts(id, student_id, question_version_id, sitting_id, assessment_id,
      assessment_item_id, context, selected_option_key, is_correct, response_ms,
      answered_at_client)
      VALUES (gen_random_uuid(), v_student, v_second_version, v_sitting, v_assessment,
        v_placement_a, 'mini_mock', 'B', true, 30000, now());
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates foreign key constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an answer was recorded against the wrong placement'; END IF;

  -- Another student cannot answer into this sitting.
  v_rejected := false;
  BEGIN
    INSERT INTO attempts(id, student_id, question_version_id, sitting_id, assessment_id,
      assessment_item_id, context, selected_option_key, is_correct, response_ms,
      answered_at_client)
      VALUES (gen_random_uuid(), v_other_student, v_version, v_sitting, v_assessment,
        v_placement_a, 'mini_mock', 'A', true, 30000, now());
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%belongs to another student%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a sitting accepted another student''s answer'; END IF;

  -- A changed answer is a new attempt; the last one counts and the change is visible.
  INSERT INTO attempts(id, student_id, question_version_id, sitting_id, assessment_id,
    assessment_item_id, context, selected_option_key, is_correct, response_ms,
    answered_at_client)
    VALUES (gen_random_uuid(), v_student, v_version, v_sitting, v_assessment, v_placement_a,
      'mini_mock', 'C', false, 21000, now() - interval '2 minutes');
  INSERT INTO attempts(id, student_id, question_version_id, sitting_id, assessment_id,
    assessment_item_id, context, selected_option_key, is_correct, response_ms,
    answered_at_client)
    VALUES (gen_random_uuid(), v_student, v_version, v_sitting, v_assessment, v_placement_a,
      'mini_mock', 'A', true, 33000, now() - interval '1 minute');

  IF (SELECT selected_option_key FROM sitting_final_answers
        WHERE sitting_id = v_sitting AND assessment_item_id = v_placement_a) <> 'A' THEN
    RAISE EXCEPTION 'the final answer is not the last one given';
  END IF;

  -- Question 2 is left unanswered.
  UPDATE assessment_sittings SET status = 'submitted', submitted_at = now() WHERE id = v_sitting;

  -- No more answers once it is submitted.
  v_rejected := false;
  BEGIN
    INSERT INTO attempts(id, student_id, question_version_id, sitting_id, assessment_id,
      assessment_item_id, context, selected_option_key, is_correct, response_ms,
      answered_at_client)
      VALUES (gen_random_uuid(), v_student, v_second_version, v_sitting, v_assessment,
        v_placement_b, 'mini_mock', 'B', true, 30000, now());
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%no further answers%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an answer was accepted after submission'; END IF;

  -- ------------------------------------------------------------------ results
  IF (SELECT questions_placed FROM sitting_results WHERE sitting_id = v_sitting) <> 2 THEN
    RAISE EXCEPTION 'the result does not count both placed questions';
  END IF;
  IF (SELECT questions_answered FROM sitting_results WHERE sitting_id = v_sitting) <> 1 THEN
    RAISE EXCEPTION 'the result does not count the answered question';
  END IF;
  IF (SELECT questions_unanswered FROM sitting_results WHERE sitting_id = v_sitting) <> 1 THEN
    RAISE EXCEPTION 'an unanswered question was not counted as unanswered';
  END IF;
  IF (SELECT answers_changed FROM sitting_results WHERE sitting_id = v_sitting) <> 1 THEN
    RAISE EXCEPTION 'the changed answer was not recorded';
  END IF;
  IF (SELECT raw_score FROM sitting_results WHERE sitting_id = v_sitting) <> 1 THEN
    RAISE EXCEPTION 'the score is wrong';
  END IF;
  IF (SELECT percentage FROM sitting_results WHERE sitting_id = v_sitting) <> 50 THEN
    RAISE EXCEPTION 'the percentage is wrong';
  END IF;

  -- Marking cannot claim a score above the paper's total.
  v_rejected := false;
  BEGIN
    UPDATE assessment_sittings SET status = 'marked', raw_score = 9, max_score = 2,
      marked_at = now() WHERE id = v_sitting;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a score above the maximum was accepted'; END IF;

  UPDATE assessment_sittings SET status = 'marked', raw_score = 1, max_score = 2,
    marked_at = now() WHERE id = v_sitting;
END $$;

ROLLBACK;
