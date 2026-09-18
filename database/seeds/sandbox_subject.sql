-- A complete, deliverable subject, written by us, for building and testing the student side.
--
-- WHY THIS EXISTS. A question reaches a student only after passing six gates: its version
-- approved, its classification approved, its skill teachable (which needs an approved
-- syllabus from a licence-cleared document), its source licensed for delivery, its pool
-- correct, and its topic carrying an approved exam weight. The real bank passes none of them
-- yet — 0 of 1,860 questions are approved — so the check-up screen would have nothing to
-- render and nothing to adapt to.
--
-- This fixture passes all six honestly rather than bypassing any. The content is ours, so
-- the licence really is clear; the reviewer is a fixture account, so the approvals really
-- were made by someone identifiable; the questions really do have worked solutions, hints,
-- levels and verified answers, because that is what approval requires. Nothing here weakens
-- a rule — it satisfies the rules with material we own.
--
-- It is deliberately obvious: the examination is called SANDBOX and the subject "Sandbox
-- Numeracy". No real student should ever see it, and no real question is mixed into it.
--
-- Safe to re-run: every id is derived from md5 of a fixed key, and every insert is
-- ON CONFLICT DO NOTHING.
BEGIN;
SET LOCAL search_path = stackprep, public;

-- Two accounts, because the schema enforces four eyes: a question's reviewer may not be
-- its author. The fixture respects that rather than working around it.
INSERT INTO academic_reviewers (id, display_name, active)
VALUES (md5('sandbox:author')::uuid, 'Sandbox fixture author', true),
       (md5('sandbox:reviewer')::uuid, 'Sandbox fixture reviewer', true)
ON CONFLICT (id) DO NOTHING;

INSERT INTO examinations (id, name, short_name, exam_body, country_code, description, status)
VALUES (md5('sandbox:exam')::uuid, 'Sandbox Examination', 'SANDBOX', 'Score Pilot', 'NG',
        'A fixture examination for building and testing. Not a real examination.', 'active')
ON CONFLICT (id) DO NOTHING;

INSERT INTO subjects (id, examination_id, code, name, status)
VALUES (md5('sandbox:subject')::uuid, md5('sandbox:exam')::uuid, 'SBXNUM',
        'Sandbox Numeracy', 'active')
ON CONFLICT (id) DO NOTHING;

-- We wrote this "document", so its rights genuinely are ours to grant.
INSERT INTO source_documents (id, examination_id, subject_id, document_type, title, issuer,
  file_uri, file_sha256, mime_type, page_count, licence_status, storage_permission,
  student_delivery_permission, model_context_permission, processing_status, review_status,
  reviewed_by, reviewed_at)
VALUES (md5('sandbox:doc')::uuid, md5('sandbox:exam')::uuid, md5('sandbox:subject')::uuid,
        'syllabus', 'Sandbox Numeracy syllabus', 'Score Pilot',
        'database/seeds/sandbox_subject.sql', md5('sandbox:doc-content')::text || md5('sandbox:doc-content')::text,
        'text/plain', 1, 'verified', true, true, true, 'processed', 'approved',
        md5('sandbox:reviewer')::uuid, now())
ON CONFLICT (id) DO NOTHING;

INSERT INTO syllabus_versions (id, subject_id, version_label, source_document_id, status,
  is_current, approved_by, approved_at)
VALUES (md5('sandbox:version')::uuid, md5('sandbox:subject')::uuid, 'sandbox-v1',
        md5('sandbox:doc')::uuid, 'approved', true, md5('sandbox:reviewer')::uuid, now())
ON CONFLICT (id) DO NOTHING;

-- ── curriculum: three topics, each with one subtopic and two skills ──────────────────
INSERT INTO curriculum_items (id, syllabus_version_id, subject_id, parent_id, item_type, code,
  name, syllabus_status, pilot_support_status, display_order, review_status, approved_by,
  approved_at)
SELECT md5('sandbox:item:' || item.code)::uuid, md5('sandbox:version')::uuid,
       md5('sandbox:subject')::uuid,
       CASE WHEN item.parent IS NULL THEN NULL
            ELSE md5('sandbox:item:' || item.parent)::uuid END,
       -- Draft first: the guard refuses to approve an item that has no reviewed evidence
       -- yet, and the evidence rows are inserted below. Approval happens last, as it does
       -- for questions.
       item.kind, item.code, item.name, 'explicit', 'supported', item.ord, 'draft',
       NULL, NULL
