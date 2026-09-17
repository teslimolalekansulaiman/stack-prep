-- The learning profile: every part of the syllabus a student is preparing for, with what
-- they have done against it.
--
-- These are views, not tables, on purpose. A student's state at subtopic level is an
-- aggregate of evidence that already exists — ratings at skill level, attempts in the
-- append-only log. Storing it again would create a second source of truth that drifts the
-- first time a job fails halfway. Trends over time are a different thing and get their own
-- snapshot table when the metrics work lands.
--
-- One deliberate omission: these views expose mastery as a probability, never as a band
-- ("weak", "exam-ready"). The thresholds belong to packages/engine; duplicating them in SQL
-- would let the database and the engine disagree about the same student.
BEGIN;
SET LOCAL search_path = stackprep, public;

-- Makes the per-student evidence lookups below index-only friendly.
CREATE INDEX IF NOT EXISTS attempts_student_question_idx
  ON attempts(student_id, question_version_id);

-- Every answer a student has given, tied to the skill it tested. This is the join that
-- turns "answered question 47" into "practised translating word problems".
CREATE VIEW student_skill_answers AS
SELECT a.id                       AS attempt_id,
       a.student_id,
       a.question_version_id,
       qv.question_id,
       q.subject_id,
       c.curriculum_item_id       AS skill_id,
       c.syllabus_version_id,
       qv.mastery_level_number    AS question_level,
       a.context,
       a.sitting_id IS NOT NULL   AS in_exam,
       a.selected_option_key,
       a.is_correct,
       a.response_ms,
       a.hint_count,
       a.solution_viewed_before_answer,
       a.answered_at_client
FROM attempts a
JOIN question_versions qv ON qv.id = a.question_version_id
JOIN questions q ON q.id = qv.question_id
JOIN question_classifications c
  ON c.question_id = qv.question_id
 AND c.classification_role = 'primary'
 AND c.review_status = 'approved';

-- What one student has done on one skill: attempted, right, wrong, how fast, how recently.
CREATE VIEW student_skill_evidence AS
SELECT student_id,
       skill_id,
       count(*)                                        AS attempts,
       count(*) FILTER (WHERE is_correct)              AS correct,
       count(*) FILTER (WHERE is_correct IS FALSE)     AS wrong,
       count(*) FILTER (WHERE in_exam)                 AS exam_attempts,
       count(*) FILTER (WHERE hint_count > 0)          AS attempts_with_help,
       round(avg(response_ms))                         AS mean_response_ms,
       max(answered_at_client)                         AS last_answered_at,
       max(answered_at_client) FILTER (WHERE is_correct) AS last_correct_at,
       round(
         count(*) FILTER (WHERE is_correct)::numeric / nullif(count(*), 0), 4
       )                                               AS correct_rate
FROM student_skill_answers
GROUP BY student_id, skill_id;

-- The whole syllabus for the subjects a student is actively preparing for — topics,
-- subtopics and skills — with their rating and evidence where any exists. Items the
-- student has never touched appear with nulls and zeros, because "not yet assessed" is
-- something the planner and the tutor both need to see.
CREATE VIEW student_syllabus_map AS
SELECT g.student_id,
       g.id                       AS goal_id,
       g.subject_id,
       v.id                       AS syllabus_version_id,
       ci.id                      AS curriculum_item_id,
       ci.item_type,
       ci.code,
       ci.name,
       ci.display_order,
       CASE ci.item_type
         WHEN 'topic' THEN ci.id
         WHEN 'subtopic' THEN parent.id
         ELSE grandparent.id
       END                        AS topic_id,
       CASE ci.item_type
         WHEN 'topic' THEN ci.name
         WHEN 'subtopic' THEN parent.name
         ELSE grandparent.name
       END                        AS topic_name,
       CASE ci.item_type
         WHEN 'subtopic' THEN ci.id
         WHEN 'skill' THEN parent.id
       END                        AS subtopic_id,
       CASE ci.item_type
         WHEN 'subtopic' THEN ci.name
         WHEN 'skill' THEN parent.name
       END                        AS subtopic_name,
       ci.pilot_support_status,
       r.theta,
       -- The engine's displayed mastery: the chance of answering a standard exam-level
       -- item. Bands are the engine's to name, not this view's.
       CASE WHEN r.theta IS NOT NULL
            THEN round((1 / (1 + exp(-r.theta)))::numeric, 4) END AS mastery_estimate,
       r.scored_attempts,
       r.confidence,
       r.last_success_at,
       r.half_life_days,
       rs.next_review_at,
       coalesce(e.attempts, 0)    AS attempts,
       coalesce(e.correct, 0)     AS correct,
       coalesce(e.wrong, 0)       AS wrong,
       e.correct_rate,
       e.mean_response_ms,
       e.last_answered_at
