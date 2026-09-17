# Score Pilot — Engineering Delivery Plan

**Plan period: 14 September 2026 – 12 September 2027 · two-week sprints · 26 sprints · 7 milestones**

The plan is organised by technical capability. Its dates are anchored to one external constraint: **UTME 2027** (assumed late April–mid May; move the plan when JAMB publishes dates). The code freeze sits two weeks before that window.

<div id="timeline"></div>

## Planning assumptions

- **Team:** tech lead, 2 full-stack engineers, 1 backend engineer who leans toward data work, 1 half-time product designer.
- **Cadence:** sprints start Monday and end with a Friday demo of working software on staging.
- **Stack decisions** (framework, database, hosting) are made in S0 and recorded as architecture decision records (ADRs). The plan doesn't assume a specific stack.
- **Scope shrinks, dates don't.** If a sprint slips, cut lower-priority scope. Protect three releases:
  - **v0.1** — limited release, S4
  - **v1.0** — pilot release, S8
  - **code freeze** — S15

## External dependencies

These are outside engineering but block specific sprints. The tech lead tracks them weekly.

| Dependency | Needed by | Blocks |
|---|---|---|
| Skill taxonomies and prerequisite graph for Maths and English (subject leads) | S1 | Curriculum import, engine fixtures |
| Approved question volumes per product spec §11 | S4, S7, S10, S14 | Releases, mock forms, coverage checks |
| Held-out question pools | S8 | Mini-mocks |
| Confirmed UTME configuration (question counts, time allowance) | S0 | Exam config seed |
| Legal sign-off on consent, research and results-capture screens | S7, S15 | v1.0 release, results capture |
| Access to a school computer lab for load testing | S11 | CBT lab test |

## Working agreements

### Definition of Ready

A story enters a sprint only when it has:

- the spec section it implements,
- acceptance criteria written as checkable statements,
- designs for any new screen,
- API contract or schema changes described,
- dependencies named,
- analytics events listed,
- any privacy impact noted.

### Definition of Done

- Code reviewed; unit and integration tests pass in CI.
- Acceptance criteria verified by someone other than the builder.
- Database migrations included and reversible.
- Permission checks tested for every role that can reach the feature.
- Analytics events emitted and visible in the events dashboard.
- Works on the reference low-end Android device (2 GB RAM) and in desktop Chrome.
- Offline behaviour tested where the feature runs offline.
- Error states implemented with clear, actionable copy.
- Metrics, logs and alerts in place for new services.
- **Engine changes:** the golden student set passes 100% in CI, and `engine_version` is bumped.

### Golden student test set

A set of fixed student profiles, each with the recommendation subject experts expect. Examples:

- strong student,
- weak student,
- weak prerequisite,
- forgotten skill,
- careless student,
- slow but accurate,
- guesser,
- exam in 3 weeks,
- strong on rare topics but weak on common ones.

Every change to the engine runs against the set in CI, and a failure blocks the merge. It starts with 10 profiles (S2) and grows to ≥ 50 (S7).

---

## M0 · Platform and content foundations

**Sprints S0–S1 · 14 Sep – 11 Oct 2026**

**Goal:** a deployable platform with authentication, roles, exam configuration, and the tooling to author, review and version curriculum and questions.

**Exit criteria**
- [ ] CI/CD deploys every merge to staging; production environment provisioned
- [ ] Authentication and role-based access enforced by automated tests
- [ ] Exam configuration validated against a schema and loaded from seed data
- [ ] Curriculum and question authoring, review and versioning working end to end on staging
- [ ] ADRs recorded for stack, hosting, offline strategy and maths rendering

### S0 · 14 Sep – 27 Sep · Platform setup, auth and exam configuration

**Goal:** a skeleton app in staging with sign-in, roles and exam configuration.

**Scope**
- Repository, branching strategy, CI (lint, type check, tests), automatic deploys to staging.
- ADRs: frontend and PWA approach, backend, database, hosting, maths rendering.
- Authentication (phone or email plus school join code); sessions; password-less sign-in option.
- Roles: student, teacher, school admin, content author, subject lead, research analyst, platform admin.
- `exams.config` JSON schema (sections, question counts, time allowance, score scale, goal types, pass rules, retake cycle) with validation; UTME seed.
- Error tracking, structured logs, uptime monitoring.