FROM (VALUES
  ('SBX.N',     NULL,        'topic',    'Number',                        1),
  ('SBX.A',     NULL,        'topic',    'Algebra',                       2),
  ('SBX.D',     NULL,        'topic',    'Data',                          3),
  ('SBX.N.1',   'SBX.N',     'subtopic', 'Whole numbers and fractions',   1),
  ('SBX.A.1',   'SBX.A',     'subtopic', 'Expressions and equations',     1),
  ('SBX.D.1',   'SBX.D',     'subtopic', 'Averages and charts',           1),
  ('SBX.N.1.i', 'SBX.N.1',   'skill',    'Calculate with whole numbers',  1),
  ('SBX.N.1.ii','SBX.N.1',   'skill',    'Calculate with fractions',      2),
  ('SBX.A.1.i', 'SBX.A.1',   'skill',    'Simplify an expression',        1),
  ('SBX.A.1.ii','SBX.A.1',   'skill',    'Solve a linear equation',       2),
  ('SBX.D.1.i', 'SBX.D.1',   'skill',    'Find an average',               1),
  ('SBX.D.1.ii','SBX.D.1',   'skill',    'Read a chart',                  2)
) AS item(code, parent, kind, name, ord)
ORDER BY CASE item.kind WHEN 'topic' THEN 1 WHEN 'subtopic' THEN 2 ELSE 3 END
ON CONFLICT (id) DO NOTHING;

INSERT INTO curriculum_evidence (id, curriculum_item_id, source_document_id, evidence_kind,
  source_location, source_excerpt, review_status, reviewed_by, reviewed_at)
SELECT md5('sandbox:evidence:' || c.code)::uuid, c.id, md5('sandbox:doc')::uuid, 'inclusion',
       'Sandbox fixture', 'Written for the fixture; not extracted from any paper.',
       'approved', md5('sandbox:reviewer')::uuid, now()
FROM curriculum_items c
WHERE c.syllabus_version_id = md5('sandbox:version')::uuid
ON CONFLICT (id) DO NOTHING;

-- Now that every item has reviewed evidence behind it, the items can be approved. Parents
-- go first: the guard also refuses to approve a child whose parent is still a draft.
UPDATE curriculum_items SET review_status = 'approved',
       approved_by = md5('sandbox:reviewer')::uuid, approved_at = now()
 WHERE syllabus_version_id = md5('sandbox:version')::uuid AND item_type = 'topic';
UPDATE curriculum_items SET review_status = 'approved',
       approved_by = md5('sandbox:reviewer')::uuid, approved_at = now()
 WHERE syllabus_version_id = md5('sandbox:version')::uuid AND item_type = 'subtopic';
UPDATE curriculum_items SET review_status = 'approved',
       approved_by = md5('sandbox:reviewer')::uuid, approved_at = now()
 WHERE syllabus_version_id = md5('sandbox:version')::uuid AND item_type = 'skill';

-- ── the paper, so the topics carry real weights (Number 50%, Algebra 30%, Data 20%) ──
INSERT INTO exam_papers (id, subject_id, paper_code, name, response_mode, question_count,
  duration_minutes, options_per_question, score_out_of, values_confirmed, confirmation_note,
  pilot_support_status, status)
VALUES (md5('sandbox:paper')::uuid, md5('sandbox:subject')::uuid, 'SBX-P1',
        'Sandbox paper 1', 'objective', 40, 30, 4, 40, true,
        'Defined by this fixture, which is the whole of the sandbox examination.',
        'supported', 'active')
ON CONFLICT (id) DO NOTHING;

INSERT INTO exam_paper_sections (id, exam_paper_id, subject_id, section_code, name,
  question_count, marks_total, topic_id, syllabus_version_id, source_location, review_status,
  reviewed_by, reviewed_at)
SELECT md5('sandbox:section:' || s.code)::uuid, md5('sandbox:paper')::uuid,
       md5('sandbox:subject')::uuid, s.code, s.name, s.questions, s.questions,
       md5('sandbox:item:' || s.topic)::uuid, md5('sandbox:version')::uuid,
       'Sandbox fixture', 'approved', md5('sandbox:reviewer')::uuid, now()
FROM (VALUES
  ('SBX-NUMBER',  'Number',  20, 'SBX.N'),
  ('SBX-ALGEBRA', 'Algebra', 12, 'SBX.A'),
  ('SBX-DATA',    'Data',     8, 'SBX.D')
) AS s(code, name, questions, topic)
ON CONFLICT (id) DO NOTHING;

-- ── the questions ────────────────────────────────────────────────────────────────────
-- Levels run 1 (easy) to 5 (hard) so the check-up's ladder has somewhere to go in every
-- topic: a student who gets one right is offered a harder one, and the screen can be seen
-- doing it. Every question is genuinely answerable from its own text.
DO $$
DECLARE
  item record;
  v_question uuid;
  v_version uuid;
  v_skill uuid;
