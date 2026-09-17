# Student schema

**Status: implemented in migrations
[007](../database/migrations/007_students.sql) (students and evidence),
[008](../database/migrations/008_assessments.sql) (exams) and
[009](../database/migrations/009_learning_profile.sql) (the learning profile),
each with tests of the same number.**
Date: 17 September 2026

The student side of the product: who is learning, what they consented to, what they did,
and what the engine concluded from it. Read with [product-spec.md §12 and §14](product-spec.md)
and [ADR-0013](adr/0013-auth-and-sessions.md).

## What one row means

| Table | One row is | Kind |
| --- | --- | --- |
| `students` | One learner | Source of truth |
| `guardians` | One parent or guardian | Source of truth |
| `guardian_students` | One verified guardian–student link | Source of truth |
| `consents` | One recorded consent decision | Source of truth |
| `student_exam_goals` | One subject a student is preparing for, with a target out of 100 | Source of truth |
| `study_sessions` | One learning sitting: practice, check-up, review | Source of truth |
| `attempts` | **One answered question** | Source of truth, append-only |
| `assessments` | One assembled paper | Source of truth |
| `assessment_items` | One question's placement in a paper | Source of truth |
| `assessment_sittings` | One student taking one paper once | Source of truth |
| `skill_ratings` | What we believe about one student on one skill | Derived |
| `review_state` | When a skill is due back | Derived |

## Exams are not practice

An exam has a form fixed before it starts, a deadline the server owns, no hints, and a score
in which an unanswered question is not the same as a wrong one. Practice has none of that:
items are chosen one at a time, hints are the point, and there is no score. One table cannot
enforce both sets of rules, so **the administration of exams is separate** — `assessments`,
`assessment_items`, `assessment_sittings` — and `study_sessions` is learning-only.

**What is not split is the evidence.** `attempts` remains the single record of "this student
answered this item, this way, in this long", because mastery, item statistics and calibration
all read it. Splitting it would turn each of those into a union, and any query that forgot
half would be quietly wrong. An attempt belongs to a study session **or** a sitting — never
both, never neither.

What the database enforces:

- A published paper is frozen: its questions and marks cannot change, so two students'
  results mean the same thing.
- Publication checks every question is approved for delivery and comes from the pool the
  assessment requires — a mock cannot contain a question students practise on.
- The declared mark total must match the marks actually placed.
- An answer must belong to an open sitting, to the right student, and to the question
  actually placed at that position.
- Hints and viewed solutions are impossible inside an exam.
- Changing an answer writes a new attempt; `sitting_final_answers` takes the last one before
  the deadline, and `sitting_results` reports how many answers were changed.
- Unanswered questions are counted as unanswered, never as wrong.

## The learning profile

Migration 009 links a student to **everything in the syllabus they are preparing for**, with
what they have done against it:

| View | One row is |
| --- | --- |
| `student_syllabus_map` | One student × one curriculum item (topic, subtopic or skill), with rating and evidence. Untouched items appear with zeros — "not yet assessed" is something the planner needs to see |
| `student_subtopic_state` | One student × subtopic: skills assessed vs total, mean and weakest mastery, attempts, right, wrong, next review |
| `student_skill_evidence` | One student × skill: attempted, right, wrong, how fast, how recently |
| `student_skill_answers` | Every answer, joined to the skill it tested |
| `student_question_history` | Which questions the student has seen and how it went — the selector reads it to avoid repeats |
| `student_recent_answers` | The last answers with stem, choice, correct option and the misconception behind a wrong choice — the context an AI tutor needs |

**These are views, not tables.** A subtopic's state is an aggregate of evidence that already
exists; storing it again creates a second source of truth that drifts the first time a job
fails halfway. Trends over time are a different thing and get a snapshot table when the
metrics work lands.

**They expose mastery as a probability, never as a band.** "Weak" and "exam-ready" are the
engine's thresholds ([packages/engine](../packages/engine)); duplicating them in SQL would
let the database and the engine disagree about the same student.

Two further views: `student_skill_state` (what the planner reads) and
`student_daily_activity` (counts for the teacher list and guardian digest — counts only,
never answers).

## Three rules the database enforces

**1. Attempts are append-only.** Mastery, plans and score ranges are all derived from them.
A rewritten attempt silently rewrites a student's history and everything computed from it,
so `UPDATE` and `DELETE` are blocked by a trigger. A wrong mark is corrected by recording a
new attempt, not by editing the old one.

Erasure is the one exception, and it has to be asked for in the open:

```sql
SET LOCAL scorepilot.allow_erasure = 'on';
DELETE FROM attempts WHERE student_id = :student;
```

Ordinary application code never sets that, so a deletion can only come from a job written
to handle a deletion request.

**2. No consent, no storage.** Most candidates are 16–18. A student marked
`requires_guardian_consent` — the default, because assuming a minor is the safe error —
cannot have an attempt stored until a live `data_processing` consent exists. The trigger
refuses the insert with a plain message rather than trusting the API to remember.

Consent is a row, never an inference: who granted it, through which guardian link, from
what source, and what evidence exists. A school-collected consent must name its evidence.
Revoking and re-granting creates a new row; only one live consent of each type can exist.

**3. Derived state is disposable.** `skill_ratings` and `review_state` carry
`engine_version` and can be rebuilt by replaying attempts. When the engine changes, state
is recomputed rather than migrated.

## Details worth knowing

- **Two clocks on every attempt.** `answered_at_client` is when the student answered;
  `received_at` is when it reached us. Devices are offline, and their clocks are sometimes
  wrong or deliberately moved, so both are kept and the analysis can choose.
- **The attempt's primary key is generated on the device.** A retried sync carries the same
  id, so the second write is rejected as a duplicate rather than double-counting practice.
- **Attempts point at a `question_version`, not a question.** A student's history reflects
  what they actually saw, even after the question is corrected.
- **Goals are per subject, out of 100** (ADR-0014, ADR-0015). One active goal per subject.
- **Minimal personal data:** no address, no national identifier, a birth date only when the
  product needs one, and a contact route or a school reference — at least one is required.

## Deliberately not here

- **Plans, plan items and score ranges** — they belong with the planner, and inventing their
  shape before the engine exists would guess at the wrong thing.
- **Per-subtopic snapshots over time** — the views above give the current state; trends need
  a dated snapshot table, which arrives with the metrics work.
- **Schools, classrooms and enrolment** — the POC is direct-to-student; `students.external_ref`
  holds a school's own identifier in the meantime.
- **Authentication** — sessions and sign-in are ADR-0013, still proposed. Nothing here
  assumes a particular auth model.

## Open decisions

| # | Question | Needed by |
| --- | --- | --- |
| a | Retention periods per table, and what a deletion request must remove versus anonymise | Before the pilot collects real data |
| b | Whether a withdrawn consent erases past attempts or freezes them | Same |
| c | The pseudonymised research export: which columns, and the key that links a student across it | Before any analysis work |
| d | Whether school enrolment arrives before the pilot (it changes who can see a student's progress) | Before school onboarding |