**Acceptance criteria**
- [ ] Merging to main deploys to staging within 15 minutes without manual steps
- [ ] Automated tests show each role blocked from other roles' routes and APIs (401/403 as appropriate)
- [ ] Invalid exam configs (missing sections, negative counts, unknown goal type) are rejected with field-level errors
- [ ] UTME seed loads English 60 items and other subjects 40, each out of 100; unconfirmed values carry a `confirmed: false` flag
- [ ] An unhandled server error appears in error tracking with request ID and user role, and no personal data
- [ ] ADRs for the five decisions are merged in the repository

### S1 · 28 Sep – 11 Oct · Curriculum and authoring tools

**Goal:** subject experts can build the curriculum and write, review and publish versioned items.

**Scope**
- Tables and admin screens for syllabus versions, topics, subtopics and skills; within-topic weights; L1–L5 level descriptions.
- `skill_prerequisites` with strength and required mastery; cycle detection on save.
- `topic_weights` storing historical share, expert share, alpha and sources.
- Item authoring:
  - stem and options with maths notation (live preview),
  - key,
  - ordered solution steps,
  - hints,
  - level, primary skill, archetype,
  - misconception for each wrong option,
  - pool, source and rights, expected seconds.
- `passages` shared by several English items.
- Review workflow Draft → In review → Approved → Live → Retired; author ≠ reviewer enforced.
- Immutable `item_versions`: editing a live item creates a new version.
- Code-based answer check (e.g. SymPy service) for numeric and algebraic Maths items.
- Bulk import from CSV/JSON with validation report.

**Acceptance criteria**
- [ ] Saving a prerequisite edge that would create a cycle is rejected, and the error names the cycle path
- [ ] Topic weights within a syllabus version must sum to 1 ± 0.001 before the version can be published
- [ ] An item can't be approved without primary skill, level, key, worked solution, pool and rights, or by its own author (API and UI tests)
- [ ] Editing a live item creates version n+1; version n stays readable and unchanged
- [ ] For a numeric Maths item whose key disagrees with the code-computed answer, the reviewer sees a blocking warning
- [ ] Importing 500 items reports every invalid row with row number and field, and imports the valid rows
- [ ] Maths notation renders identically in the authoring preview and in the student practice view (visual test on 20 reference items)

---

## M1 · Core practice loop · v0.1

**Sprints S2–S4 · 12 Oct – 22 Nov 2026**

**Goal:** students can onboard, take the check-up, practise at adaptive difficulty with worked solutions, work offline, and follow a simple Today plan. Shipped as release v0.1.

**Exit criteria**
- [ ] v0.1 deployed to production behind school join codes
- [ ] Offline practice with loss-free sync proven in automated and device tests
- [ ] Mastery engine v1 matches reference calculations
- [ ] Crash-free sessions ≥ 99% and zero lost attempts in sync reconciliation during the first production week

### S2 · 12 Oct – 25 Oct · Event log, onboarding and mastery engine

**Goal:** attempts are stored reliably, and the engine turns them into skill ratings.

**Scope**
- Append-only `attempts` table and ingestion API; client-generated UUIDs so repeated syncs don't duplicate; server and client timestamps.
- Onboarding: exam, full subject combination (covered subjects flagged), target out of 100 per covered subject, study days and minutes, join code.
- `consents` and a consent gate: no attempts stored beyond the session without a recorded consent.
- Mastery engine v1:
  - Elo update;
  - rules for hints, guesses and viewed solutions;
  - displayed mastery, bands and confidence;
  - forgetting half-life fields.
- Exam weight service: expected questions per topic and per skill; marks per question from exam config.
- Golden student harness (fixture format, CI runner) with the first 10 profiles.
- `engine_version` stamped on every derived record.

**Acceptance criteria**
- [ ] Sending the same attempt twice with the same client UUID stores exactly one record; the second request returns 200 with the existing ID
- [ ] Without a consent record, the API accepts attempts for in-session feedback but doesn't persist them (integration test)
- [ ] A student with English, Biology, Chemistry and Physics gets `covered: [english]` and no total-target field in the onboarding API
- [ ] Rating updates match hand-calculated reference values for 20 fixture attempts (tolerance 1e-6)
- [ ] A correct answer with a hint raises θ less than an unaided one; a correct answer after viewing the solution leaves θ unchanged
- [ ] Skills with < 3 scored attempts return `band: not_assessed` and no percentage
- [ ] Marks per question are read from config (Maths 2.5, English 1.67), not hard-coded (test swaps config values)

