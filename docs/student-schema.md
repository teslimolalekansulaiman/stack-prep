# Student schema

**Status: implemented in [`database/migrations/007_students.sql`](../database/migrations/007_students.sql),
tested in [`database/tests/007_students.sql`](../database/tests/007_students.sql).**
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
| `study_sessions` | One sitting: practice, check-up or mock | Source of truth |
| `attempts` | **One answered question** | Source of truth, append-only |
| `skill_ratings` | What we believe about one student on one skill | Derived |
| `review_state` | When a skill is due back | Derived |

Two views: `student_skill_state` (what the planner reads) and `student_daily_activity`
(counts for the teacher list and guardian digest — counts only, never answers).

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
- **Mock sessions and responses** — the CBT simulator defines them (roadmap M4).
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
