# Question schema — proposal

**Status: implemented in [`database/migrations/003_questions.sql`](../database/migrations/003_questions.sql),
with tests in [`database/tests/003_questions.sql`](../database/tests/003_questions.sql).**
Exam scope and marking settled in [ADR-0014](adr/0014-neco-objective-poc.md): NECO
objective papers for the POC, marking kept general, each subject reported out of 100.
Date: 17 September 2026 · Author: engineering · Reviewers: academic team

This builds on *StackPrep Complete Project Data Model v1.1* (15 Sep 2026) and on the
nine tables already live in the `stackprep` schema. It keeps v1.1's shape —
questions, classifications, generation profiles — and changes ten things, each
explained below with the reason.

Read with [product-spec.md §9 and §11](product-spec.md) and [ADR-0006](adr/0006-sql-first-schema.md).

---

## 1. What one row means

| Table | One row is | Phase |
| --- | --- | --- |
| `exam_papers` | One paper within a subject, e.g. Paper I (objective), with its confirmed structure and mark total. | 1 |
| `questions` | One independently answerable item, with its provenance. Stable identity. | 1 |
| `question_versions` | One immutable snapshot of that item's content. | 1 |
| `question_options` | One lettered choice on one version. | 1 |
| `passages` | One shared stimulus (comprehension passage, data table, diagram set). | 1 |
| `question_assets` | One image or file used by a version, with rights and alt text. | 1 |
| `question_classifications` | One question mapped to one syllabus skill, at one level. | 1 |
| `misconceptions` | One named, recurring reason students get things wrong. | 1 |
| `question_statistics` | Derived performance of one version, recomputed nightly. | 1 |
| `question_reports` | One problem reported against a version. | 1 |
| `question_import_batches` | One ingestion run from one source file. | 1 |
| `generation_profiles` | One approved brief for generating items for a skill and level. | 2 |
| `generation_profile_questions` | One approved question used as evidence for a profile. | 2 |

## 2. How it attaches to what exists

```
examinations → subjects → syllabus_versions → curriculum_items (topic/subtopic/skill)
                                                   │            └─ curriculum_mastery_levels
                                                   │            └─ curriculum_prerequisites
                                                   ▼
                                       question_classifications
                                                   ▲
source_documents ──────────────► questions ──► question_versions ──► question_options
   (rights, licence, review)         │                 │            └─ question_assets
                                     │                 └─ passages
                                     └─ question_import_batches
```

Nothing in the question tables restates what the curriculum tables already say. A
question knows its subject and its skill; topic and depth are reached through
`curriculum_items`.

## 3. What changed from StackPrep v1.1, and why

| # | v1.1 | Proposed | Reason |
| --- | --- | --- | --- |
| 1 | One `questions` table, frozen once approved | `questions` (identity) + `question_versions` (content) | A typo fix after a mock must not rewrite what a student was asked. Responses point at the version; statistics aggregate by version; the question keeps one identity across corrections. |
| 2 | `options` in JSONB | `question_options` rows | v1.1's own rule says cross-table links don't belong in JSONB — and each wrong option links to a misconception. Rows also give per-option analytics ("41% chose C") and let the database enforce exactly one correct answer. |
| 3 | `passage_text` on the question | `passages` table, referenced by versions | One English comprehension passage carries five or more questions. Copying it per question breaks rights tracking, reading-time estimates and delivery size. |
| 4 | `asset_urls` JSONB | `question_assets` rows | Each diagram needs its own licence state and alt text. Accessibility and rights are per file, not per question. |
| 5 | — | `usage_pool` on every question: `practice`, `diagnostic`, `held_out` | Score ranges are only honest when measured on items the student has never practised. Without a reserved pool, mastery measures our bank, not the exam. This is the single most important addition. |
| 6 | `difficulty` enum on the classification | Academic **level** stays on the classification; empirical difficulty moves to `question_statistics` | Two different facts. The level is a reviewed academic judgment tied to a skill; difficulty is what students actually did. Mixing them means neither can be trusted. |
| 7 | Misconception as a free-text label on a diagnosis | `misconceptions` catalogue, referenced by the wrong option | A named, reusable misconception can be counted across students and drive the help ladder. Free text cannot. |
| 8 | — | `question_statistics` (derived) | The spec requires auto-flagging items with a correct rate below 10% or above 97%, and later calibration of item difficulty. |
| 9 | — | `question_reports` | Sprint S3 requires "report a problem with this question" feeding a review queue. |
| 10 | Ingestion contract undecided | `question_import_batches` + deterministic IDs | Re-running an import must not duplicate rows, exactly as the syllabus loader already guarantees for curriculum items. |

