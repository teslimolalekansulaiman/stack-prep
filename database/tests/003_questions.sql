-- Run after 003_questions.sql in a disposable PostgreSQL database.
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
  v_paper_doc uuid;
  v_syllabus_version uuid;
  v_topic uuid;
  v_subtopic uuid;
  v_skill_a uuid;
  v_skill_b uuid;
  v_level_a uuid;
  v_level_b uuid;
  v_paper uuid;
  v_misconception uuid;
  v_question uuid;
  v_qversion uuid;
  v_held_out uuid;
  v_held_out_version uuid;
  v_essay_question uuid;
  v_rejected boolean;
BEGIN
  -- ---------------------------------------------------------------- fixtures
  INSERT INTO academic_reviewers(display_name) VALUES ('Test author') RETURNING id INTO v_author;
  INSERT INTO academic_reviewers(display_name) VALUES ('Test reviewer') RETURNING id INTO v_reviewer;
  INSERT INTO examinations(name, short_name, exam_body, country_code, status)
    VALUES ('Synthetic objective exam', 'TESTQ', 'Test body', 'NG', 'active')
    RETURNING id INTO v_exam;
  INSERT INTO subjects(examination_id, code, name, status)
    VALUES (v_exam, 'MATH', 'Mathematics', 'active') RETURNING id INTO v_subject;

  INSERT INTO source_documents(examination_id, subject_id, document_type, title,
    file_uri, file_sha256, mime_type, licence_status, storage_permission,
    student_delivery_permission, review_status, reviewed_by, reviewed_at)
    VALUES (v_exam, v_subject, 'syllabus', 'Synthetic syllabus', 'test://syllabus',
      repeat('b', 64), 'application/pdf', 'verified', true, true, 'approved', v_reviewer, now())
    RETURNING id INTO v_syllabus_doc;
  INSERT INTO source_documents(examination_id, subject_id, document_type, title,
    file_uri, file_sha256, mime_type, licence_status, storage_permission,
    student_delivery_permission, review_status, reviewed_by, reviewed_at)
    VALUES (v_exam, v_subject, 'paper', 'Synthetic objective paper', 'test://paper',
      repeat('c', 64), 'application/pdf', 'verified', true, true, 'approved', v_reviewer, now())
    RETURNING id INTO v_paper_doc;

  INSERT INTO syllabus_versions(subject_id, version_label, source_document_id,
    status, is_current, approved_by, approved_at)
    VALUES (v_subject, 'q-test-v1', v_syllabus_doc, 'approved', true, v_reviewer, now())
    RETURNING id INTO v_syllabus_version;

  INSERT INTO curriculum_items(syllabus_version_id, subject_id, item_type, code, name,
    syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, 'topic', 'ALG', 'Algebra', 'explicit', 'supported')
    RETURNING id INTO v_topic;
  INSERT INTO curriculum_evidence(curriculum_item_id, source_document_id, evidence_kind,
    source_location, review_status, reviewed_by, reviewed_at)
    VALUES (v_topic, v_syllabus_doc, 'inclusion', 'page 1', 'approved', v_reviewer, now());
  UPDATE curriculum_items SET review_status = 'approved', approved_by = v_reviewer,
    approved_at = now() WHERE id = v_topic;

  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type,
    code, name, syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, v_topic, 'subtopic', 'ALG.EQ', 'Equations',
      'explicit', 'supported') RETURNING id INTO v_subtopic;
  INSERT INTO curriculum_evidence(curriculum_item_id, source_document_id, evidence_kind,
    source_location, review_status, reviewed_by, reviewed_at)
    VALUES (v_subtopic, v_syllabus_doc, 'inclusion', 'page 2', 'approved', v_reviewer, now());
  UPDATE curriculum_items SET review_status = 'approved', approved_by = v_reviewer,
    approved_at = now() WHERE id = v_subtopic;

  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type,
    code, name, syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, v_subtopic, 'skill', 'ALG.EQ.S1',
      'Solve linear equations', 'explicit', 'supported') RETURNING id INTO v_skill_a;
  INSERT INTO curriculum_evidence(curriculum_item_id, source_document_id, evidence_kind,
    source_location, review_status, reviewed_by, reviewed_at)
    VALUES (v_skill_a, v_syllabus_doc, 'inclusion', 'page 3', 'approved', v_reviewer, now());
  UPDATE curriculum_items SET review_status = 'approved', approved_by = v_reviewer,
    approved_at = now() WHERE id = v_skill_a;

  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type,
    code, name, syllabus_status, pilot_support_status)
    VALUES (v_syllabus_version, v_subject, v_subtopic, 'skill', 'ALG.EQ.S2',
      'Factorise quadratics', 'explicit', 'supported') RETURNING id INTO v_skill_b;
  INSERT INTO curriculum_evidence(curriculum_item_id, source_document_id, evidence_kind,
    source_location, review_status, reviewed_by, reviewed_at)
    VALUES (v_skill_b, v_syllabus_doc, 'inclusion', 'page 4', 'approved', v_reviewer, now());
  UPDATE curriculum_items SET review_status = 'approved', approved_by = v_reviewer,
    approved_at = now() WHERE id = v_skill_b;

  INSERT INTO curriculum_mastery_levels(curriculum_item_id, level_number, name,
    description, review_status, reviewed_by, reviewed_at)
    VALUES (v_skill_a, 3, 'Exam standard', 'Solves a standard exam item unaided.',
      'approved', v_reviewer, now()) RETURNING id INTO v_level_a;
  INSERT INTO curriculum_mastery_levels(curriculum_item_id, level_number, name,
    description, review_status, reviewed_by, reviewed_at)
    VALUES (v_skill_b, 3, 'Exam standard', 'Factorises a standard quadratic.',
      'approved', v_reviewer, now()) RETURNING id INTO v_level_b;

  INSERT INTO exam_papers(subject_id, paper_code, name, response_mode, question_count,
    duration_minutes, options_per_question, score_out_of, values_confirmed,
    confirmation_note, pilot_support_status, status)
    VALUES (v_subject, 'P1', 'Paper I (objective)', 'objective', 50, 90, 4, 100, true,
      'Structure confirmed from the synthetic test paper.', 'supported', 'active')
    RETURNING id INTO v_paper;

  INSERT INTO misconceptions(subject_id, code, name, description, review_status,
    reviewed_by, reviewed_at)
    VALUES (v_subject, 'sign-error', 'Sign error',
      'Moves a term across the equals sign without changing its sign.',
      'approved', v_reviewer, now()) RETURNING id INTO v_misconception;

  -- ------------------------------------------------- paper structure honesty
  v_rejected := false;
  BEGIN
    INSERT INTO exam_papers(subject_id, paper_code, name, response_mode, pilot_support_status)
      VALUES (v_subject, 'P9', 'Unconfirmed paper', 'objective', 'supported');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'unconfirmed paper was marked supported'; END IF;

  -- ------------------------------------------------------------- a question
  INSERT INTO questions(subject_id, exam_paper_id, origin, source_document_id, exam_year,
    paper_code, question_number, usage_pool, created_by)
    VALUES (v_subject, v_paper, 'past_paper', v_paper_doc, 2024, 'P1', '12',
      'practice', v_author) RETURNING id INTO v_question;

  INSERT INTO question_versions(question_id, subject_id, version, stem, response_format,
    marking_method, solution_steps, hints, marks, expected_seconds, mastery_level_number,
    option_count, content_hash, authored_by, answer_source, level_source)
    VALUES (v_question, v_subject, 1, 'Solve 2x + 5 = 17.', 'mcq_single', 'auto_key',
      '["Subtract 5 from both sides", "Divide both sides by 2", "x = 6"]'::jsonb,
      '["What happens to 5 when it moves across the equals sign?"]'::jsonb,
      2, 75, 3, 4, repeat('1', 64), v_author, 'expert_verified', 'expert_verified')
    RETURNING id INTO v_qversion;

  INSERT INTO question_options(question_version_id, subject_id, option_key, body,
    is_correct, display_order)
    VALUES (v_qversion, v_subject, 'A', 'x = 6', true, 1);
  INSERT INTO question_options(question_version_id, subject_id, option_key, body,
    misconception_id, display_order)
    VALUES (v_qversion, v_subject, 'B', 'x = 11', v_misconception, 2);
  INSERT INTO question_options(question_version_id, subject_id, option_key, body,
    distractor_note, display_order)
    VALUES (v_qversion, v_subject, 'C', 'x = 12', 'Forgot to halve.', 3);

  -- A second correct option is impossible.
  v_rejected := false;
  BEGIN
    INSERT INTO question_options(question_version_id, subject_id, option_key, body,
      is_correct, display_order)
      VALUES (v_qversion, v_subject, 'D', 'x = 22', true, 4);
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%duplicate key%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a second correct option was accepted'; END IF;

  -- Three options are not enough for an objective item.
  v_rejected := false;
  BEGIN
    UPDATE question_versions SET review_status = 'approved', reviewed_by = v_reviewer,
      reviewed_at = now() WHERE id = v_qversion;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%at least four options%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a three-option objective question was approved'; END IF;

  INSERT INTO question_options(question_version_id, subject_id, option_key, body,
    distractor_note, display_order)
    VALUES (v_qversion, v_subject, 'D', 'x = 22', 'Added instead of subtracting.', 4);

  -- option_count must describe the options actually stored.
  UPDATE question_versions SET option_count = 5 WHERE id = v_qversion;
  v_rejected := false;
  BEGIN
    UPDATE question_versions SET review_status = 'approved', reviewed_by = v_reviewer,
      reviewed_at = now() WHERE id = v_qversion;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%does not match%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a mismatched option_count was approved'; END IF;
  UPDATE question_versions SET option_count = 4 WHERE id = v_qversion;

  -- An author cannot approve their own question.
  v_rejected := false;
  BEGIN
    UPDATE question_versions SET review_status = 'approved', reviewed_by = v_author,
      reviewed_at = now() WHERE id = v_qversion;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an author approved their own question'; END IF;

  UPDATE question_versions SET review_status = 'approved', reviewed_by = v_reviewer,
    reviewed_at = now() WHERE id = v_qversion;
  UPDATE questions SET current_version_id = v_qversion WHERE id = v_question;

  -- Approved content and its options are frozen.
  v_rejected := false;
  BEGIN
    UPDATE question_versions SET stem = 'Solve 2x + 5 = 19.' WHERE id = v_qversion;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%immutable%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'approved question content was editable'; END IF;

  v_rejected := false;
  BEGIN
    UPDATE question_options SET body = 'x = 7'
      WHERE question_version_id = v_qversion AND option_key = 'A';
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%immutable%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'options of an approved question were editable'; END IF;

  -- --------------------------------------------------------- classification
  -- A subtopic is not a skill.
  v_rejected := false;
  BEGIN
    INSERT INTO question_classifications(question_id, subject_id, curriculum_item_id,
      syllabus_version_id, classification_role, classification_reason)
      VALUES (v_question, v_subject, v_subtopic, v_syllabus_version, 'primary',
        'Wrongly mapped to a subtopic.');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates foreign key constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a question was classified against a subtopic'; END IF;

  -- A level defined for another skill cannot be borrowed.
  v_rejected := false;
  BEGIN
    INSERT INTO question_classifications(question_id, subject_id, curriculum_item_id,
      syllabus_version_id, mastery_level_id, classification_role, classification_reason)
      VALUES (v_question, v_subject, v_skill_a, v_syllabus_version, v_level_b, 'primary',
        'Level borrowed from another skill.');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates foreign key constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a level from another skill was accepted'; END IF;

  INSERT INTO question_classifications(question_id, subject_id, curriculum_item_id,
    syllabus_version_id, mastery_level_id, classification_role, classification_reason,
    review_status, reviewed_by, reviewed_at)
    VALUES (v_question, v_subject, v_skill_a, v_syllabus_version, v_level_a, 'primary',
      'Tests solving a linear equation in one variable.', 'approved', v_reviewer, now());

  -- Only one approved primary per question.
  v_rejected := false;
  BEGIN
    INSERT INTO question_classifications(question_id, subject_id, curriculum_item_id,
      syllabus_version_id, mastery_level_id, classification_role, classification_reason,
      review_status, reviewed_by, reviewed_at)
      VALUES (v_question, v_subject, v_skill_b, v_syllabus_version, v_level_b, 'primary',
        'A second primary mapping.', 'approved', v_reviewer, now());
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%duplicate key%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN
    RAISE EXCEPTION 'a second approved primary classification was accepted';
  END IF;

  INSERT INTO question_classifications(question_id, subject_id, curriculum_item_id,
    syllabus_version_id, mastery_level_id, classification_role, classification_reason,
    review_status, reviewed_by, reviewed_at)
    VALUES (v_question, v_subject, v_skill_b, v_syllabus_version, v_level_b, 'secondary',
      'Also requires accurate arithmetic.', 'approved', v_reviewer, now());

  -- -------------------------------------------------------------- the pools
  INSERT INTO questions(subject_id, exam_paper_id, origin, usage_pool, created_by)
    VALUES (v_subject, v_paper, 'authored', 'held_out', v_author) RETURNING id INTO v_held_out;
  INSERT INTO question_versions(question_id, subject_id, version, stem, response_format,
    marking_method, solution_steps, hints, marks, expected_seconds, mastery_level_number,
    option_count, content_hash, authored_by, answer_source, level_source)
    VALUES (v_held_out, v_subject, 1, 'Solve 3x = 18.', 'mcq_single', 'auto_key',
      '["Divide both sides by 3", "x = 6"]'::jsonb, '["Undo the multiplication."]'::jsonb,
      2, 60, 3, 4, repeat('2', 64), v_author, 'expert_verified', 'expert_verified')
    RETURNING id INTO v_held_out_version;
  INSERT INTO question_options(question_version_id, subject_id, option_key, body,
    is_correct, display_order)
    VALUES (v_held_out_version, v_subject, 'A', 'x = 6', true, 1);
  INSERT INTO question_options(question_version_id, subject_id, option_key, body, display_order)
    VALUES (v_held_out_version, v_subject, 'B', 'x = 15', 2),
           (v_held_out_version, v_subject, 'C', 'x = 21', 3),
           (v_held_out_version, v_subject, 'D', 'x = 54', 4);
  UPDATE question_versions SET review_status = 'approved', reviewed_by = v_reviewer,
    reviewed_at = now() WHERE id = v_held_out_version;
  UPDATE questions SET current_version_id = v_held_out_version WHERE id = v_held_out;
  INSERT INTO question_classifications(question_id, subject_id, curriculum_item_id,
    syllabus_version_id, mastery_level_id, classification_role, classification_reason,
    review_status, reviewed_by, reviewed_at)
    VALUES (v_held_out, v_subject, v_skill_a, v_syllabus_version, v_level_a, 'primary',
      'Held-out measurement item for the same skill.', 'approved', v_reviewer, now());

  -- A generated question may never sit in a measuring pool.
  v_rejected := false;
  BEGIN
    INSERT INTO questions(subject_id, origin, generation_profile_id, usage_pool, created_by)
      VALUES (v_subject, 'generated', gen_random_uuid(), 'held_out', v_author);
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a generated question entered the held-out pool'; END IF;

  -- A past question without a source document is impossible.
  v_rejected := false;
  BEGIN
    INSERT INTO questions(subject_id, origin, usage_pool, created_by)
      VALUES (v_subject, 'past_paper', 'practice', v_author);
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'a past question without a source was accepted'; END IF;

  -- --------------------------------------------------------------- delivery
  IF (SELECT count(*) FROM deliverable_questions) <> 2 THEN
    RAISE EXCEPTION 'expected two deliverable questions';
  END IF;
  IF (SELECT count(*) FROM adaptive_practice_questions) <> 1 THEN
    RAISE EXCEPTION 'the held-out question must not be available to adaptive practice';
  END IF;
  IF (SELECT option_count FROM deliverable_questions WHERE question_id = v_question) <> 4 THEN
    RAISE EXCEPTION 'the engine cannot read the option count';
  END IF;
  IF (SELECT count(*) FROM candidate_question_options
        WHERE question_version_id = v_qversion) <> 4 THEN
    RAISE EXCEPTION 'the candidate cannot see the four options';
  END IF;

  -- The candidate payload must not leak the answer.
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'stackprep'
      AND table_name IN ('candidate_question_payload', 'candidate_question_options')
      AND column_name IN ('is_correct', 'solution_steps', 'marking_scheme',
                          'numeric_answer', 'accepted_answers', 'misconception_id')
  ) THEN
    RAISE EXCEPTION 'the candidate payload exposes answer data';
  END IF;

  -- A non-objective item is stored but stays out of adaptive practice.
  INSERT INTO questions(subject_id, exam_paper_id, origin, usage_pool, created_by)
    VALUES (v_subject, v_paper, 'authored', 'practice', v_author)
    RETURNING id INTO v_essay_question;
  INSERT INTO question_versions(question_id, subject_id, version, stem, response_format,
    marking_method, solution_steps, hints, marks, expected_seconds, mastery_level_number,
    content_hash, authored_by)
    VALUES (v_essay_question, v_subject, 1, 'Explain why the equation has one solution.',
      'essay', 'human', '["Discuss the degree of the equation."]'::jsonb,
      '["How many times can a straight line cross the axis?"]'::jsonb,
      5, 300, 4, repeat('3', 64), v_author);
  IF (SELECT adaptive_eligible FROM question_versions
        WHERE question_id = v_essay_question) THEN
    RAISE EXCEPTION 'a human-marked question was marked adaptive';
  END IF;

  -- Withdrawing delivery rights removes the past question from delivery at once.
  UPDATE source_documents SET student_delivery_permission = false WHERE id = v_paper_doc;
  IF EXISTS (SELECT 1 FROM deliverable_questions WHERE question_id = v_question) THEN
    RAISE EXCEPTION 'a question stayed deliverable after its source lost delivery rights';
  END IF;
END $$;

ROLLBACK;