### S3 · 26 Oct – 8 Nov · Check-up, adaptive practice and offline

**Goal:** a short adaptive check-up seeds ratings; practice serves the right item with feedback, including offline.

**Scope**
- Check-up generator: 12–15 items per subject weighted by topic share, starts at L2, adapts within topic, resumable.
- Practice item selector: target P(correct) ≈ 0.7; two-up/two-down level rule; 14-day repeat exclusion; archetype run limit.
- Feedback view: stored hint, step-by-step solution, misconception note.
- Item problem reports feeding the review queue.
- Service worker and local store: prefetch the next 40 items with solutions; queue attempts; background sync with retry and backoff.
- Pool isolation: held-out and check-up items excluded from practice at query level.

**Acceptance criteria**
- [ ] The generator returns 12–15 items per subject covering every in-scope topic group at least once (property test over 100 random curricula)
- [ ] Golden: the strong profile reaches L4 within 6 items in a topic; the weak profile gets nothing above L2 after two consecutive L2 misses
- [ ] The selector never returns an item the student saw in the last 14 days unless called with `retry=true`
- [ ] An automated test confirms no practice or check-up query can return a held-out item
- [ ] With the network off after a session starts, 20 items can be completed; on reconnect all 20 attempts sync with their original client timestamps and correct order
- [ ] Killing the app mid-session loses no answered attempts (device test)
- [ ] On the reference device, the next item renders in < 300 ms from the local store

### S4 · 9 Nov – 22 Nov · Today plan v0, teacher and admin views, v0.1 release

**Goal:** ship v0.1.

**Scope**
- Plan generator v0: ranks in-scope skills by marks gained per minute for 15, 30 or 60 minutes (no prerequisites or reviews yet); stored plans and plan items with reason codes.
- Teacher view v0: class roster, 7-day activity, class topic-mastery heatmap.
- School admin: CSV student import, class assignment, join-code management.
- Analytics event schema (versioned), event pipeline and operations dashboard (activity, attempts, sync failures, errors).
- Release checklist: production config, backups, alerts, rollback procedure.

**Acceptance criteria**
- [ ] A 30-minute plan contains 2–4 activities totalling 25–35 minutes, each with a reason code and display copy
- [ ] CSV import of 1,000 rows completes in < 30 s and reports invalid and duplicate rows by row number
- [ ] Teachers can query only their own classes (API permission tests), and heatmap values match a recalculation from raw attempts
- [ ] A nightly sync reconciliation job compares client attempt counts with stored attempts and alerts on any gap
- [ ] Database backup restores to a fresh environment in a rehearsal, with documented time to restore
- [ ] v0.1 tagged, deployed to production, and rollback rehearsed on staging

---

## M2 · Personalisation engine

**Sprints S5–S7 · 23 Nov 2026 – 3 Jan 2027**

**Goal:** the full marks-per-minute planner with prerequisite repair, spaced reviews, planner rules, the help ladder and grounded AI help, verified by the golden student set and a load test.

**Exit criteria**
- [ ] Golden student set ≥ 50 profiles, 100% passing, blocking merges in CI
- [ ] Planner simulation suite passing (coverage, balance, review caps, success mix)
- [ ] AI help grounded with an answer-mismatch fallback, and per-student cost caps enforced
- [ ] Load test at pilot scale passed

### S5 · 23 Nov – 6 Dec · Opportunity and priority engine

**Goal:** rank study activities by expected marks gained per minute, and substitute prerequisites when they block progress.

**Scope**
- Decayed mastery (half-life retention with a chance-level floor).
- Gain calculation, credit for unblocking later skills, blocked-skill detection.
- Prerequisite substitution at most 2 levels back.
- `opportunities` table stamped with `engine_version`; recalculated on new attempts and nightly.
- Reason codes and copy templates.
- "Where your marks are" screen showing high, medium or low value per skill.
- Engine decision log: inputs and outputs per plan, for debugging.

**Acceptance criteria**
- [ ] Golden: Quadratics 30%, Factorisation 25%, Basic algebra 82% → first activity is Factorisation with `PREREQ_REPAIR`
- [ ] Golden: of two equally weak skills, the high-share 20-minute skill ranks above the low-share 30-minute skill
- [ ] Golden: a low-share skill unblocking ≥ 3 blocked high-share skills ranks above a standalone high-share skill of equal weakness
- [ ] Property test on 1,000 random prerequisite graphs: substitution never goes deeper than 2 levels and always terminates
- [ ] The same state and `engine_version` produce byte-identical rankings
- [ ] Opportunities for one student recalculate in < 200 ms (p95) for a 250-skill curriculum

