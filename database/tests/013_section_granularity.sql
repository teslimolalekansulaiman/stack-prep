-- Run after 013_section_granularity.sql in a disposable PostgreSQL database.
-- Local variables are prefixed v_ so they never collide with column names.
BEGIN;
SET LOCAL search_path = stackprep, public;

DO $$
DECLARE
  v_reviewer uuid;
  v_exam uuid;
  v_subject uuid;
  v_document uuid;
  v_version uuid;
  v_topic uuid;
  v_sub_named uuid;
  v_sub_quiet_a uuid;
  v_sub_quiet_b uuid;
  v_paper uuid;
  v_share numeric;
  v_questions numeric;
BEGIN
  INSERT INTO academic_reviewers(display_name) VALUES ('Section reviewer')
    RETURNING id INTO v_reviewer;
  INSERT INTO examinations(name, short_name, exam_body, country_code, status)
    VALUES ('Section test exam', 'TESTSG', 'Test body', 'NG', 'active') RETURNING id INTO v_exam;
  INSERT INTO subjects(examination_id, code, name, status)
    VALUES (v_exam, 'SEC', 'Section test subject', 'active') RETURNING id INTO v_subject;
  INSERT INTO source_documents(examination_id, subject_id, document_type, title, file_uri,
    file_sha256, mime_type, licence_status, storage_permission, student_delivery_permission,
    review_status, reviewed_by, reviewed_at)
    VALUES (v_exam, v_subject, 'syllabus', 'Section test syllabus', 'test://sections',
      repeat('a', 64), 'application/pdf', 'verified', true, true, 'approved', v_reviewer, now())
    RETURNING id INTO v_document;
  INSERT INTO syllabus_versions(subject_id, version_label, source_document_id, status,
    is_current, approved_by, approved_at)
    VALUES (v_subject, 'sec-1', v_document, 'approved', true, v_reviewer, now())
    RETURNING id INTO v_version;

  INSERT INTO curriculum_items(syllabus_version_id, subject_id, item_type, code, name,
    syllabus_status, pilot_support_status)
    VALUES (v_version, v_subject, 'topic', 'SEC.I', 'The only topic', 'explicit', 'supported')
    RETURNING id INTO v_topic;
  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type, code,
    name, syllabus_status, pilot_support_status)
    VALUES (v_version, v_subject, v_topic, 'subtopic', 'SEC.I.1', 'Named by a section',
      'explicit', 'supported')
    RETURNING id INTO v_sub_named;
  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type, code,
    name, syllabus_status, pilot_support_status)
    VALUES (v_version, v_subject, v_topic, 'subtopic', 'SEC.I.2', 'Named by nothing',
      'explicit', 'supported')
    RETURNING id INTO v_sub_quiet_a;
  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type, code,
    name, syllabus_status, pilot_support_status)
    VALUES (v_version, v_subject, v_topic, 'subtopic', 'SEC.I.3', 'Named by nothing either',
      'explicit', 'supported')
    RETURNING id INTO v_sub_quiet_b;

  INSERT INTO exam_papers(subject_id, paper_code, name, response_mode, question_count,
    duration_minutes, options_per_question, score_out_of, values_confirmed,
    confirmation_note, status)
    VALUES (v_subject, 'SEC-1', 'Paper 1', 'objective', 30, 60, 4, 30, true,
      'Fixture paper; every value here is invented for the test.', 'active')
    RETURNING id INTO v_paper;

  -- One section names a subtopic; one names only the topic. Ten questions each.
  INSERT INTO exam_paper_sections(exam_paper_id, subject_id, section_code, name,
    question_count, curriculum_item_id, syllabus_version_id, source_location, review_status,
    reviewed_by, reviewed_at)
    VALUES (v_paper, v_subject, 'PRECISE', 'A section that names its subtopic', 10,
      v_sub_named, v_version, 'page 1', 'approved', v_reviewer, now());
  INSERT INTO exam_paper_sections(exam_paper_id, subject_id, section_code, name,
    question_count, curriculum_item_id, syllabus_version_id, source_location, review_status,
    reviewed_by, reviewed_at)
    VALUES (v_paper, v_subject, 'VAGUE', 'A section that names only the topic', 20,
      v_topic, v_version, 'page 1', 'approved', v_reviewer, now());

  -- The topic's weight is unaffected by how finely its sections are attributed: both
  -- sections still belong to it, and together they are the whole paper.
  SELECT expected_questions INTO v_questions FROM topic_exam_weight
   WHERE topic_id = v_topic AND syllabus_version_id = v_version;
  IF v_questions <> 30 THEN
    RAISE EXCEPTION 'a subtopic-level section changed its topic''s weight: % questions', v_questions;
  END IF;

  -- The named subtopic gets its own ten.
  SELECT expected_questions INTO v_questions FROM subtopic_exam_weight
   WHERE subtopic_id = v_sub_named;
  IF v_questions <> 10 THEN
    RAISE EXCEPTION 'the named subtopic got % questions, not its section''s 10', v_questions;
  END IF;

  -- The twenty the document did not divide go to the two subtopics no section names — ten
  -- each — and NOT to the one that already has its own section. That rule is a judgement,
  -- which is exactly why it is pinned here.
  SELECT expected_questions INTO v_questions FROM subtopic_exam_weight
   WHERE subtopic_id = v_sub_quiet_a;
  IF v_questions <> 10 THEN
    RAISE EXCEPTION 'an unnamed subtopic got % of the undivided 20, not 10', v_questions;
  END IF;

  -- And the shares still add up to the whole paper.
  SELECT sum(share) INTO v_share FROM subtopic_exam_weight WHERE syllabus_version_id = v_version;
  IF abs(v_share - 1) > 0.001 THEN
    RAISE EXCEPTION 'subtopic shares sum to %, not 1', v_share;
  END IF;

  -- A section nobody has approved weighs nothing, as before.
  UPDATE exam_paper_sections SET review_status = 'pending' WHERE section_code = 'PRECISE';
  IF EXISTS (SELECT 1 FROM subtopic_exam_weight WHERE subtopic_id = v_sub_named
               AND expected_questions >= 10) THEN
    RAISE EXCEPTION 'an unapproved section is still carrying its subtopic''s weight';
  END IF;
  UPDATE exam_paper_sections SET review_status = 'approved' WHERE section_code = 'PRECISE';

  -- When every subtopic is named there is nobody left to share the undivided questions with,
  -- so they are spread across all of them rather than disappearing from the paper.
  UPDATE exam_paper_sections SET curriculum_item_id = v_sub_quiet_a
   WHERE section_code = 'PRECISE';
  INSERT INTO exam_paper_sections(exam_paper_id, subject_id, section_code, name,
    question_count, curriculum_item_id, syllabus_version_id, source_location, review_status,
    reviewed_by, reviewed_at)
    VALUES (v_paper, v_subject, 'PRECISE-2', 'Another precise section', 10,
      v_sub_quiet_b, v_version, 'page 1', 'approved', v_reviewer, now());
  INSERT INTO exam_paper_sections(exam_paper_id, subject_id, section_code, name,
    question_count, curriculum_item_id, syllabus_version_id, source_location, review_status,
    reviewed_by, reviewed_at)
    VALUES (v_paper, v_subject, 'PRECISE-3', 'A third precise section', 10,
      v_sub_named, v_version, 'page 1', 'approved', v_reviewer, now());
  SELECT sum(expected_questions) INTO v_questions FROM subtopic_exam_weight
   WHERE syllabus_version_id = v_version;
  -- Allowing a hundredth either way: the undivided twenty splits three ways and each share
  -- is rounded for display, so the total can land a rounding step from the paper's own count.
  IF abs(v_questions - 50) > 0.05 THEN
    RAISE EXCEPTION 'questions went missing when every subtopic was named: % of 50', v_questions;
  END IF;
END $$;

ROLLBACK;