Kept from v1.1 unchanged in spirit: provenance rules (past questions need a
licensed source, generated questions need an approved profile), at most one
approved primary classification, the review workflow, answers hidden from
candidate responses, and generation profiles with reference questions.

## 4. Table proposals

Conventions follow `001_curriculum.sql`: UUID primary keys, `text` with `CHECK (... IN (...))`
rather than Postgres enums, `btrim(x) <> ''` on required text, composite unique keys so
child rows can be forced to stay consistent, and the review pattern
`CHECK (review_status <> 'approved' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL))`.

### 4.1 `questions` — identity and provenance

| Column | Type | Meaning |
| --- | --- | --- |
| `id` | uuid PK | Deterministic for imports (see §7) |
| `subject_id` | uuid FK subjects | The exam-specific subject |
| `origin` | text | `past_paper`, `authored`, `generated` |
| `source_document_id` | uuid FK source_documents, null | Required when `origin = 'past_paper'` |
| `exam_year`, `paper_code`, `question_number` | integer, text, text, null | Historical locator |
| `generation_profile_id` | uuid FK, null | Required when `origin = 'generated'` (Phase 2) |
| `parent_question_id` | uuid FK questions, null | Multipart grouping: 4(a), 4(b) |
| `part_label` | text, null | `a`, `b`, `i` as printed |
| `import_batch_id` | uuid FK question_import_batches, null | Which ingestion run created it |
| `current_version_id` | uuid FK question_versions, null | The live version (set after insert) |
| `usage_pool` | text | `practice`, `diagnostic`, `held_out` |
| `retired_at`, `retired_reason` | timestamptz, text, null | Withdrawal without deletion |
| `created_by` | uuid FK academic_reviewers | Author |
| `created_at`, `updated_at` | timestamptz | Audit |

Constraints

- `UNIQUE (id, subject_id)` — lets classifications prove the skill belongs to the same subject.
- `CHECK (origin <> 'past_paper' OR source_document_id IS NOT NULL)`
- `CHECK (origin <> 'generated' OR generation_profile_id IS NOT NULL)`
- `CHECK (origin <> 'generated' OR usage_pool = 'practice')` — **generated items never sit in the diagnostic or held-out pools.** Assessments must be measured on human-verified content.
- `CHECK (parent_question_id IS NULL OR part_label IS NOT NULL)`
- No cycles in `parent_question_id`, one level deep only (trigger, like `check_syllabus_version`).
- Unique historical locator per source: `UNIQUE (source_document_id, paper_code, question_number, part_label)` where the source is not null.

### 4.2 `question_versions` — immutable content

