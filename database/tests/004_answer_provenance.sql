-- Run after 004_answer_provenance.sql in a disposable PostgreSQL database.
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
  v_rejected boolean;
BEGIN
  INSERT INTO academic_reviewers(display_name) VALUES ('Answer test author') RETURNING id INTO v_author;
  INSERT INTO academic_reviewers(display_name) VALUES ('Answer test reviewer') RETURNING id INTO v_reviewer;
  INSERT INTO examinations(name, short_name, exam_body, country_code, status)
    VALUES ('Answer provenance exam', 'TESTA', 'Test body', 'NG', 'active') RETURNING id INTO v_exam;
  INSERT INTO subjects(examination_id, code, name, status)
    VALUES (v_exam, 'ENG', 'English Language', 'active') RETURNING id INTO v_subject;
  INSERT INTO source_documents(examination_id, subject_id, document_type, title,
    file_uri, file_sha256, mime_type, licence_status, storage_permission,
    student_delivery_permission, review_status, reviewed_by, reviewed_at)
    VALUES (v_exam, v_subject, 'syllabus', 'Answer test syllabus', 'test://answers',
      repeat('d', 64), 'application/pdf', 'verified', true, true, 'approved', v_reviewer, now())
    RETURNING id INTO v_doc;
  INSERT INTO syllabus_versions(subject_id, version_label, source_document_id, status,
    is_current, approved_by, approved_at)
    VALUES (v_subject, 'answers-v1', v_doc, 'approved', true, v_reviewer, now())
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
    marking_method, solution_steps, hints, marks, expected_seconds, mastery_level_number,
    option_count, content_hash, authored_by, answer_source, answer_confidence, level_source)
    VALUES (v_question, v_subject, 1, 'The car crashed into a ______ vehicle.', 'mcq_single',
      'auto_key', '["stationary means not moving"]'::jsonb, '["Which word means not moving?"]'::jsonb,
      1, 45, 3, 4, repeat('4', 64), v_author, 'model_proposed', 'high', 'expert_verified')
    RETURNING id INTO v_qversion;
  INSERT INTO question_options(question_version_id, subject_id, option_key, body, is_correct, display_order)
    VALUES (v_qversion, v_subject, 'A', 'stationary', true, 1);
  INSERT INTO question_options(question_version_id, subject_id, option_key, body, display_order)
    VALUES (v_qversion, v_subject, 'B', 'stagnant', 2),
           (v_qversion, v_subject, 'C', 'stationed', 3),
           (v_qversion, v_subject, 'D', 'stationery', 4);

  -- A model-proposed answer cannot be approved.
  v_rejected := false;
  BEGIN
    UPDATE question_versions SET review_status = 'approved', reviewed_by = v_reviewer,
      reviewed_at = now() WHERE id = v_qversion;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a model-proposed answer was approved'; END IF;

  -- It shows up in the review queue with its proposed key.
  IF (SELECT proposed_key FROM questions_awaiting_answer_check
        WHERE question_version_id = v_qversion) <> 'A' THEN
    RAISE EXCEPTION 'the review queue does not show the proposed key';
  END IF;

  -- Once an expert verifies it, approval succeeds.
  UPDATE question_versions SET answer_source = 'expert_verified' WHERE id = v_qversion;
  UPDATE question_versions SET review_status = 'approved', reviewed_by = v_reviewer,
    reviewed_at = now() WHERE id = v_qversion;
  IF EXISTS (SELECT 1 FROM questions_awaiting_answer_check WHERE question_version_id = v_qversion) THEN
    RAISE EXCEPTION 'a verified question is still queued for an answer check';
  END IF;

  -- Answer provenance is frozen with the rest of the approved content.
  v_rejected := false;
  BEGIN
    UPDATE question_versions SET answer_source = 'official_key' WHERE id = v_qversion;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%immutable%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'answer provenance was editable after approval'; END IF;
END $$;

ROLLBACK;