### S6 · 7 Dec – 20 Dec · Planner rules, review state and help ladder

**Goal:** daily plans that respect time, subject balance and memory, and a help ladder matched to the student's state.

**Scope**
- `review_state` with half-life updates; due-review selection capped at 25% of a session.
- Planner rules:
  - subject balance ≥ 30%,
  - 14-day coverage floor,
  - ≤ 30 consecutive minutes on one skill,
  - ≥ 30% of items at P(correct) 0.65–0.85.
- Daily plan regeneration with no backlog.
- Help ladder state machine: check again → hint → worked solution → micro-lesson and guided ladder → prerequisite probe and repair, with stop rules and time boxes.
- Micro-lesson player (stored content).
- Planner simulation harness running multi-week scenarios against golden profiles.

**Acceptance criteria**
- [ ] A student inactive for 4 days receives a regenerated plan with no overdue items, and reviews take ≤ 25% of planned minutes
- [ ] 14-day simulation: every in-scope topic below Exam-ready gets at least one activity
- [ ] Simulation: each subject of a two-subject student gets ≥ 30% of weekly minutes
- [ ] Golden: mastery ≥ 80% with one wrong answer → `check_again`; mastery < 40% or 3 wrong in a session → `micro_lesson` then `guided_ladder`
- [ ] Guided ladder returns `success` only after 3 correct in a row, including ≥ 1 at L3, without hints (state-machine unit tests cover every transition)
- [ ] Review success doubles half-life (cap 60 days); failure halves it (floor 1 day)
- [ ] Simulation: ≥ 30% of served practice items fall in predicted P(correct) 0.65–0.85

### S7 · 21 Dec – 3 Jan · Grounded AI help, cost controls, load test (reduced holiday capacity)

**Goal:** add "Explain this differently" safely and make the system ready for pilot scale.

**Scope**
- AI help service: prompt built from stored solution, skill note and chosen option; no student names in prompts; provider no-training setting.
- Final-answer extraction and comparison with the item key; fall back to the stored solution on mismatch.
- `ai_requests` logging of tokens, cost and latency; per-student daily cap; response caching.
- Assessment lock: AI endpoints refuse check-up and held-out items.
- Load and soak tests.
- Golden set expanded to ≥ 50 profiles.

**Acceptance criteria**
- [ ] Across 100 Maths items, every AI explanation reaches the stored answer or is replaced by the stored solution (automated evaluation run in CI nightly)
- [ ] AI endpoints return 403 for any item in the check-up or held-out pool
- [ ] A student past their daily cap gets the stored solution with a clear message, and no provider call is made
- [ ] The cost dashboard shows cost per active student per day, with an alert above the configured threshold
- [ ] Load test: 600 concurrent students practising, p95 API latency < 500 ms, error rate < 0.5%
- [ ] 8-hour soak test shows no memory growth or queue backlog
- [ ] Golden set ≥ 50 profiles, 100% passing; CI blocks engine merges on failure

---

## M3 · Assessment and experimentation · v1.0

**Sprints S8–S10 · 4 Jan – 14 Feb 2027**

**Goal:** held-out mini-mocks, an experiment framework for the two-group pilot design, mixed and timed practice, and score ranges with a calibration pipeline. Shipped as release v1.0.

**Exit criteria**
- [ ] v1.0 released with experiment groups enforced server-side
- [ ] Mini-mock engine robust to backgrounding and connection loss
- [ ] Score range service live with display rules enforced by the API
- [ ] Calibration pipeline produces a reproducible report from raw events

### S8 · 4 Jan – 17 Jan · Experiment framework, mini-mocks, v1.0 release

**Goal:** run two product variants safely and deliver timed mini-mocks.

**Scope**
- `research_assignments`: class-level or student-level randomisation with a stored seed; assignments can't be changed.
- Feature entitlements per group: Group B hides My Plan and opportunities at API and UI level.
- Mock form builder: draws from the held-out pool; no item reused across a student's forms.
- Mini-mock runner:
  - server-authoritative start and end time,
  - local timer that survives backgrounding and offline,
  - answers saved locally,
  - submit on reconnect.