| Column | Type | Meaning |
| --- | --- | --- |
| `id` | uuid PK | |
| `question_id` | uuid FK questions | Owner |
| `version` | integer | 1, 2, 3 … |
| `passage_id` | uuid FK passages, null | Shared stimulus |
| `stem` | text | The question as the candidate reads it |
| `instructions` | text, null | "Choose the correct option" |
| `response_format` | text | `mcq_single`, `numeric`, `short_text`, `structured`, `essay` |
| `marking_method` | text | `auto_key`, `auto_numeric`, `rubric`, `ai_assisted`, `human` |
| `numeric_answer`, `numeric_tolerance`, `numeric_unit` | numeric, numeric, text, null | For `numeric` |
| `accepted_answers` | jsonb, null | Alternative accepted strings, validated against a JSON schema |
| `solution_steps` | jsonb | Ordered worked solution — the grounding for AI help (ADR-0009) |
| `marking_scheme` | jsonb, null | Mark allocation for non-auto marking |
| `hints` | jsonb | Ordered hints, at least one |
| `marks` | numeric(6,2) | Marks as printed, when known |
| `expected_seconds` | integer | Feeds the engine's guess detection |
| `mastery_level_number` | smallint | The L1–L5 the engine ladders on (§6) |
| `option_count` | smallint, null | Generated from the option rows; the engine's chance level is `1 / option_count` |
| `content_hash` | text | Duplicate detection within a subject |
| `review_status` | text | `draft`, `pending`, `approved`, `rejected`, `withdrawn` |
| `authored_by`, `reviewed_by`, `reviewed_at` | uuid, uuid, timestamptz | Two-person rule |
| `created_at` | timestamptz | |

Constraints

- `UNIQUE (question_id, version)`, `UNIQUE (id, question_id)`
- `CHECK (review_status <> 'approved' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL))`
- `CHECK (reviewed_by IS NULL OR reviewed_by <> authored_by)` — nobody approves their own item.
- `CHECK (response_format <> 'mcq_single' OR marking_method = 'auto_key')`
- `CHECK (marking_method <> 'auto_numeric' OR numeric_answer IS NOT NULL)`
- `CHECK (expected_seconds BETWEEN 10 AND 1800)`
- `CHECK (mastery_level_number BETWEEN 1 AND 5)`
- `CHECK (jsonb_typeof(solution_steps) = 'array' AND jsonb_array_length(solution_steps) > 0)`
- `CHECK (jsonb_typeof(hints) = 'array' AND jsonb_array_length(hints) > 0)`
- `UNIQUE (question_id, content_hash)` and an index on `content_hash` for cross-subject review.
- **Immutability:** once `review_status = 'approved'`, a trigger rejects updates to every content column. Corrections create version n+1.

### 4.3 `question_options`

| Column | Type | Meaning |
| --- | --- | --- |
| `id` | uuid PK | |
| `question_version_id` | uuid FK question_versions | Owner |
| `option_key` | text | `A`–`E` |
| `body` | text | Option text |
| `is_correct` | boolean | |
| `misconception_id` | uuid FK misconceptions, null | Why a student would pick this wrong option |
| `distractor_note` | text, null | Reviewer explanation shown with the solution |
| `display_order` | smallint | |

Constraints

- `UNIQUE (question_version_id, option_key)`
- `CHECK (option_key ~ '^[A-E]$')`
- `CHECK (is_correct OR misconception_id IS NOT NULL OR distractor_note IS NOT NULL)` for the top-weighted skills — enforced at approval, not insert (see §5).
- Exactly one correct option per version: partial unique index on `(question_version_id) WHERE is_correct`.
- At least four options for `mcq_single`, checked at approval.

### 4.4 `passages`

| Column | Type | Meaning |
| --- | --- | --- |
| `id` | uuid PK | |
| `subject_id` | uuid FK subjects | |
| `source_document_id` | uuid FK source_documents, null | Rights inheritance |
| `title` | text, null | |
| `body` | text | The passage as read |
| `passage_type` | text | `prose`, `dialogue`, `data_table`, `figure_set` |
| `word_count` | integer | Generated |
| `estimated_reading_seconds` | integer | Feeds session time estimates |
| `reading_level_note` | text, null | Reviewer judgment |
| `licence_status` | text | `pending`, `verified`, `blocked` |
| `review_status`, `reviewed_by`, `reviewed_at` | | Same pattern |

A passage is immutable once approved, like a question version. Comprehension
passages are the most rights-sensitive content in the bank: an original passage
written for us is safest, and an extract needs the same licence evidence a source
document does.

### 4.5 `question_assets`

