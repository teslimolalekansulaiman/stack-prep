-- Run after 001_curriculum.sql in a disposable PostgreSQL database.
BEGIN;
SET LOCAL search_path = stackprep, public;

DO $$
DECLARE
  reviewer_id uuid;
  exam_id uuid;
  subject_id uuid;
  document_id uuid;
  version_id uuid;
  topic_id uuid;
  subtopic_id uuid;
  skill_a uuid;
  skill_b uuid;
  excluded_id uuid;
  boundary_evidence_id uuid;
  second_version_id uuid;
  rejected boolean;
BEGIN
  INSERT INTO academic_reviewers(display_name) VALUES ('Test reviewer') RETURNING id INTO reviewer_id;
  INSERT INTO examinations(name, short_name, exam_body, country_code, status)
    VALUES ('Synthetic test exam', 'TEST', 'Test body', 'NG', 'active') RETURNING id INTO exam_id;
  INSERT INTO subjects(examination_id, code, name, status)
    VALUES (exam_id, 'MATH', 'Mathematics', 'active') RETURNING id INTO subject_id;
  INSERT INTO source_documents(examination_id, subject_id, document_type, title,
    file_uri, file_sha256, mime_type, licence_status, storage_permission,
    student_delivery_permission, review_status, reviewed_by, reviewed_at)
    VALUES (exam_id, subject_id, 'syllabus', 'Synthetic syllabus', 'test://syllabus',
      repeat('a', 64), 'application/pdf', 'verified', true, true,
      'approved', reviewer_id, now())
    RETURNING id INTO document_id;
  INSERT INTO syllabus_versions(subject_id, version_label, source_document_id,
    status, is_current, approved_by, approved_at)
    VALUES (subject_id, 'test-v1', document_id, 'approved', true, reviewer_id, now())
    RETURNING id INTO version_id;

  INSERT INTO curriculum_items(syllabus_version_id, subject_id, item_type, code,
    name, syllabus_status, pilot_support_status)
    VALUES (version_id, subject_id, 'topic', 'ALG', 'Algebra', 'explicit', 'supported')
    RETURNING id INTO topic_id;
  INSERT INTO curriculum_evidence(curriculum_item_id, source_document_id,
    evidence_kind, source_location, review_status, reviewed_by, reviewed_at)
    VALUES (topic_id, document_id, 'inclusion', 'page 1', 'approved', reviewer_id, now());
  UPDATE curriculum_items SET review_status = 'approved', approved_by = reviewer_id,
    approved_at = now() WHERE id = topic_id;

  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type,
    code, name, syllabus_status, pilot_support_status)
    VALUES (version_id, subject_id, topic_id, 'subtopic', 'ALG.EQ', 'Equations',
      'explicit', 'supported') RETURNING id INTO subtopic_id;
  INSERT INTO curriculum_evidence(curriculum_item_id, source_document_id,
    evidence_kind, source_location, review_status, reviewed_by, reviewed_at)
    VALUES (subtopic_id, document_id, 'inclusion', 'page 2', 'approved', reviewer_id, now());
  UPDATE curriculum_items SET review_status = 'approved', approved_by = reviewer_id,
    approved_at = now() WHERE id = subtopic_id;

  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type,
    code, name, syllabus_status, pilot_support_status)
    VALUES (version_id, subject_id, subtopic_id, 'skill', 'ALG.EQ.S1', 'Form equations',
      'explicit', 'supported') RETURNING id INTO skill_a;
  INSERT INTO curriculum_evidence(curriculum_item_id, source_document_id,
    evidence_kind, source_location, review_status, reviewed_by, reviewed_at)
    VALUES (skill_a, document_id, 'inclusion', 'page 2', 'approved', reviewer_id, now());
  UPDATE curriculum_items SET review_status = 'approved', approved_by = reviewer_id,
    approved_at = now() WHERE id = skill_a;

  INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id, item_type,
    code, name, syllabus_status, pilot_support_status)
    VALUES (version_id, subject_id, subtopic_id, 'skill', 'ALG.EQ.S2', 'Solve equations',
      'explicit', 'supported') RETURNING id INTO skill_b;
  INSERT INTO curriculum_evidence(curriculum_item_id, source_document_id,
    evidence_kind, source_location, review_status, reviewed_by, reviewed_at)
    VALUES (skill_b, document_id, 'inclusion', 'page 2', 'approved', reviewer_id, now());
  UPDATE curriculum_items SET review_status = 'approved', approved_by = reviewer_id,
    approved_at = now() WHERE id = skill_b;

  INSERT INTO curriculum_mastery_levels(curriculum_item_id, level_number, name,
    description, review_status, reviewed_by, reviewed_at)
    VALUES (skill_a, 1, 'Foundation', 'Forms a simple equation.', 'approved', reviewer_id, now());
  INSERT INTO curriculum_prerequisites(curriculum_item_id, prerequisite_item_id,
    strength, reason, review_status, reviewed_by, reviewed_at)
    VALUES (skill_b, skill_a, 'required', 'Form before solving.', 'approved', reviewer_id, now());

  rejected := false;
  BEGIN
    INSERT INTO curriculum_prerequisites(curriculum_item_id, prerequisite_item_id,
      strength, reason, review_status, reviewed_by, reviewed_at)
      VALUES (skill_a, skill_b, 'required', 'Would form a cycle.', 'approved', reviewer_id, now());
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%cycle%' THEN RAISE; END IF;
    rejected := true;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'required cycle was accepted'; END IF;

  INSERT INTO curriculum_items(syllabus_version_id, subject_id, item_type, code,
    name, syllabus_status)
    VALUES (version_id, subject_id, 'topic', 'OUT', 'Excluded test topic', 'excluded')
    RETURNING id INTO excluded_id;
  INSERT INTO curriculum_evidence(curriculum_item_id, source_document_id,
    evidence_kind, source_location, review_status, reviewed_by, reviewed_at)
    VALUES (excluded_id, document_id, 'inclusion', 'page 1', 'approved', reviewer_id, now());
  rejected := false;
  BEGIN
    UPDATE curriculum_items SET review_status = 'approved', approved_by = reviewer_id,
      approved_at = now() WHERE id = excluded_id;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%exclusion requires%' THEN RAISE; END IF;
    rejected := true;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'exclusion without boundary evidence was accepted'; END IF;
  INSERT INTO curriculum_evidence(curriculum_item_id, evidence_kind,
    decision_rationale, decision_evidence_reference, review_status, reviewed_by, reviewed_at)
    VALUES (excluded_id, 'academic_boundary', 'Reviewed boundary decision for test.',
      'test-boundary-record-001', 'approved', reviewer_id, now())
    RETURNING id INTO boundary_evidence_id;
  UPDATE curriculum_items SET review_status = 'approved', approved_by = reviewer_id,
    approved_at = now() WHERE id = excluded_id;
  rejected := false;
  BEGIN
    UPDATE curriculum_evidence SET decision_rationale = 'Silently changed'
      WHERE id = boundary_evidence_id;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%immutable%' THEN RAISE; END IF;
    rejected := true;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'approved evidence was editable'; END IF;

  INSERT INTO syllabus_versions(subject_id, version_label, source_document_id)
    VALUES (subject_id, 'test-v2', document_id) RETURNING id INTO second_version_id;
  rejected := false;
  BEGIN
    UPDATE syllabus_versions SET status = 'approved', approved_by = reviewer_id,
      approved_at = now() WHERE id = second_version_id;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%overlap%' THEN RAISE; END IF;
    rejected := true;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'overlapping syllabus version was approved'; END IF;
  rejected := false;
  BEGIN
    INSERT INTO curriculum_items(syllabus_version_id, subject_id, parent_id,
      item_type, code, name)
      VALUES (second_version_id, subject_id, topic_id, 'subtopic', 'BAD', 'Cross-version child');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%same syllabus version%' THEN RAISE; END IF;
    rejected := true;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'cross-version parent was accepted'; END IF;

  IF (SELECT count(*) FROM teachable_skills) <> 2 THEN
    RAISE EXCEPTION 'expected two published teachable skills';
  END IF;
  IF (SELECT count(*) FROM published_curriculum_scope WHERE syllabus_status = 'excluded') <> 1 THEN
    RAISE EXCEPTION 'expected one visible reviewed exclusion';
  END IF;
  UPDATE source_documents SET student_delivery_permission = false WHERE id = document_id;
  IF EXISTS (SELECT 1 FROM published_curriculum_scope) THEN
    RAISE EXCEPTION 'content remained published after delivery permission was removed';
  END IF;
END $$;

ROLLBACK;
