-- Let a printed section say which subtopic it examines, not just which topic.
--
-- WHY. Topic weights were already real — they come from the paper's own structure. Subtopic
-- weights were not: a topic's share was split evenly among its subtopics, because the column
-- holding the attribution was called topic_id and pointed at topics. That even split is what
-- every study plan was being built on, and it is wrong in a way that matters. UTME Use of
-- English sets ten cloze questions and five comprehension questions; an even split across
-- Comprehension and Summary's six subtopics gave both 4.17, when the truth is 10 and 1.67.
-- A plan built on that sends a student to the wrong place for weeks.
--
-- But the printed structure does not always reach a subtopic. "Basic grammar - 10 questions"
-- covers five of them without saying in what proportion, and no amount of reading page 3
-- will divide it. So the column is renamed rather than replaced, and a section may name a
-- topic, a subtopic or a skill — whichever the document actually supports. Attribution is as
-- fine as the evidence, and no finer.
--
-- Nothing about topic weights changes. topic_exam_weight now resolves whatever a section
-- names up to its topic, so a section that still names a topic contributes exactly as before.
BEGIN;
SET LOCAL search_path = stackprep, public;

ALTER TABLE exam_paper_sections RENAME COLUMN topic_id TO curriculum_item_id;
COMMENT ON COLUMN exam_paper_sections.curriculum_item_id IS
  'The most specific syllabus item this printed section examines: a topic when the section '
  'spans several subtopics, a subtopic when it names one, a skill when it names one. Null '
  'when the section cannot be attributed at all, in which case it weights nothing.';

-- A section names an item; the item sits somewhere in topic > subtopic > skill. These two
-- expressions climb to whichever level a view needs. The hierarchy is exactly three deep and
-- the schema enforces that, so this is a join and not a recursion.
CREATE OR REPLACE VIEW section_attribution AS
SELECT s.id              AS section_id,
       s.syllabus_version_id,
       s.question_count,
       coalesce(s.marks_total,
                p.score_out_of * s.question_count::numeric
                  / nullif(p.question_count, 0)::numeric)      AS marks,
       CASE ci.item_type
         WHEN 'topic'    THEN ci.id
         WHEN 'subtopic' THEN ci.parent_id
         WHEN 'skill'    THEN parent.parent_id
       END                                                     AS topic_id,
       CASE ci.item_type
         WHEN 'subtopic' THEN ci.id
         WHEN 'skill'    THEN ci.parent_id
       END                                                     AS subtopic_id
FROM exam_paper_sections s
JOIN exam_papers p ON p.id = s.exam_paper_id
JOIN curriculum_items ci ON ci.id = s.curriculum_item_id
LEFT JOIN curriculum_items parent ON parent.id = ci.parent_id
WHERE s.review_status = 'approved'
  AND s.curriculum_item_id IS NOT NULL
  AND p.response_mode = 'objective'
  AND p.status <> 'retired';

CREATE OR REPLACE VIEW topic_exam_weight AS
SELECT syllabus_version_id,
       topic_id,
       sum(question_count)                                     AS expected_questions,
       round(sum(marks), 2)                                    AS expected_marks,
       round(sum(marks) / sum(sum(marks)) OVER (PARTITION BY syllabus_version_id), 4) AS share,
       'exam_structure'::text                                  AS source
FROM section_attribution
WHERE topic_id IS NOT NULL
GROUP BY syllabus_version_id, topic_id;

-- What each SUBTOPIC is worth.
--
-- Two kinds of section feed this. One names a subtopic, and its questions go there. One names
-- only a topic, and its questions have to be shared out — across the subtopics of that topic
-- that no section names, because a subtopic with its own printed section has already been
-- accounted for. Where every subtopic of a topic is named, there is nobody left to share
-- with, so the leftover is spread across all of them rather than lost.
--
-- That rule is a judgement and it is visible here rather than buried in a query somewhere.
-- It is slightly generous to the unnamed subtopics: "Basic grammar" almost certainly sets a
-- question or two on clause patterns, which already has its own section, and this gives those
-- to word classes and concord instead. That is a smaller error than an even split, and it is
-- an error in the direction of the parts of the syllabus we know least about.
CREATE OR REPLACE VIEW subtopic_exam_weight AS
WITH named AS (
  SELECT syllabus_version_id, subtopic_id, topic_id,
         sum(question_count) AS questions, sum(marks) AS marks
  FROM section_attribution
  WHERE subtopic_id IS NOT NULL
  GROUP BY syllabus_version_id, subtopic_id, topic_id
),
spare AS (
  SELECT syllabus_version_id, topic_id,
         sum(question_count) AS questions, sum(marks) AS marks
  FROM section_attribution
  WHERE subtopic_id IS NULL AND topic_id IS NOT NULL
  GROUP BY syllabus_version_id, topic_id
),
candidates AS (
  SELECT sp.syllabus_version_id, sp.topic_id, sub.id AS subtopic_id,
         sp.questions, sp.marks,
         NOT EXISTS (SELECT 1 FROM named n WHERE n.subtopic_id = sub.id) AS unnamed
  FROM spare sp
  JOIN curriculum_items sub
    ON sub.parent_id = sp.topic_id AND sub.item_type = 'subtopic'
),
receivers AS (
  SELECT c.*
  FROM candidates c
  WHERE c.unnamed
     OR NOT EXISTS (SELECT 1 FROM candidates o WHERE o.topic_id = c.topic_id AND o.unnamed)
),
shared AS (
  SELECT syllabus_version_id, subtopic_id, topic_id,
         questions::numeric / count(*) OVER (PARTITION BY topic_id) AS questions,
         marks / count(*) OVER (PARTITION BY topic_id)              AS marks
  FROM receivers
),
combined AS (
  SELECT syllabus_version_id, subtopic_id, topic_id, questions::numeric, marks FROM named
  UNION ALL
  SELECT syllabus_version_id, subtopic_id, topic_id, questions, marks FROM shared
)
SELECT syllabus_version_id,
       subtopic_id,
       topic_id,
       round(sum(questions), 2)                                AS expected_questions,
       round(sum(marks), 2)                                    AS expected_marks,
       round(sum(marks) / sum(sum(marks)) OVER (PARTITION BY syllabus_version_id), 4) AS share,
       'exam_structure'::text                                  AS source
FROM combined
GROUP BY syllabus_version_id, subtopic_id, topic_id;

COMMIT;
