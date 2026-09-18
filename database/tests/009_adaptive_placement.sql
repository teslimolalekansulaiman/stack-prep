-- Run after 009_adaptive_placement.sql in a disposable PostgreSQL database.
-- Local variables are prefixed v_ so they never collide with column names.
--
-- The claim under test: an adaptive session may grow while it is open, a fixed
-- paper may not, and neither may serve a student anything nobody approved.
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
  v_second_question uuid;
  v_second_version uuid;
  v_draft_question uuid;
  v_draft_version uuid;
  v_student_user uuid;
  v_student uuid;
  v_adaptive uuid;
  v_fixed uuid;
  v_placement uuid;
  v_rejected boolean;
BEGIN
  INSERT INTO academic_reviewers(display_name) VALUES ('Adaptive test author')
    RETURNING id INTO v_author;
  INSERT INTO academic_reviewers(display_name) VALUES ('Adaptive test reviewer')
    RETURNING id INTO v_reviewer;
  INSERT INTO examinations(name, short_name, exam_body, country_code, status)
    VALUES ('Adaptive test exam', 'TESTX', 'Test body', 'NG', 'active')
    RETURNING id INTO v_exam;
  INSERT INTO subjects(examination_id, code, name, status)
    VALUES (v_exam, 'ENG', 'English Language', 'active') RETURNING id INTO v_subject;
  INSERT INTO source_documents(examination_id, subject_id, document_type, title,
    file_uri, file_sha256, mime_type, licence_status, storage_permission,
    student_delivery_permission, review_status, reviewed_by, reviewed_at)
    VALUES (v_exam, v_subject, 'syllabus', 'Adaptive test syllabus', 'test://adaptive',
      repeat('b', 64), 'application/pdf', 'verified', true, true, 'approved',
      v_reviewer, now())
    RETURNING id INTO v_doc;
  INSERT INTO syllabus_versions(subject_id, version_label, source_document_id, status,
    is_current, approved_by, approved_at)
    VALUES (v_subject, 'adaptive-v1', v_doc, 'approved', true, v_reviewer, now())
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

  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type,
    code, name, syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, v_topic, 'subtopic', 'LEX.V', 'Vocabulary',
      'explicit', 'supported') RETURNING id INTO v_subtopic;
  INSERT INTO curriculum_evidence(curriculum_item_id, source_document_id, evidence_kind,
    source_location, review_status, reviewed_by, reviewed_at)
    VALUES (v_subtopic, v_doc, 'inclusion', 'page 2', 'approved', v_reviewer, now());
  UPDATE curriculum_items SET review_status = 'approved', approved_by = v_reviewer,
    approved_at = now() WHERE id = v_subtopic;

  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type,
    code, name, syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, v_subtopic, 'skill', 'LEX.V.1',
      'Choose the word that completes a sentence', 'explicit', 'supported')
    RETURNING id INTO v_skill;
  INSERT INTO curriculum_evidence(curriculum_item_id, source_document_id, evidence_kind,
    source_location, review_status, reviewed_by, reviewed_at)
    VALUES (v_skill, v_doc, 'inclusion', 'page 2', 'approved', v_reviewer, now());
  UPDATE curriculum_items SET review_status = 'approved', approved_by = v_reviewer,
    approved_at = now() WHERE id = v_skill;

  -- Two approved questions, and one nobody reviewed.
  INSERT INTO questions(subject_id, origin, usage_pool, created_by)
    VALUES (v_subject, 'authored', 'practice', v_author) RETURNING id INTO v_question;
  INSERT INTO question_versions(question_id, subject_id, version, stem, response_format,
    marking_method, solution_steps, hints, marks, expected_seconds, mastery_level_number,
    option_count, content_hash, authored_by, answer_source, level_source)
    VALUES (v_question, v_subject, 1, 'The car crashed into a ______ vehicle.', 'mcq_single',
      'auto_key', '["stationary means not moving"]'::jsonb, '["Not moving."]'::jsonb,
      1, 45, 3, 4, repeat('b', 64), v_author, 'expert_verified', 'expert_verified')
    RETURNING id INTO v_qversion;
  INSERT INTO question_options(question_version_id, subject_id, option_key, body,
    is_correct, display_order)
    VALUES (v_qversion, v_subject, 'A', 'stationary', true, 1);
  INSERT INTO question_options(question_version_id, subject_id, option_key, body, display_order)
    VALUES (v_qversion, v_subject, 'B', 'stagnant', 2),
           (v_qversion, v_subject, 'C', 'stationed', 3),
           (v_qversion, v_subject, 'D', 'stationery', 4);
  UPDATE question_versions SET review_status = 'approved', reviewed_by = v_reviewer,
    reviewed_at = now() WHERE id = v_qversion;
  UPDATE questions SET current_version_id = v_qversion WHERE id = v_question;
  INSERT INTO question_classifications(question_id, subject_id, curriculum_item_id,
    syllabus_version_id, classification_role, classification_reason, review_status,
    reviewed_by, reviewed_at)
    VALUES (v_question, v_subject, v_skill, v_syllabus_version, 'primary',
      'Vocabulary choice.', 'approved', v_reviewer, now());

  INSERT INTO questions(subject_id, origin, usage_pool, created_by)
    VALUES (v_subject, 'authored', 'practice', v_author) RETURNING id INTO v_second_question;
  INSERT INTO question_versions(question_id, subject_id, version, stem, response_format,
    marking_method, solution_steps, hints, marks, expected_seconds, mastery_level_number,
    option_count, content_hash, authored_by, answer_source, level_source)
    VALUES (v_second_question, v_subject, 1, 'She was ______ about the result.', 'mcq_single',
      'auto_key', '["anxious means worried"]'::jsonb, '["Worried."]'::jsonb,
      1, 45, 4, 4, repeat('c', 64), v_author, 'expert_verified', 'expert_verified')
    RETURNING id INTO v_second_version;
  INSERT INTO question_options(question_version_id, subject_id, option_key, body,
    is_correct, display_order)
    VALUES (v_second_version, v_subject, 'A', 'anxious', true, 1);
  INSERT INTO question_options(question_version_id, subject_id, option_key, body, display_order)
    VALUES (v_second_version, v_subject, 'B', 'anxiety', 2),
           (v_second_version, v_subject, 'C', 'anxiously', 3),
           (v_second_version, v_subject, 'D', 'anxiousness', 4);
  UPDATE question_versions SET review_status = 'approved', reviewed_by = v_reviewer,
    reviewed_at = now() WHERE id = v_second_version;
  UPDATE questions SET current_version_id = v_second_version WHERE id = v_second_question;
  INSERT INTO question_classifications(question_id, subject_id, curriculum_item_id,
    syllabus_version_id, classification_role, classification_reason, review_status,
    reviewed_by, reviewed_at)
    VALUES (v_second_question, v_subject, v_skill, v_syllabus_version, 'primary',
      'Vocabulary choice.', 'approved', v_reviewer, now());

  INSERT INTO questions(subject_id, origin, usage_pool, created_by)
    VALUES (v_subject, 'authored', 'practice', v_author) RETURNING id INTO v_draft_question;
  INSERT INTO question_versions(question_id, subject_id, version, stem, response_format,
    marking_method, marks, expected_seconds, mastery_level_number, option_count,
    content_hash, authored_by)
    VALUES (v_draft_question, v_subject, 1, 'An unreviewed question.', 'mcq_single',
      'auto_key', 1, 45, 3, 4, repeat('d', 64), v_author)
    RETURNING id INTO v_draft_version;

  INSERT INTO users(first_name, last_name, email, role, status)
    VALUES ('Ada', 'Obi', 'ada.adaptive@example.test', 'student', 'active')
    RETURNING id INTO v_student_user;
  INSERT INTO student_profiles(user_id) VALUES (v_student_user) RETURNING id INTO v_student;

  -- An adaptive set belongs to one learner.
  v_rejected := false;
  BEGIN
    INSERT INTO assessments(examination_id, subject_id, title, assessment_type,
      delivery_mode)
      VALUES (v_exam, v_subject, 'Shared adaptive set', 'practice', 'adaptive');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an adaptive set was created for nobody'; END IF;

  -- An adaptive session starts empty: its first question is chosen after the
  -- student begins, not before.
  INSERT INTO assessments(examination_id, subject_id, title, assessment_type,
    delivery_mode, created_for_student_id, status, published_at)
    VALUES (v_exam, v_subject, 'Ada: vocabulary practice', 'practice', 'adaptive',
      v_student, 'published', now())
    RETURNING id INTO v_adaptive;

  -- And grows as the engine picks.
  INSERT INTO assessment_questions(assessment_id, question_id, question_version_id,
    position, marks)
    VALUES (v_adaptive, v_question, v_qversion, 1, 1) RETURNING id INTO v_placement;
  INSERT INTO assessment_questions(assessment_id, question_id, question_version_id,
    position, marks)
    VALUES (v_adaptive, v_second_question, v_second_version, 2, 1);
  IF (SELECT count(*) FROM assessment_questions WHERE assessment_id = v_adaptive) <> 2 THEN
    RAISE EXCEPTION 'the adaptive session did not grow';
  END IF;

  -- But never with something nobody approved.
  v_rejected := false;
  BEGIN
    INSERT INTO assessment_questions(assessment_id, question_id, question_version_id,
      position, marks)
      VALUES (v_adaptive, v_draft_question, v_draft_version, 3, 1);
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%not approved for delivery%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an unapproved question was served to a student'; END IF;

  -- A question already served cannot be swapped or withdrawn.
  v_rejected := false;
  BEGIN
    UPDATE assessment_questions SET marks = 2 WHERE id = v_placement;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%frozen%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a served question was edited'; END IF;

  v_rejected := false;
  BEGIN
    DELETE FROM assessment_questions WHERE id = v_placement;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%frozen%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a served question was withdrawn'; END IF;

  -- A fixed paper is still a fixed paper.
  INSERT INTO assessments(examination_id, subject_id, title, assessment_type,
    delivery_mode)
    VALUES (v_exam, v_subject, 'Fixed mock', 'mock', 'fixed') RETURNING id INTO v_fixed;
  INSERT INTO assessment_questions(assessment_id, question_id, question_version_id,
    position, marks)
    VALUES (v_fixed, v_question, v_qversion, 1, 1);
  UPDATE assessments SET status = 'published', published_at = now() WHERE id = v_fixed;

  v_rejected := false;
  BEGIN
    INSERT INTO assessment_questions(assessment_id, question_id, question_version_id,
      position, marks)
      VALUES (v_fixed, v_second_question, v_second_version, 2, 1);
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%frozen%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a published fixed paper gained a question'; END IF;

  -- An empty fixed paper still cannot be published.
  v_rejected := false;
  BEGIN
    INSERT INTO assessments(examination_id, subject_id, title, assessment_type,
      delivery_mode, status, published_at)
      VALUES (v_exam, v_subject, 'Empty mock', 'mock', 'fixed', 'published', now());
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%no questions%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an empty fixed paper was published'; END IF;
END $$;

ROLLBACK;
