# Where the schema differs from the data model document

**StackPrep — Complete Project Data Model v1.1** (15 September 2026) is the design
this schema implements. It is a proposed design, not executable SQL, and in places
the implementation has moved past it.

> **That document is not in this repository.** It exists only as an HTML file
> passed around outside version control, which means the schema's specification
> cannot be diffed, reviewed or pinned to a commit. It should be added to `docs/`.
> Until it is, this file is the only record of where the two disagree.

This file records every deliberate difference and why. If you are reading the
document and the database disagrees with it, the answer should be here. If it
is not, that is a bug in one of them — say so rather than guessing.

---

## Mastery is the engine's shape, not the document's

**The document** gives `student_skill_mastery` the columns `evidence_count`,
`consecutive_successes`, `consecutive_failures`, with statuses
*learning / practising / mastered / reopened*.

**`packages/engine` uses** `theta`, `scored_attempts`, `levels_seen`, with bands
*not_assessed / weak / developing / exam_ready / strong / maintained*.

`mastery_score` and `confidence` agree — `displayed_mastery()` and `confidence()`
produce exactly those. The underlying state and the status vocabulary do not.

**The engine wins.** Reasons, in order of weight:

1. It weights every answer by the difficulty of the question it was given on.
   Three correct answers at level 1 and three at level 5 are different evidence,
   and counting consecutive successes cannot tell them apart. That distinction is
   the product.
2. It exists, is tested, and is mirrored in TypeScript for offline use with
   shared parity vectors (ADR-0005). Rewriting it to match the document would
   discard tested work for no gain.
3. `packages/engine/version.py` says derived state is rebuilt by replaying events
   under a known engine version, so the stored shape has to be what the engine
   produces or that guarantee breaks.
4. The document's own "Decisions the team must settle before coding migrations"
   list still shows mastery policy as open. The engine settled it in code; the
   document has not caught up.

Confirmed with Teslim, September 2026. Implemented in migration 008.

**One further departure, not in the document at all:** `student_skill_mastery` is
*derived*. It cannot be written to directly — a trigger refuses it. The only way
a student's mastery changes is by inserting a `mastery_events` row, which the
database then applies. An event must also agree with the state it claims to
replace, so the history always reconstructs the present value.

The document asks for this outcome ("every state transition creates an event with
previous/new state, triggering diagnosis or evidence and rule version") but leaves
it to whoever writes the application. Making the current value derived means an
undocumented change to what a student knows is not possible rather than merely
discouraged, which matters when the number eventually backs a refund promise.

---

## A placement freezes a question *version*, not a question

**The document** has `assessment_questions.question_id` referencing "the frozen
approved question".

**The schema** carries `question_version_id` as well, tied to `question_id` by a
composite key so the two can never disagree.

This schema versions questions (migration 003) — the document's Section B design
did not. A student marked against version 2 must never be re-read against version
3, and pointing at the question alone cannot express that. The document's intent
("freeze the assessment's question order, marks and content reference") is
honoured more exactly this way, not less.

---

## Responses carry the engine's evidence fields

**The document** gives `student_responses` an answer, working, marks and timing.

**The schema** adds `response_ms`, `hint_used` and `solution_viewed_before_answer`,
named to match `engine.mastery.Attempt` exactly.

Those three are what the engine needs to fold an answer into a rating: a correct
answer given too quickly is treated as a guess, a hint caps the credit earned, and
viewing the solution first means the attempt is not scored at all. Naming them
identically means nothing is translated between the database and the engine, and
a mismatch becomes a type error rather than a silent miscalculation.

---

## Adaptive sessions grow; fixed papers freeze

**The document** says to "freeze the assessment's question order, marks and content
reference" at publication, and separately notes that "adaptive delivery needs
separately defined question-placement policy". This is that policy.

**The schema** freezes a fixed paper completely at publication, and lets an
adaptive session gain questions while it is open — but never edit or remove one.

The guarantee that matters is narrower than a freeze: work a student has already
done must not change underneath them. Appending a question they have not seen does
not breach that; editing or withdrawing one they have answered does, and stays
forbidden in both modes. Anything appended to a live session still has to pass
`deliverable_questions`, since the publication check cannot see a question that did
not exist when it ran.

An adaptive set is also required to name the student it belongs to. It is one
learner's session, not a paper several people sit.

---

## Identity is thinner than the document, on purpose

**The document** gives `users` an `auth_provider_id` for an external identity
provider.

**The schema** has the column but leaves it nullable and unused.

[ADR-0013](adr/0013-auth-and-sessions.md) has not chosen a provider. A person can
exist in the table but cannot sign in, which is the honest state of the product.
Guessing a provider's identifier format now would mean a migration later.

The document's rule that a user must have an email or a phone *is* enforced, as is
the rule that a guardian's account cannot acquire a student profile — the latter
by a composite key rather than application code, so it holds regardless of which
service writes the row.

---

## Not yet built

From the document's 26 tables, still missing: `guardian_profiles`,
`guardian_students`, `student_exam_goals`, `response_diagnoses`,
`learning_plans`, `learning_plan_items`, `learning_sessions`,
`generation_profiles` and `generation_profile_questions`.

Their absence is recorded here rather than implied, per the document's own
instruction that deferred entities be stated explicitly instead of pretending
current tables already implement them.