- Analysis pipeline scaffold: versioned SQL/notebooks in the repository reading pseudonymised exports.

**Acceptance criteria**
- [ ] Rerunning randomisation with the same seed and roster produces identical assignments, and assignments can't be updated through any API
- [ ] Group B requests to plan and opportunity endpoints return 403; both groups get identical item and solution responses
- [ ] No student receives the same held-out item on two forms (property test across 500 simulated students × 3 forms)
- [ ] A mock started online, continued offline for 10 minutes and backgrounded twice submits all answers with correct per-item timings on reconnect
- [ ] Submissions after the server end time (plus 60 s grace) are flagged as late and recorded, not silently accepted
- [ ] The pseudonymised export contains no names, phone numbers or emails (automated schema check)
- [ ] v1.0 tagged, deployed and rollback rehearsed

### S9 · 18 Jan – 31 Jan · Mixed and timed practice, engagement tracking

**Goal:** exam-speed practice and the data to see who is falling behind.

**Scope**
- Mixed set generator with topic hidden and a limit on consecutive items from one topic.
- Timed drills with per-item speed classification from expected seconds.
- Weekly commitment tracker (no streak resets).
- In-app notification service.
- Teacher "inactive students" list and weekly class summary.
- Retention and engagement metrics tables (`metrics_daily`, `metrics_weekly`) computed from events.

**Acceptance criteria**
- [ ] Mixed sets never return topic metadata to the client before an answer, and never place > 2 consecutive items from one topic
- [ ] Each timed-drill response is classified as fast/slow × correct/wrong, based on the item's expected seconds (unit tests at boundaries)
- [ ] The inactive list returns students with no study session in 7 days and matches a direct event query
- [ ] Daily and weekly metrics jobs are idempotent: running twice for the same day produces identical rows
- [ ] Notifications respect quiet hours (default 21:00–07:00 Africa/Lagos)

### S10 · 1 Feb – 14 Feb · Score range service and calibration pipeline

**Goal:** score ranges that appear only when evidence supports them, with a way to check them.

**Scope**
- Score range service: model estimate plus recent mock blend, width from calibration residuals (default ±12).
- Unlock rules enforced server-side.
- `score_ranges` table with history.
- Calibration job comparing earlier ranges with later mock scores; adjusts width parameters by version.
- Mock report v1: per-topic results and likely error causes, with the rule shown for each.

**Acceptance criteria**
- [ ] The API returns no range until the student has ≥ 1 completed mini-mock and ≥ 150 scored attempts in the subject; the locked response includes the unlock requirements
- [ ] The API never returns a total score unless all of the student's subjects are covered
- [ ] Ranges recalculate only on mock submission or the weekly job, never on individual attempts (test asserts no writes to `score_ranges` from the attempt path)
- [ ] The calibration job reports interval coverage and writes new width parameters under a new version, without changing existing ranges
- [ ] Mock report likely-cause labels are reproducible from stored inputs and include the rule identifier

---

## M4 · Exam simulation and reliability

**Sprints S11–S15 · 15 Feb – 25 Apr 2027**

**Goal:** full CBT mock simulation, the mock repair loop, exam-phase planning, content quality automation, and a stable platform through the exam window.

**Exit criteria**
- [ ] CBT simulator passes keyboard, auto-submit and shared-connection lab tests
- [ ] Mock mistakes flow into plans automatically within 24 hours
- [ ] Item statistics and auto-flagging running nightly
- [ ] Code freeze in place, with hotfix process and on-call rota

### S11 · 15 Feb – 28 Feb · CBT mock simulator and scheduled mocks

**Goal:** a realistic computer-based mock that works in school labs and on phones.

**Scope**
- Full mock runner:
  - configured sections and item counts,
  - pro-rated time allowance,
  - question palette,
  - flag for review,
  - subject switching,
  - keyboard controls,
  - auto-submit.
- Teacher-scheduled mock windows per class.
- Low-bandwidth mode: preload the whole form before the start, then minimal traffic during the mock.
- Guardian digest delivery service (channel adapter; opt-in required; templated content).