BEGIN
  FOR item IN
    SELECT * FROM (VALUES
      -- key,  skill,          level, stem, A, B, C, D, correct, solution, hint
      ('n1', 'SBX.N.1.i',  1, 'What is 7 + 6?', '12', '13', '14', '15', 'B',
       '7 + 6 = 13.', 'Count on six from seven.'),
      ('n2', 'SBX.N.1.i',  1, 'What is 9 x 4?', '32', '34', '36', '38', 'C',
       '9 x 4 = 36.', 'Four nines: 9, 18, 27, 36.'),
      ('n3', 'SBX.N.1.i',  2, 'What is 144 divided by 12?', '11', '12', '13', '14', 'B',
       '12 x 12 = 144, so the answer is 12.', 'Which number times twelve gives 144?'),
      ('n4', 'SBX.N.1.i',  3, 'A shirt costs 2,400 naira after a 20% discount. What was the original price?',
       '2,880', '3,000', '2,700', '3,200', 'B',
       '2400 is 80% of the original, so the original is 2400/0.8 = 3000.',
       'The price paid is 80% of the original.'),
      ('n5', 'SBX.N.1.ii', 2, 'What is 1/2 + 1/4?', '1/6', '2/6', '3/4', '1/8', 'C',
       'A common denominator of 4 gives 2/4 + 1/4 = 3/4.', 'Write both halves in quarters.'),
      ('n6', 'SBX.N.1.ii', 3, 'What is 2/3 of 45?', '15', '20', '30', '35', 'C',
       '45/3 = 15, and 2 x 15 = 30.', 'Find one third first.'),
      ('n7', 'SBX.N.1.ii', 4, 'Simplify (3/4) divided by (2/3).', '1/2', '9/8', '8/9', '6/12', 'B',
       'Dividing by a fraction multiplies by its reciprocal: (3/4)(3/2) = 9/8.',
       'Turn the second fraction upside down and multiply.'),
      ('n8', 'SBX.N.1.ii', 5, 'A tank is 3/8 full. After 120 litres are added it is 3/4 full. What is its capacity?',
       '240 litres', '320 litres', '360 litres', '480 litres', 'B',
       '3/4 - 3/8 = 3/8 of the tank is 120 litres, so the tank is 120 x 8/3 = 320 litres.',
       'What fraction of the tank did the 120 litres fill?'),
      ('a1', 'SBX.A.1.i',  1, 'Simplify 3x + 5x.', '8', '8x', '15x', '2x', 'B',
       'Like terms add: 3x + 5x = 8x.', 'Both terms are lots of x.'),
      ('a2', 'SBX.A.1.i',  2, 'Simplify 4(a + 3) - 2a.', '2a + 3', '2a + 12', '6a + 12', '2a + 7', 'B',
       'Expanding gives 4a + 12 - 2a = 2a + 12.', 'Multiply out the bracket first.'),
      ('a3', 'SBX.A.1.i',  4, 'Factorise x^2 - 9.', '(x-3)(x-3)', '(x+3)(x+3)', '(x-3)(x+3)', 'x(x-9)', 'C',
       'A difference of two squares: x^2 - 9 = (x-3)(x+3).', 'Both terms are perfect squares.'),
      ('a4', 'SBX.A.1.ii', 2, 'Solve 2x + 5 = 13.', 'x = 3', 'x = 4', 'x = 5', 'x = 9', 'B',
       '2x = 8, so x = 4.', 'Take five from both sides.'),
      ('a5', 'SBX.A.1.ii', 3, 'Solve 5x - 3 = 2x + 9.', 'x = 2', 'x = 3', 'x = 4', 'x = 6', 'C',
       '3x = 12, so x = 4.', 'Gather the x terms on one side.'),
      ('a6', 'SBX.A.1.ii', 4, 'Solve x/3 + 2 = 7.', 'x = 5', 'x = 12', 'x = 15', 'x = 21', 'C',
       'x/3 = 5, so x = 15.', 'Undo the +2 before the division.'),
      ('a7', 'SBX.A.1.ii', 5, 'If 3(y - 2) = 2(y + 4), find y.', 'y = 2', 'y = 10', 'y = 14', 'y = 6', 'C',
       '3y - 6 = 2y + 8, so y = 14.', 'Expand both brackets, then collect y.'),
      ('a8', 'SBX.A.1.i',  3, 'Simplify (2x^3)(3x^2).', '5x^5', '6x^5', '6x^6', '5x^6', 'B',
       'Multiply the numbers and add the indices: 6x^5.', 'Indices add when powers multiply.'),
      ('d1', 'SBX.D.1.i',  1, 'What is the mean of 4, 6 and 8?', '5', '6', '7', '18', 'B',
       'The three values total 18, and 18/3 = 6.', 'Add them, then divide by how many.'),
      ('d2', 'SBX.D.1.i',  2, 'What is the median of 3, 9, 4, 7 and 5?', '4', '5', '6', '7', 'B',
       'In order: 3, 4, 5, 7, 9. The middle value is 5.', 'Put them in order first.'),
      ('d3', 'SBX.D.1.i',  3, 'The mean of five numbers is 12. Four of them are 10, 11, 13 and 14. What is the fifth?',
       '10', '11', '12', '14', 'C',
       'The five total 60; the four given total 48; so the fifth is 12.',
       'What must all five add up to?'),
      ('d4', 'SBX.D.1.i',  5, 'The mean of six numbers is 15. Removing one leaves a mean of 16. What was removed?',
       '6', '9', '10', '15', 'C',
       'Six numbers total 90; the remaining five total 80; so 10 was removed.',
       'Compare the two totals, not the two means.'),
      ('d5', 'SBX.D.1.ii', 2, 'A pie chart has four equal sectors. What angle does each take?',
       '45 degrees', '60 degrees', '90 degrees', '120 degrees', 'C',
       '360/4 = 90 degrees.', 'A full circle is 360 degrees.'),
      ('d6', 'SBX.D.1.ii', 3, 'In a pie chart of 200 students, a sector of 72 degrees represents how many students?',
       '20', '40', '50', '72', 'B',
       '72/360 = 1/5, and one fifth of 200 is 40.', 'What fraction of the circle is 72 degrees?'),
      ('d7', 'SBX.D.1.ii', 4, 'A bar chart shows 8, 5, 11 and 4 books read in four weeks. What is the range?',
       '4', '5', '7', '11', 'C',
       '11 - 4 = 7.', 'The range is the largest minus the smallest.'),
      ('d8', 'SBX.D.1.i',  4, 'Five scores have a mean of 20 and a range of 8. The lowest is 16. What is the highest?',
       '20', '22', '24', '28', 'C',
       'The range is highest minus lowest: 16 + 8 = 24.', 'The mean is not needed here.')
    ) AS t(key, skill, level, stem, a, b, c, d, correct, solution, hint)
  LOOP
    v_question := md5('sandbox:question:' || item.key)::uuid;
    v_version := md5('sandbox:version:' || item.key)::uuid;
    v_skill := md5('sandbox:item:' || item.skill)::uuid;

    INSERT INTO questions (id, subject_id, origin, usage_pool, created_by)
    VALUES (v_question, md5('sandbox:subject')::uuid, 'authored', 'diagnostic',
            md5('sandbox:author')::uuid)
    ON CONFLICT (id) DO NOTHING;

    INSERT INTO question_versions (id, question_id, subject_id, version, stem, response_format,
      marking_method, solution_steps, hints, marks, expected_seconds, option_count,
      mastery_level_number, content_hash, authored_by, answer_source, answer_confidence,
      level_source, review_status, reviewed_by, reviewed_at)
    VALUES (v_version, v_question, md5('sandbox:subject')::uuid, 1, item.stem, 'mcq_single',
            'auto_key', jsonb_build_array(item.solution), jsonb_build_array(item.hint),
            1, 60, 4, item.level,
            md5('sandbox:hash:' || item.key)::text || md5('sandbox:hash2:' || item.key)::text,
            md5('sandbox:author')::uuid, 'expert_verified', 'high', 'expert_verified',
            'draft', NULL, NULL)
    ON CONFLICT (id) DO NOTHING;

    INSERT INTO question_options (id, question_version_id, subject_id, option_key, body,
      is_correct, display_order)
    SELECT md5('sandbox:option:' || item.key || ':' || o.key)::uuid, v_version,
           md5('sandbox:subject')::uuid, o.key, o.body, o.key = item.correct, o.ord
    FROM (VALUES ('A', item.a, 1), ('B', item.b, 2), ('C', item.c, 3), ('D', item.d, 4))
         AS o(key, body, ord)
    ON CONFLICT (id) DO NOTHING;

    -- Approval comes last: the trigger checks the options, so they must exist first.
    UPDATE question_versions
       SET review_status = 'approved', reviewed_by = md5('sandbox:reviewer')::uuid,
           reviewed_at = now()
     WHERE id = v_version AND review_status = 'draft';

    UPDATE questions SET current_version_id = v_version WHERE id = v_question;

    INSERT INTO question_classifications (id, question_id, subject_id, curriculum_item_id,
      syllabus_version_id, classification_role, proposed_by, confidence, classification_reason,
      review_status, reviewed_by, reviewed_at)
    VALUES (md5('sandbox:class:' || item.key)::uuid, v_question, md5('sandbox:subject')::uuid,
            v_skill, md5('sandbox:version')::uuid, 'primary', 'human', 1.0,
            'Written for this skill.', 'approved', md5('sandbox:reviewer')::uuid, now())
    ON CONFLICT (id) DO NOTHING;
  END LOOP;
END $$;

COMMIT;