| Column | Type | Meaning |
| --- | --- | --- |
| `id` | uuid PK | |
| `question_version_id` | uuid FK, null | Either a question version… |
| `passage_id` | uuid FK, null | …or a passage owns it |
| `storage_uri` | text | Object storage, not the database |
| `mime_type`, `byte_size`, `width`, `height` | | Delivery budget checks |
| `alt_text` | text | Required before approval — accessibility, and it is what an AI tutor can read |
| `licence_status` | text | `pending`, `verified`, `blocked` |
| `display_order` | smallint | |

`CHECK ((question_version_id IS NULL) <> (passage_id IS NULL))` — exactly one owner.

### 4.6 `question_classifications`

| Column | Type | Meaning |
| --- | --- | --- |
| `id` | uuid PK | |
| `question_id` | uuid FK questions | |
| `subject_id` | uuid | Carried to prove subject agreement |
| `curriculum_item_id` | uuid FK curriculum_items | **Must be an item of type `skill`** |
| `syllabus_version_id` | uuid | Carried to prove version agreement |
| `mastery_level_id` | uuid FK curriculum_mastery_levels, null | Must belong to this skill |
| `classification_role` | text | `primary`, `secondary` |
| `cognitive_process` | text, null | `recall`, `procedure`, `application`, `reasoning` |
| `confidence` | numeric(5,4), null | Only set when proposed by a model |
| `proposed_by` | text | `human`, `model` |
| `classification_reason` | text | Readable rationale |
| `review_status`, `reviewed_by`, `reviewed_at` | | Same pattern |

Constraints — this is where the schema does the real work:

- `FOREIGN KEY (curriculum_item_id, syllabus_version_id) REFERENCES curriculum_items(id, syllabus_version_id)` — uses the existing composite key, so a question can never be mapped to a skill from a different syllabus version.
- `FOREIGN KEY (mastery_level_id, curriculum_item_id) REFERENCES curriculum_mastery_levels(id, curriculum_item_id)` — uses the existing `UNIQUE (id, curriculum_item_id)`, so the level always belongs to the mapped skill. v1.1 states this as a rule; here the database enforces it.
- `FOREIGN KEY (question_id, subject_id) REFERENCES questions(id, subject_id)` plus a check that the syllabus version belongs to the same subject, so a Mathematics question cannot be classified under an English skill.
- **Skill-only:** add `UNIQUE (id, item_type)` to `curriculum_items`, then hold a generated column `target_item_type text GENERATED ALWAYS AS ('skill') STORED` here and
  `FOREIGN KEY (curriculum_item_id, target_item_type) REFERENCES curriculum_items(id, item_type)`. This blocks classification against a topic, a subtopic, or either of the two structural containers the syllabus import created — declaratively, with no trigger.
- One approved primary per question: partial unique index on `(question_id) WHERE classification_role = 'primary' AND review_status = 'approved'`.

### 4.7 `misconceptions`

| Column | Type | Meaning |
| --- | --- | --- |
| `id` | uuid PK | |
| `subject_id` | uuid FK subjects | |
| `code` | text | `sign-error`, `factor-pair-sum` |
| `name`, `description` | text | What the student is doing |
| `remediation_note` | text, null | What usually fixes it |
| `curriculum_item_id` | uuid FK, null | Where it usually appears |
| `review_status`, `reviewed_by`, `reviewed_at` | | Same pattern |

`UNIQUE (subject_id, code)`.

### 4.8 `question_statistics` — derived, rebuildable

| Column | Type | Meaning |
| --- | --- | --- |
| `question_version_id` | uuid PK FK | One row per version |
| `attempt_count`, `correct_count` | integer | |
| `correct_rate` | numeric(5,4) | Generated |
| `median_response_ms`, `p90_response_ms` | integer | Calibrates `expected_seconds` |
| `discrimination` | numeric(6,4), null | Point-biserial against subject ability |
| `calibrated_difficulty` | numeric(6,4), null | The engine's `b`, replacing the level prior once there is evidence |
| `option_share` | jsonb | Share choosing each option — the distractor analysis |
| `flag_state` | text | `none`, `too_easy`, `too_hard`, `low_discrimination`, `reported` |
| `stats_version`, `computed_at` | text, timestamptz | Which job version produced this |

