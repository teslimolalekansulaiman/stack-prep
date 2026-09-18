-- Run after 010_exam_structure_weights.sql in a disposable PostgreSQL database.
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
  v_topic_a uuid;
  v_topic_b uuid;
  v_topic_c uuid;
  v_sub_a uuid;
  v_skill_a uuid;
  v_paper_objective uuid;
  v_paper_theory uuid;
  v_question uuid;
  v_version uuid;
  v_share numeric;
  v_rejected boolean;
BEGIN
  INSERT INTO academic_reviewers(display_name) VALUES ('Weights author') RETURNING id INTO v_author;
  INSERT INTO academic_reviewers(display_name) VALUES ('Weights reviewer') RETURNING id INTO v_reviewer;
  INSERT INTO examinations(name, short_name, exam_body, country_code, status)
    VALUES ('Weights test exam', 'TESTW', 'Test body', 'NG', 'active') RETURNING id INTO v_exam;
  INSERT INTO subjects(examination_id, code, name, status)
    VALUES (v_exam, 'ENG', 'English Language', 'active') RETURNING id INTO v_subject;
  INSERT INTO source_documents(examination_id, subject_id, document_type, title, file_uri,
    file_sha256, mime_type, licence_status, storage_permission, student_delivery_permission,
    review_status, reviewed_by, reviewed_at)
    VALUES (v_exam, v_subject, 'syllabus', 'Weights syllabus', 'test://weights',
      repeat('c', 64), 'application/pdf', 'verified', true, true, 'approved', v_reviewer, now())
    RETURNING id INTO v_doc;
  INSERT INTO syllabus_versions(subject_id, version_label, source_document_id, status,
    is_current, approved_by, approved_at)
    VALUES (v_subject, 'weights-v1', v_doc, 'approved', true, v_reviewer, now())
    RETURNING id INTO v_syllabus_version;

  INSERT INTO curriculum_items(syllabus_version_id, subject_id, item_type, code, name,
    syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, 'topic', 'LEX', 'Lexis', 'explicit', 'supported')
    RETURNING id INTO v_topic_a;
  INSERT INTO curriculum_items(syllabus_version_id, subject_id, item_type, code, name,
    syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, 'topic', 'STR', 'Structure', 'explicit', 'supported')
    RETURNING id INTO v_topic_b;
  INSERT INTO curriculum_items(syllabus_version_id, subject_id, item_type, code, name,
    syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, 'topic', 'ESS', 'Essay writing', 'explicit', 'supported')
    RETURNING id INTO v_topic_c;
  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type, code,
    name, syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, v_topic_a, 'subtopic', 'LEX.V', 'Vocabulary',
      'explicit', 'supported') RETURNING id INTO v_sub_a;
  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type, code,
    name, syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, v_sub_a, 'skill', 'LEX.V.1', 'Choose a word',
      'explicit', 'supported') RETURNING id INTO v_skill_a;

  INSERT INTO exam_papers(subject_id, paper_code, name, response_mode, question_count,
    duration_minutes, options_per_question, score_out_of, values_confirmed,
    confirmation_note, status)
    VALUES (v_subject, 'W-P1', 'Paper 1', 'objective', 80, 60, 4, 40, true,
      'Printed on the cover.', 'active') RETURNING id INTO v_paper_objective;
  INSERT INTO exam_papers(subject_id, paper_code, name, response_mode, duration_minutes,
    score_out_of, status)
    VALUES (v_subject, 'W-P2', 'Paper 2', 'theory', 120, 100, 'active')
    RETURNING id INTO v_paper_theory;

  -- A section is a claim about the exam, so it has to say where it came from.
  v_rejected := false;
  BEGIN
    INSERT INTO exam_paper_sections(exam_paper_id, subject_id, section_code, name,
      question_count, curriculum_item_id, syllabus_version_id, source_location)
      VALUES (v_paper_objective, v_subject, 'X', 'No citation', 10, v_topic_a,
        v_syllabus_version, '   ');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a section without a source was accepted'; END IF;

  INSERT INTO exam_paper_sections(exam_paper_id, subject_id, section_code, name,
    question_count, marks_total, curriculum_item_id, syllabus_version_id, source_location, review_status)
    VALUES (v_paper_objective, v_subject, 'LEXIS', 'Lexis', 40, 20, v_topic_a,
      v_syllabus_version, 'page 2', 'pending');
  INSERT INTO exam_paper_sections(exam_paper_id, subject_id, section_code, name,
    question_count, marks_total, curriculum_item_id, syllabus_version_id, source_location, review_status)
    VALUES (v_paper_objective, v_subject, 'STRUCTURE', 'Structure', 40, 20, v_topic_b,
      v_syllabus_version, 'page 2', 'pending');
  -- A theory section: real marks, but nothing the adaptive engine can mark.
  INSERT INTO exam_paper_sections(exam_paper_id, subject_id, section_code, name,
    question_count, marks_total, curriculum_item_id, syllabus_version_id, source_location, review_status)
    VALUES (v_paper_theory, v_subject, 'ESSAY', 'Essay', 5, 50, v_topic_c,
      v_syllabus_version, 'page 3', 'pending');

  -- Nothing counts until a reviewer agrees with the reading of the syllabus.
  IF EXISTS (SELECT 1 FROM topic_exam_weight WHERE syllabus_version_id = v_syllabus_version) THEN
    RAISE EXCEPTION 'pending sections produced weights';
  END IF;

  UPDATE exam_paper_sections SET review_status = 'approved', reviewed_by = v_reviewer,
    reviewed_at = now() WHERE syllabus_version_id = v_syllabus_version;

  -- Two objective sections of equal marks: half each, and the essay is excluded because
  -- the engine cannot help a student earn those marks yet.
  SELECT share INTO v_share FROM topic_exam_weight WHERE topic_id = v_topic_a;
  IF v_share <> 0.5 THEN
    RAISE EXCEPTION 'expected an equal split across the two objective sections, got %', v_share;
  END IF;
  IF EXISTS (SELECT 1 FROM topic_exam_weight WHERE topic_id = v_topic_c) THEN
    RAISE EXCEPTION 'a theory section was given an objective weight';
  END IF;
  IF (SELECT round(sum(share), 4) FROM topic_exam_weight
        WHERE syllabus_version_id = v_syllabus_version) <> 1 THEN
    RAISE EXCEPTION 'shares do not add up to one';
  END IF;
  IF (SELECT expected_questions FROM topic_exam_weight WHERE topic_id = v_topic_a) <> 40 THEN
    RAISE EXCEPTION 'expected question count is wrong';
  END IF;

  -- ---------------------------------------------- the bank does not move the weight
  INSERT INTO questions(subject_id, origin, usage_pool, created_by)
    VALUES (v_subject, 'authored', 'practice', v_author) RETURNING id INTO v_question;
  INSERT INTO question_versions(question_id, subject_id, version, stem, response_format,
    marking_method, marks, expected_seconds, option_count, content_hash, authored_by)
    VALUES (v_question, v_subject, 1, 'A lexis question.', 'mcq_single', 'auto_key', 1, 45,
      4, repeat('d', 64), v_author) RETURNING id INTO v_version;
  UPDATE questions SET current_version_id = v_version WHERE id = v_question;
  INSERT INTO question_classifications(question_id, subject_id, curriculum_item_id,
    syllabus_version_id, classification_role, classification_reason, review_status,
    reviewed_by, reviewed_at)
    VALUES (v_question, v_subject, v_skill_a, v_syllabus_version, 'primary',
      'Lexis item.', 'approved', v_reviewer, now());

  SELECT share INTO v_share FROM topic_exam_weight WHERE topic_id = v_topic_a;
  IF v_share <> 0.5 THEN
    RAISE EXCEPTION 'adding a question to the bank changed the exam weight (it must not)';
  END IF;

  -- Coverage is reported separately, so the gap between the exam and our bank is visible.
  IF (SELECT questions_in_bank FROM topic_bank_coverage WHERE topic_id = v_topic_a) <> 1 THEN
    RAISE EXCEPTION 'bank coverage does not count the question';
  END IF;
  IF (SELECT questions_in_bank FROM topic_weight_vs_coverage WHERE topic_id = v_topic_b) <> 0 THEN
    RAISE EXCEPTION 'a weighted topic with no questions should show zero coverage, not vanish';
  END IF;
END $$;

ROLLBACK;