**Acceptance criteria**
- [ ] A–D selects an answer, N/P moves next/previous, F flags, S opens submit confirmation; a full mock can be completed without a mouse (automated end-to-end test)
- [ ] Auto-submit at 0:00 records unanswered items as `unanswered`, not `wrong`
- [ ] Starting a scheduled mock outside its window returns a clear error with the window times
- [ ] Lab test: 200 clients on one shared connection throttled to 2 Mbps complete a mock with zero lost answers
- [ ] The digest service sends nothing to a guardian without an opt-in record, and each send is logged with its template version

### S12 · 1 Mar – 14 Mar · Experiment switch and analysis pipeline

**Goal:** close the comparison window cleanly and move every student to the full product.

**Scope**
- Group switch job: move Group B to My Plan, generate plans from existing ratings, record `switched_at`.
- Analysis pipeline for the week-8 comparison (versioned queries, reproducible output).
- Guardian digest content from metrics tables.
- Data quality checks on the experiment dataset (missing mocks, contamination signals such as shared devices).

**Acceptance criteria**
- [ ] The switch job is idempotent, completes for all Group B students, and each gets a plan generated from existing ratings
- [ ] Running the analysis pipeline twice on the same export produces identical outputs
- [ ] Data quality report lists students with missing mocks and accounts sharing a device fingerprint
- [ ] Digest content matches the metrics tables for 20 sampled students

### S13 · 15 Mar – 28 Mar · Mock repair loop

**Goal:** every missed mock question feeds the plan.

**Scope**
- Post-submit job: map wrong and unanswered items to skills and likely causes.
- `MOCK_REPAIR` plan items, with re-test items at the mock item's level.
- Mock report v2 with recoverable marks by topic and cause.

**Acceptance criteria**
- [ ] Within 24 hours of a mock submission, each wrong item's skill has a `MOCK_REPAIR` plan item, unless mastery is ≥ 80% and the cause is "likely careless"
- [ ] A repair completes only after ≥ 2 correct non-mock items at the mock item's level
- [ ] Recoverable marks per topic equal wrong items × marks per question from config (unit tests)
- [ ] Golden: a previously Strong skill with an expired half-life receives `REVIEW_DUE`, not a micro-lesson

### S14 · 29 Mar – 11 Apr · Exam-phase planning, item statistics, performance

**Goal:** the planner switches to exam mode, and bad items are caught automatically.

**Scope**
- Exam-phase planner rules:
  - ≤ 6 weeks to the exam: mixed and timed practice ≥ 40% of time;
  - final 3 weeks: don't start skills that need too much of the remaining time.
- Nightly `item_stats` job: correct rate, response time distribution, discrimination estimate.
- Auto-flagging rules into the review queue.
- Coverage report endpoint (items per skill by pool).
- Query and index tuning; caching for plan and opportunity reads.

**Acceptance criteria**
- [ ] Simulation: a student with ≤ 6 weeks to the exam spends ≥ 40% of weekly planned minutes on mixed and timed practice
- [ ] Golden: in the final 3 weeks, skills needing > 10% of remaining minutes to reach Exam-ready aren't started as new learning
- [ ] Items with correct rate < 10% or > 97% after ≥ 50 attempts are flagged automatically, with the statistic attached
- [ ] The coverage report returns items per skill per pool and matches a direct database count
- [ ] p95 latency for plan and opportunity reads < 150 ms at 600 concurrent users

### S15 · 12 Apr – 25 Apr · Code freeze and reliability

**Goal:** stability through the exam window.

**Scope**
- Code and engine freeze with a documented hotfix process.
- On-call rota and incident runbooks.
- Alert tuning.
- Results-capture feature built and kept disabled until opt-in is enabled:
  - opt-in form,
  - subject scores,
  - optional result-slip upload with verification method,
  - encrypted storage.
- Backup and restore rehearsal.

**Acceptance criteria**
- [ ] No `engine_version` change after the freeze except hotfixes logged with approver and reason
- [ ] Results-capture endpoints reject submissions without an opt-in record; uploaded slips are encrypted at rest and visible only to the research role
- [ ] Runbooks exist for sync failure, mock submission failure, AI provider outage and database failover, and each has been rehearsed once
- [ ] Uptime ≥ 99.5% measured through the window
- [ ] Restore rehearsal completes within the documented recovery time objective

---

## M5 · Data, calibration and multi-exam readiness

**Sprints S16–S19 · 26 Apr – 20 Jun 2027**

**Goal:** turn pilot data into a better engine, make it possible to rebuild any student's state, and prove that a second exam runs on configuration alone.