Never written by the request path. Recomputed nightly and rebuildable from
`attempts`, per ADR-0006.

### 4.9 `question_reports`

| Column | Type | Meaning |
| --- | --- | --- |
| `id` | uuid PK | |
| `question_version_id` | uuid FK | |
| `reported_by_student_id` / `reported_by_reviewer_id` | uuid, null | One of the two |
| `reason` | text | `wrong_answer`, `ambiguous`, `typo`, `image_missing`, `off_syllabus`, `other` |
| `detail` | text, null | |
| `attempt_context` | jsonb, null | What the student saw |
| `status` | text | `open`, `triaged`, `fixed`, `rejected` |
| `resolved_by`, `resolved_at`, `resolution_note` | | |

The spec's 48-hour triage target is measured from `created_at`.

### 4.10 `question_import_batches`

| Column | Type | Meaning |
| --- | --- | --- |
| `id` | uuid PK | |
| `source_document_id` | uuid FK, null | The paper or answer key |
| `import_file_uri`, `import_file_sha256` | text | The spreadsheet or JSON actually imported |
| `format_version` | text | Matches the ingestion contract |
| `row_count`, `created_count`, `skipped_count`, `rejected_count` | integer | Result |
| `rejected_rows` | jsonb | Row number and reason, for the person fixing the file |
| `imported_by`, `imported_at` | uuid, timestamptz | |

Same discipline as the syllabus loader: hash the file, derive IDs deterministically,
re-running changes nothing.

## 5. Two gates: insert versus approve

Authors need to save incomplete work; students must never see it. So constraints
split in two:

**Enforced at insert** (always true): foreign keys, subject and version agreement,
one correct option, valid ranges, non-empty text.

**Enforced at approval** (a trigger on the transition to `approved`):

- at least four options for `mcq_single`, exactly one correct, and `option_count` equal to the options actually stored,
- `solution_steps` and `hints` non-empty,
- every asset has `alt_text` and a verified licence,
- the passage, if any, is itself approved with a verified licence,
- `expected_seconds` and `mastery_level_number` set,
- an author recorded, and `reviewed_by <> authored_by`.

Classification is deliberately **not** in this gate: a reviewer approving the wording
of an item should not be blocked by the mapping workflow, and vice versa. An
approved primary classification is instead required by `deliverable_questions`, so an
item with no approved skill simply never reaches a student.

## 6. What the engine reads

The learning engine (`packages/engine`) needs exactly five things per item:

| Engine input | Source |
| --- | --- |
| Primary skill | `question_classifications` where role is primary and approved |
| Level 1–5 | `question_versions.mastery_level_number`, overridden by `question_statistics.calibrated_difficulty` once evidence exists |
| Expected seconds | `question_versions.expected_seconds` — the guess rule compares against it |
| Chance level | `1 / question_versions.option_count` |
| Pool | `questions.usage_pool` |

**This changes the engine.** `packages/engine` currently hard-codes
`CHANCE_LEVEL = 0.25` for four options. If NECO items have five options, or the two
subjects differ, chance level must come from the item. That is a rule change:
change it in Python, mirror it in TypeScript, regenerate the parity vectors
(ADR-0005), and bump `ENGINE_VERSION`.

## 7. Delivery and safety views

Mirroring the existing `published_curriculum_scope`:

**`deliverable_questions`** — what may be shown to a student:

```
approved question version
  AND question not retired
  AND approved primary classification
  AND that skill visible in teachable_skills (approved, current syllabus, supported)
  AND every asset licence verified
  AND (origin <> 'past_paper' OR source document approved, licence verified,
       student_delivery_permission true)
  AND passage (if any) approved and licence verified
```

**`candidate_question_payload`** — the same rows with `numeric_answer`,
`accepted_answers`, `solution_steps`, `marking_scheme`, `is_correct` and
`misconception_id` **removed**. The student-facing role gets `SELECT` on this view
and on nothing else in the question tables. Answer keys never travel to the client;
marking happens server-side.

Two further rules the views cannot express, which belong in the selection code and
its tests:

