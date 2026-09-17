-- Run after 012_asset_provenance.sql in a disposable PostgreSQL database.
-- Local variables are prefixed v_ so they never collide with column names.
BEGIN;
SET LOCAL search_path = stackprep, public;

DO $$
DECLARE
  v_author uuid;
  v_reviewer uuid;
  v_exam uuid;
  v_subject uuid;
  v_question uuid;
  v_version uuid;
  v_asset uuid;
  v_rejected boolean;
  v_message text;
BEGIN
  INSERT INTO academic_reviewers(display_name) VALUES ('Figure author') RETURNING id INTO v_author;
  INSERT INTO academic_reviewers(display_name) VALUES ('Figure reviewer') RETURNING id INTO v_reviewer;
  INSERT INTO examinations(name, short_name, exam_body, country_code, status)
    VALUES ('Figure exam', 'TESTFIG', 'Test body', 'NG', 'active') RETURNING id INTO v_exam;
  INSERT INTO subjects(examination_id, code, name, status)
    VALUES (v_exam, 'MATH', 'Mathematics', 'active') RETURNING id INTO v_subject;
  INSERT INTO questions(subject_id, origin, usage_pool, created_by)
    VALUES (v_subject, 'authored', 'practice', v_author) RETURNING id INTO v_question;

  -- Everything approval needs, so the only open question is the figure.
  INSERT INTO question_versions(question_id, subject_id, version, stem, response_format,
    marking_method, solution_steps, hints, marks, expected_seconds, option_count,
    content_hash, authored_by, answer_source, mastery_level_number, level_source)
    VALUES (v_question, v_subject, 1, 'Find the value of x in the diagram.', 'mcq_single',
      'auto_key', '["angles on a straight line sum to 180"]'::jsonb, '["what do the angles sum to?"]'::jsonb,
      1, 60, 4, repeat('a', 64), v_author, 'expert_verified', 3, 'expert_verified')
    RETURNING id INTO v_version;
  INSERT INTO question_options(question_version_id, subject_id, option_key, body, is_correct, display_order)
    VALUES (v_version, v_subject, 'A', '30', true, 1);
  INSERT INTO question_options(question_version_id, subject_id, option_key, body, display_order)
    VALUES (v_version, v_subject, 'B', '45', 2);
  INSERT INTO question_options(question_version_id, subject_id, option_key, body, display_order)
    VALUES (v_version, v_subject, 'C', '60', 3);
  INSERT INTO question_options(question_version_id, subject_id, option_key, body, display_order)
    VALUES (v_version, v_subject, 'D', '90', 4);

  -- A crop straight out of the converter: described by machine, licence not yet cleared.
  INSERT INTO question_assets(question_version_id, storage_uri, mime_type, width, height,
    alt_text, alt_text_source, source_location, licence_status)
    VALUES (v_version, 'docs/questions/utme/mathematics/figures/abc.png', 'image/png',
      400, 300, 'Triangle labelled x, 60 and 80 degrees.', 'model_proposed',
      'PDF page 51, crop (330,225)-(580,335)pt', 'pending')
    RETURNING id INTO v_asset;

  -- Licence first: the older guard still does its job.
  v_rejected := false;
  BEGIN
    UPDATE question_versions SET review_status = 'approved', reviewed_by = v_reviewer,
      reviewed_at = now() WHERE id = v_version;
  EXCEPTION WHEN OTHERS THEN
    v_message := SQLERRM; v_rejected := true;
  END;
  IF NOT v_rejected THEN
    RAISE EXCEPTION 'a question with an unlicensed figure was approved';
  END IF;

  -- With the licence cleared, a machine-written description must still not be enough.
  UPDATE question_assets SET licence_status = 'verified' WHERE id = v_asset;
  v_rejected := false;
  BEGIN
    UPDATE question_versions SET review_status = 'approved', reviewed_by = v_reviewer,
      reviewed_at = now() WHERE id = v_version;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%alt text a person has confirmed%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN
    RAISE EXCEPTION 'a proposed figure description was accepted as if a person had checked it';
  END IF;

  -- Once a person has confirmed the description, approval goes through.
  UPDATE question_assets SET alt_text_source = 'expert_verified' WHERE id = v_asset;
  UPDATE question_versions SET review_status = 'approved', reviewed_by = v_reviewer,
    reviewed_at = now() WHERE id = v_version;
  IF (SELECT review_status FROM question_versions WHERE id = v_version) <> 'approved' THEN
    RAISE EXCEPTION 'a verified figure description did not allow approval';
  END IF;

  -- An invented provenance is refused.
  v_rejected := false;
  BEGIN
    UPDATE question_assets SET alt_text_source = 'looked_about_right' WHERE id = v_asset;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%violates check constraint%' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'an unknown alt_text_source was accepted'; END IF;
END $$;

ROLLBACK;