FROM student_exam_goals g
JOIN syllabus_versions v
  ON v.subject_id = g.subject_id AND v.status = 'approved' AND v.is_current
JOIN curriculum_items ci ON ci.syllabus_version_id = v.id
LEFT JOIN curriculum_items parent ON parent.id = ci.parent_id
LEFT JOIN curriculum_items grandparent ON grandparent.id = parent.parent_id
LEFT JOIN skill_ratings r ON r.student_id = g.student_id AND r.skill_id = ci.id
LEFT JOIN review_state rs ON rs.student_id = g.student_id AND rs.skill_id = ci.id
LEFT JOIN student_skill_evidence e ON e.student_id = g.student_id AND e.skill_id = ci.id
WHERE g.status = 'active';

-- One row per student and subtopic: how much of it has been assessed, how it is going, and
-- which skill inside it is weakest. This is the level people talk in — "your weakest area
-- is comprehension inference" — while the engine keeps deciding at skill level.
CREATE VIEW student_subtopic_state AS
SELECT student_id,
       subject_id,
       syllabus_version_id,
       topic_id,
       topic_name,
       subtopic_id,
       subtopic_name,
       count(*)                                          AS skills_total,
       count(*) FILTER (WHERE scored_attempts > 0)       AS skills_assessed,
       count(*) FILTER (WHERE attempts = 0)              AS skills_untouched,
       round(avg(mastery_estimate) FILTER (WHERE mastery_estimate IS NOT NULL), 4)
                                                         AS mean_mastery,
       min(mastery_estimate)                             AS weakest_mastery,
       (array_agg(code ORDER BY mastery_estimate NULLS LAST))[1] AS weakest_skill_code,
       sum(attempts)                                     AS attempts,
       sum(correct)                                      AS correct,
       sum(wrong)                                        AS wrong,
       max(last_answered_at)                             AS last_answered_at,
       min(next_review_at)                               AS next_review_at
FROM student_syllabus_map
WHERE item_type = 'skill' AND subtopic_id IS NOT NULL
GROUP BY student_id, subject_id, syllabus_version_id, topic_id, topic_name,
         subtopic_id, subtopic_name;

-- Which questions a student has already seen, and how it went. The selector reads this to
-- avoid repeating an item; the tutor reads it to talk about a specific past mistake.
CREATE VIEW student_question_history AS
SELECT a.student_id,
       a.question_version_id,
       a.question_id,
       a.skill_id,
       count(*)                                       AS times_attempted,
       bool_or(a.is_correct)                          AS ever_correct,
       max(a.answered_at_client)                      AS last_answered_at,
       (array_agg(a.is_correct ORDER BY a.answered_at_client DESC))[1]        AS last_outcome,
       (array_agg(a.selected_option_key ORDER BY a.answered_at_client DESC))[1] AS last_choice,
       bool_or(a.in_exam)                             AS seen_in_exam
FROM student_skill_answers a
GROUP BY a.student_id, a.question_version_id, a.question_id, a.skill_id;

-- The student's recent answers, newest first, with enough context for a tutor prompt:
-- what was asked, what they chose, whether it was right, and the misconception their
-- choice points at. Callers filter on `recency` to take the last N.
CREATE VIEW student_recent_answers AS
SELECT a.student_id,
       row_number() OVER (PARTITION BY a.student_id ORDER BY a.answered_at_client DESC) AS recency,
       a.answered_at_client,
       a.context,
       a.in_exam,
       a.skill_id,
       ci.code                    AS skill_code,
       ci.name                    AS skill_name,
       qv.stem,
       qv.mastery_level_number    AS question_level,
       a.selected_option_key,
       chosen.body                AS chosen_option,
       a.is_correct,
       correct_option.option_key  AS correct_option_key,
       m.code                     AS misconception_code,
       m.name                     AS misconception_name,
       a.response_ms,
       a.hint_count
FROM student_skill_answers a
JOIN question_versions qv ON qv.id = a.question_version_id
JOIN curriculum_items ci ON ci.id = a.skill_id
LEFT JOIN question_options chosen
  ON chosen.question_version_id = a.question_version_id
 AND chosen.option_key = a.selected_option_key
LEFT JOIN question_options correct_option
  ON correct_option.question_version_id = a.question_version_id
 AND correct_option.is_correct
LEFT JOIN misconceptions m ON m.id = chosen.misconception_id;

COMMIT;