**Exit criteria**
- [ ] Replay framework rebuilds all derived state from events under any engine version
- [ ] Engine v3 recalibrated from pilot data, passing the golden set and replay comparisons
- [ ] Multi-exam schema supports item types, marking methods and goal types
- [ ] A second exam configured and running end to end without engine code changes

### S16 · 26 Apr – 9 May · Results ingestion and research data platform

**Goal:** clean, pseudonymised data ready for analysis.

**Scope**
- Enable the results-capture flow.
- Research data export: pseudonymised warehouse tables built from events, with a data dictionary.
- Access controls and audit log for research data.
- Retention and deletion jobs.

**Acceptance criteria**
- [ ] Each result record stores its verification method (`self_reported` or `slip_verified`) and links to the pseudonymised student ID only
- [ ] Every warehouse table is documented in the data dictionary, and a CI check fails if a column is undocumented
- [ ] Every research data access is written to an audit log with user, query and timestamp
- [ ] A deletion request removes a student's personal data from production and warehouse within the configured window (end-to-end test)

### S17 · 10 May – 23 May · Replay framework and engine v3

**Goal:** rebuild state from events and learn engine parameters from real data.

**Scope**
- Event replay: rebuild `skill_ratings`, `review_state`, `opportunities` and `score_ranges` for any `engine_version` into an isolated schema.
- Fit parameters from pilot data:
  - item difficulty,
  - session gain `g` per skill cluster,
  - session minutes,
  - score range widths.
- Engine v3 behind a version flag.
- Offline evaluation: compare v2 and v3 predictions on held-out mock outcomes.

**Acceptance criteria**
- [ ] Replaying all pilot events under v2 reproduces stored v2 ratings exactly (tolerance 1e-9)
- [ ] Parameter fitting scripts are versioned and their outputs reproducible from the same data snapshot
- [ ] On held-out mocks, v3's prediction error is at least as low as v2's, and v3 isn't released if error is higher
- [ ] Golden set passes 100% under v3, and any intentional expectation changes are reviewed in the PR

### S18 · 24 May – 6 Jun · Multi-exam data model

**Goal:** the schema and services are ready for exams that aren't UTME.

**Scope**
- `item_type` (mcq, numeric, multi_part, written, spoken) and `marking_method` (auto, rubric, ai_assisted, human) on item versions.
- Marking router: MCQ and numeric auto-marking implemented; other types return "not supported".
- Goal types `maximise_score`, `reach_band` and `pass_all_papers` in the planner interface.
- `pass_rules` evaluation from exam config.
- Syllabus `effective_from` enforcement, so retired-law items drop out of selection.

**Acceptance criteria**
- [ ] Numeric items auto-mark with configured tolerance (unit tests for rounding and sign cases)
- [ ] Unsupported item types can be stored and authored, but are excluded from student selection with a logged reason
- [ ] Items tied to a syllabus version past its end date are never selected (integration test)
- [ ] Golden: for `pass_all_papers`, the planner prioritises the paper just below the pass mark over one safely above it

### S19 · 7 Jun – 20 Jun · Second exam through configuration

**Goal:** prove a new exam needs configuration and content, not engine code.

**Scope**
- Configure one Post-UTME format: sections, timing, scale.
- Seed curriculum and a test item set.
- End-to-end tests across onboarding, check-up, practice, plan and mock for the second exam.
- Configuration authoring UI for platform admins.

**Acceptance criteria**
- [ ] The second exam runs end to end with zero changes under engine source directories (CI diff check on the branch)
- [ ] End-to-end suite passes for both UTME and the second exam in the same CI run
- [ ] A platform admin can create and validate a new exam config in the UI, and invalid configs show field-level errors
- [ ] UTME golden set still passes 100%

---

## M6 · Scale and platform maturity · v2.0

**Sprints S20–S25 · 21 Jun – 12 Sep 2027**

**Goal:** multi-tenant self-serve organisations, entitlements, support for science subjects, 10× scale, and security hardening. Shipped as release v2.0.

**Exit criteria**
- [ ] Self-serve organisation setup and entitlements working end to end
- [ ] Science notation and diagrams supported in authoring and practice
- [ ] Load test at 10× pilot concurrency passing
- [ ] Security review findings of high severity resolved
- [ ] v2.0 released

### S20 · 21 Jun – 4 Jul · Multi-tenant self-serve organisations