- A held-out item is never returned to practice, revision or the check-up.
- A student never sees the same held-out item in two assessment forms.

## 8. Deterministic IDs and idempotent import

The syllabus loader derives UUIDs from a namespaced hash of a stable key. Questions
should do the same:

```
uuid_for("question:" + source_document_sha256 + ":" + paper_code + ":" + question_number + ":" + part_label)
uuid_for("question-version:" + question_id + ":" + version)
```

Re-importing a corrected spreadsheet then updates drafts in place, skips unchanged
rows, and never silently alters an approved version — it opens a new one.

## 9. Phase 1 versus later

**Build now (S1–S3):** questions, versions, options, passages, assets,
classifications, misconceptions, reports, import batches, statistics, both views.

**Later (Phase 2, with generation):** `generation_profiles`,
`generation_profile_questions`, keeping v1.1's design and its `limited_evidence`
status. Nothing in Phase 1 blocks them; `questions.generation_profile_id` is
reserved now so generated items never have to be retrofitted.

**Not in this document:** attempts, responses, diagnoses, mastery events and plans.
They reference `question_versions` and are specified in
[product-spec.md §12](product-spec.md).

## 10. Decisions

| # | Decision | Settled | How the schema carries it |
| --- | --- | --- | --- |
| 1 | Pilot exam | **WAEC WASSCE, objective papers** — Maths Paper 1, English Papers 1 and 3 (ADR-0015, superseding the NECO choice in ADR-0014) | `exam_papers.response_mode`; theory may be stored but is not `adaptive_eligible` |
| 2 | Marking | Kept general; POC implements automatic marking only | `response_format` + `marking_method`, with `adaptive_eligible` generated from them |
| 3 | Scoring | Each subject reported **out of 100 marks**; no grade bands modelled | `exam_papers.score_out_of` (default 100); marks per question = `score_out_of / question_count` |
| 4 | Options per item | Item-specific, never assumed | `question_versions.option_count`, validated against the option rows at approval; engine uses `1 / option_count` |
| 5 | Theory content in Phase 1 | Author and store it; keep it out of adaptive practice | `adaptive_practice_questions` filters on `adaptive_eligible` |
| 6 | Classification level | On the question, not the version | `question_classifications.question_id`; a material content change needs re-review |
| 7 | Paper structure | Recorded from a source, never guessed | `values_confirmed` + `confirmation_note`; a paper cannot be `supported` until confirmed |

Still open, and not blocking the migration:

| # | Question | Needed by |
| --- | --- | --- |
| a | Held-out pool size per subject | Before the first mock is assembled |
| b | Passage rights: commissioned originals or licensed extracts | Before English comprehension authoring |
| c | The ingestion spreadsheet format (one row per answerable part) | Before bulk import; fills `question_import_batches.format_version` |
| d | Named reviewers per subject — the two-person rule needs at least two | Before authoring starts |
| e | NECO grade boundaries, if we ever report grades rather than marks | Only if the product promises a grade |

## 11. Acceptance checks for this schema

| Check | Pass condition |
| --- | --- |
| Skill only | A classification against a topic, subtopic or structural container is rejected by the database, not by application code. |
| Level belongs to skill | A level from another skill is rejected by the foreign key. |
| Version agreement | A question cannot be classified against a skill from a different syllabus version. |
| One primary | A second approved primary classification on a question is rejected. |
| Immutability | Updating the stem of an approved version fails; correcting it creates version n+1 and leaves earlier responses pointing at what was asked. |
| Two people | A version approved by its author is rejected. |
| Pool isolation | No practice or check-up query can return a held-out item; a generated item cannot be placed in a held-out or diagnostic pool. |
| Answer safety | The candidate role can read the question payload view and nothing else; no key, solution or correctness flag appears in it. |
| Rights | A question from a source document without `student_delivery_permission` never appears in `deliverable_questions`. |
| Idempotent import | Re-importing the same file creates nothing and rejects nothing. |
| Engine inputs | Every deliverable item yields a primary skill, a level, expected seconds, an option count and a pool. |