**Goal:** a new organisation can be set up without engineering help.

**Scope**
- Organisation sign-up, teacher invites, class creation, CSV import, join codes, all self-serve.
- Tenant isolation checks.
- Admin onboarding checklist with empty states.

**Acceptance criteria**
- [ ] Automated tenant-isolation tests: no API returns another organisation's data for any role
- [ ] A new organisation completes setup through the UI alone in an end-to-end test
- [ ] Every admin screen has an empty state explaining the next step

### S21 · 5 Jul – 18 Jul · Entitlements and payments integration

**Goal:** access is controlled by entitlements, and payments update them automatically.

**Scope**
- Entitlements model (seats per organisation, individual passes, expiry).
- Payment provider integration with webhook verification.
- Idempotent webhook handling; reconciliation job.

**Acceptance criteria**
- [ ] Replayed or duplicated payment webhooks change entitlements exactly once
- [ ] Webhooks with invalid signatures are rejected and logged
- [ ] Reaching the seat limit blocks new students with a clear message and never locks out existing students mid-session
- [ ] Nightly reconciliation matches provider transactions with entitlements and alerts on mismatch

### S22 · 19 Jul – 1 Aug · Individual accounts and guardian consent flow

**Goal:** students outside organisations can sign up safely.

**Scope**
- Individual sign-up.
- Guardian consent flow for under-18s (verification via guardian contact).
- Referral code attribution in analytics.
- Automatic entitlement expiry after the configured exam season.

**Acceptance criteria**
- [ ] An under-18 individual account can't persist attempts until guardian consent is verified
- [ ] Referral attribution appears correctly in analytics for sign-ups from a referral link (end-to-end test)
- [ ] Access ends at the configured expiry date, and the student sees what happens to their data

### S23 · 2 Aug – 15 Aug · Science subject support

**Goal:** the authoring and practice stack handles Biology, Chemistry and Physics content.

**Scope**
- Chemical notation, units and significant figures in maths rendering.
- Image and diagram items with alt text and compressed delivery.
- Unit-aware numeric marking.
- Total-score display, enabled only when all of a student's subjects are covered.

**Acceptance criteria**
- [ ] 50 reference science items render identically in authoring preview, practice and CBT views (visual tests)
- [ ] Diagram images are ≤ 80 KB each after compression, and every image requires alt text before approval
- [ ] Numeric marking accepts equivalent units where configured (e.g. 0.5 m and 50 cm) and rejects wrong units
- [ ] The total score appears only for students whose subjects are all covered (API test)

### S24 · 16 Aug – 29 Aug · Scale and performance

**Goal:** ready for ten times pilot load.

**Scope**
- Partition or archive the attempts table.
- Read replicas or caching for heavy reads.
- Background job queue scaling.
- Offline sync batching.
- Cost profiling for infrastructure and AI.

**Acceptance criteria**
- [ ] Load test at 10× pilot concurrency: p95 API < 500 ms, error rate < 0.5%
- [ ] A CBT mock at 2,000 concurrent takers loses zero answers
- [ ] Attempts queries for a single student stay < 50 ms p95 with 50 million rows
- [ ] Infrastructure and AI cost per active student reported per day on the cost dashboard

### S25 · 30 Aug – 12 Sep · Security hardening and v2.0 release

**Goal:** a secure, recoverable v2.0.

**Scope**
- External or structured internal security review.
- Dependency and secret scanning in CI.
- Role access audit.
- Data retention jobs verified.
- Disaster recovery rehearsal.
- v2.0 release.

**Acceptance criteria**
- [ ] All high and critical security findings resolved, or accepted with a documented reason
- [ ] CI fails on committed secrets and on high-severity vulnerable dependencies
- [ ] Access audit confirms every role's permissions match the role matrix in product spec §7
- [ ] DR rehearsal restores production into a new environment within the recovery time objective
- [ ] v2.0 tagged, released and rollback rehearsed

---

## After September 2027 (not yet scheduled)

- Rubric-based and AI-assisted marking for written responses (needed for WAEC theory and ICAN).
- IRT item calibration once response volumes support it.
- Questions tagged with more than one skill, and knowledge tracing beyond Elo.
- Voice tutor prototype with streaming speech and whiteboard actions, only with a cost-per-minute budget.
- Native Android app if PWA limits appear.
- Teacher assignment of specific practice sets.
