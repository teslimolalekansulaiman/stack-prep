# Score Pilot — Product Specification

**Version 2.0 · 13 September 2026 · Status: draft for team review**

> **Exam scope changed after this version was written.** The POC targets **NECO SSCE
> External, objective papers**, with each subject reported out of 100 marks — see
> [ADR-0014](adr/0014-neco-objective-poc.md) and [question-schema.md](question-schema.md).
> Sections below that assume UTME (its four-subject total out of 400, its question
> counts and marks per question) are being corrected; where they disagree with
> ADR-0014, the ADR wins. The engine, planner, pools and score-range rules are
> unaffected — they were written to be exam-agnostic.

This version replaces the v1 concept notes. It keeps the core idea and changes the parts that didn't hold up under review: subject coverage, exam data, how priorities are calculated, score prediction, the AI tutor, the business model and proof of results.

## 1. Summary

Score Pilot is an adaptive exam-preparation product for Nigerian UTME candidates. It decides what each student should study next to gain the most exam marks from the time they have.

It is **not** a course that runs Topic 1 to Topic 30. It keeps a skill-level picture of each student, estimates where the most marks can be gained per minute of study, gives the smallest piece of help that fixes a gap, checks that the fix worked, and moves on.

**One-line promise:** *Every minute of study focused on the marks you're missing.*

**First market:** SS3 students preparing for UTME 2027, reached through their schools.
**First subjects:** Use of English (compulsory for every candidate) and Mathematics.
**First proof:** a randomised pilot in 3–5 schools, measured on practice mocks built from questions students never see in practice (held-out questions), before we scale.

## 2. What changed from v1

| Area | v1 concept | v2 decision | Why |
|---|---|---|---|
| Target score | A total UTME target (e.g. 300 of 400) | A target out of 100 per subject; a total only when all four of the student's subjects are covered | The MVP covers 2 of 4 subjects, and Maths isn't in many combinations (Medicine takes English, Biology, Chemistry, Physics) |
| Exam data | Skill-level frequency from ~20 years of past questions | How often each topic appears, blended with expert weights; experts split each topic's weight across its skills | Past papers are reconstructed and sparse (about 4 questions per skill), so skill-level counts are noise |
| Priority | Seven factors multiplied together | Expected marks gained per minute, plus credit for unblocking later skills, inside planner rules | Removes double counting; each part can be tested |
| Mastery | BKT, Elo, accuracy and IRT on several scales | One Elo-style rating per student per skill; one 0–100% scale with named bands | Simple, explainable, and can be recalculated from past answers |
| Diagnostic | 25–40 questions per subject | A 12–15 question check-up per subject; every practice question keeps refining the picture | Long tests lose students during onboarding |
| Score prediction | A daily predicted score from day one | A score range per subject, shown only after a mini-mock of held-out questions; updated after mocks | Avoids false precision and the inflated scores students get from learning the practice bank |
| AI tutor | Realtime voice and whiteboard at the centre | Text help based on stored, checked worked solutions; voice is a later experiment | LLMs make arithmetic slips; voice costs per minute don't fit naira prices |
| Generated questions | LLM-made variants | Variants built from templates, answers computed by code, human-approved, never used in assessments | Correctness |
| Customer | Students first; schools later | Schools first (school pays, students use it); a cheap student season pass second | Each student only uses us for one exam cycle; schools buy again every year |
| Proof | Assumed | A randomised pilot measured on held-out mocks | The core claim must be tested before scaling |
| Platform | Unspecified | Web app that works offline on low-end Android phones and in school computer labs | Connectivity and device reality |
| Data | Many tables, all stored permanently | A log of student events that is never edited is the source of truth; mastery and plans are derived from it and versioned | Everything can be rebuilt when the engine changes |
| Exams | UTME, WAEC and NECO from the start | UTME only; the data model is ready for other exams; new exams must pass set gates | Focus; other exams have different formats |

## 3. Problem and customers

**The student's problem.** A UTME candidate has a few months, four subjects and too much syllabus. Most prepare by grinding past questions topic by topic or by attending tutorial centres. Neither tells them which gaps cost the most marks, why they keep getting a question type wrong, or when to stop drilling something they already know.

**The school's problem.** Private secondary schools market their exam results. Teachers can't see which of 150 SS3 students is weak where, or who has stopped preparing, until results arrive.

| Customer | Who decides | What they get | What they pay for |
|---|---|---|---|
| School (primary) | Proprietor / principal | Better results they can advertise; class visibility for teachers | Per SS3 student, per school year |
| Parent (secondary) | Parent / guardian | A plan for their child, a weekly progress message | A season pass, November–April |
| Student (user) | — | A clear "do this next", visible progress, honest feedback | Usually doesn't pay directly |

## 4. Business model and go-to-market

- **Pilot (2026/27 session):** free for 3–5 schools in exchange for consent-based data use, the comparison design, and a case study if results are positive.
- **Schools (from the 2027/28 session):** a price per SS3 student per school year. *Price hypothesis to test: ₦8,000–₦15,000.* School budgets are set around July–September, so that is the sales season.
- **Student season pass (from November 2027):** a one-off pass for the exam season. *Hypothesis: ₦5,000–₦10,000.* Grown through word of mouth and referrals, not paid ads.
- **Seasonality:** usage peaks from January to April and collapses after UTME. Plan cash for the dead months.
- **Unit-cost rule:** AI cost ≤ **$0.25 per active student per month**. Any feature that breaks this needs a pricing answer before it ships.

**Revenue sketch (assumptions, not research):** 150 SS3 students × ₦10,000 = ₦1.5M per school per year. 100 schools ≈ ₦150M per year. Growing beyond that needs more subjects, school chains or state partnerships, or higher-value exams (see §17).

## 5. Product principles

1. **Marks per minute.** Every recommendation must explain how it gains marks for the time it costs.
2. **Smallest effective help.** Hint before solution, solution before lesson, lesson before prerequisite repair. Never restart a whole topic.
3. **Prove it, then move on.** A skill counts as "fixed" only after independent correct answers at exam level.
4. **Honest numbers.** Show a score only when there is evidence behind it, always as a range, and never claim to know exam questions in advance.
5. **The curriculum is authored by people, not AI.** Experts define topics, skills and prerequisites. The AI explains; it doesn't decide what to learn.
6. **Every answer is data.** Each attempt is logged with enough context to rebuild any student's state under a new engine version.
7. **Built for real conditions:** low-end phones, patchy data, shared school computer labs.
8. **Encourage, don't punish.** No overdue backlogs and no streak resets. Each session includes some winnable questions.

## 6. v1 scope

| In v1 (pilot) | Later, after evidence | Not doing |
|---|---|---|
| UTME Use of English and Mathematics | Biology, Chemistry, Physics, then arts and commercial subjects | Predicting specific exam questions |
| Onboarding with per-subject targets | Post-UTME, WAEC objective papers | WAEC/NECO theory marking |
| 12–15 question check-up | Voice tutor experiment | Deep knowledge tracing |
| Elo-style skill mastery | IRT item calibration | LLM-authored curriculum |
| Marks-per-minute planner with prerequisite repair | Parent app | Free-form AI-generated assessment items |
| Adaptive practice, hints, worked solutions, micro-lessons | ICAN Foundation / ATSWA or nursing licensing (gated) | TOEFL (IELTS would come first) |
| Grounded text AI help ("explain differently") | Tutorial-centre channel | |
| Spaced review, mixed and timed practice | | |
| Held-out mini-mocks and full CBT mocks | | |
| Mock repair loop | | |
| Score ranges after mocks | | |
| Teacher and school admin views | | |
| Parent weekly digest (opt-in) | | |
| Content authoring and review tools | | |

## 7. Users and roles

| Role | Can do | Can't do |
|---|---|---|
| Student | Onboard, check-up, plan, practice, mocks, see own progress | See other students, see group assignment |
| Teacher | See their classes' activity and mastery, schedule mocks, see inactive students | See other classes, edit content |
| School admin | Import students, manage classes and teachers, see school summary, billing (M6) | Edit content, see research assignments |
| Guardian | Receive opt-in weekly digest | Log in to student view (v1) |
| Content author | Write and tag questions, lessons, hints | Approve their own items |
| Subject lead (reviewer) | Review and approve content, own taxonomy and weights | — |
| Research analyst | See group assignments and pseudonymised data | Change student-facing state |
| Platform admin | Configure exams, manage users, feature flags | — |

## 8. Core learning loop

```
Onboarding (exam, full subject combination, per-subject targets, study time)
      ↓
Check-up: 12–15 questions per covered subject
      ↓
Skill ratings (with confidence)  ←──────────────────────────────┐
      ↓                                                        │
Opportunity engine: expected marks gained per minute           │
      ↓                                                        │
Today plan (fits the minutes available; follows planner rules) │
      ↓                                                        │
Practice → answer → smallest effective help → similar question │
      ↓                                                        │
Ratings updated → review scheduled ────────────────────────────┤
      ↓                                                        │
Mini-mock (held-out questions) → score range → mock repair ────┘
```

## 9. The engines

### 9.1 Mastery engine

One rating **θ** per student per skill. Each question has one **primary skill** and a difficulty **b**. Questions tagged with several skills wait until v2.

```
P(correct | student, item) = 1 / (1 + e^-(θ[skill] − b[item]))

θ ← θ + K · (outcome − P)
K = max(0.08, 0.4 / (1 + 0.1·n))          n = scored attempts on this skill

outcome = 1 correct · 0 wrong
          capped at 0.5 if a hint was used
          not scored if the solution was viewed before answering
K × 0.5 when the answer is a suspected guess (correct in < 25% of the item's expected time)
```

**Starting item difficulty** by level: L1 −1.5 · L2 −0.75 · L3 0 · L4 +0.75 · L5 +1.5. After 40 or more responses, b is recalibrated nightly in small steps.

**Displayed mastery** = P(correct on a reference L3 item) = σ(θ) × 100%. There is one scale everywhere:

| Band | Mastery | What the planner does |
|---|---|---|
| Not assessed | < 3 scored attempts | Probe |
| Weak | < 40% | Remediate |
| Developing | 40–65% | Guided practice |
| Exam-ready | 65–80% | Move on, schedule review |
| Strong | 80–90% | Mixed and timed practice only |
| Maintained | ≥ 90% | Occasional review |

**Evidence confidence:** *low* with < 3 attempts; *medium* with 3–7 attempts or a single level seen; *high* with ≥ 8 attempts across ≥ 2 levels. Low confidence is shown as such, never hidden behind a percentage.

**Forgetting.** Each skill has a review half-life *h* (starts at 3 days; doubles after a successful review, halves after a failed one; kept between 1 and 60 days). For planning:

```
r            = 2^(−days_since_last_success / h)
p_decayed    = p · r + 0.25 · (1 − r)          0.25 = chance level on a four-option (A–D) item
```

### 9.2 Exam weights

These are calculated at topic level. Skills get their share from expert weights.

```
share[topic]      = α · historical_share[topic] + (1 − α) · expert_share[topic]      α = 0.5 initially
E[q_topic]        = N_subject × share[topic]
E[q_skill]        = E[q_topic] × within_topic_weight[skill]      (expert-set; weights sum to 1 per topic)
marks_per_q       = 100 / N_subject
```

UTME configuration (**confirm against the current JAMB brochure**): Use of English N = 60 (1.67 marks per question); other subjects N = 40 (2.5 marks per question); each subject is scored out of 100, and the total is out of 400.

`historical_share` comes from tagged past-question sets. Counts are smoothed (add-one) and every source is recorded. Past papers since full CBT are partial and reconstructed, so weights are labelled *estimates* inside the product.

### 9.3 Opportunity and priority

```
p_now     = p_decayed(skill)
p_after   = p_now + g · (1 − p_now)            g = expected gain from one standard session (default 0.25, expert-adjusted, learned from data later)
gain      = E[q_skill] × marks_per_q × (p_after − p_now)  +  unlock
unlock    = Σ over blocked downstream skills d:  0.5 × strength(skill→d) × gain(d)
priority  = gain / session_minutes              session_minutes default 20 (expert range 10–30)
```

- A downstream skill is **blocked** when this prerequisite is below its `required_mastery` and the edge strength is ≥ 0.6.
- `g` and `session_minutes` are expert guesses at launch and replaced by measured learning gains as data arrives. Marks estimates are shown to students only as "high / medium / low value", never as "+4 marks".

### 9.4 Planner

The planner fills the student's chosen time (15 / 30 / 60 / 90 minutes) from the ranked opportunities, subject to these rules:

| Rule | Value |
|---|---|
| Due reviews go first, capped at | 25% of session minutes |
| Blocked skill | Replaced by its weakest blocking prerequisite (at most 2 levels back) |
| Subject balance | Each selected subject ≥ 30% of weekly minutes |
| Coverage floor | Every in-scope topic below Exam-ready gets ≥ 1 activity every 14 days |
| Same-skill limit | ≤ 30 consecutive minutes; stop when its gain drops below the next candidate's |
| Success mix | ≥ 30% of practice items at predicted P(correct) 0.65–0.85 |
| Exam phase (≤ 6 weeks left) | Mixed + timed practice ≥ 40% of time |
| Final 3 weeks | Don't start new skills that would need > 10% of remaining minutes to reach Exam-ready |
| Missed days | Plan regenerates from current state; no overdue backlog |

Each plan item stores `activity_type`, `skill_id`, `minutes`, `reason_code` and `engine_version`. Reason codes: `HIGH_VALUE_GAP`, `PREREQ_REPAIR`, `REVIEW_DUE`, `COVERAGE`, `MIXED_PRACTICE`, `SPEED`, `MOCK_REPAIR`, `MOCK`. Every reason has a plain-language sentence the student sees.

### 9.5 Adaptive practice

- Start at the level where predicted P(correct) is closest to 0.7.
- Two correct in a row → up one level. Two wrong in a row → down one level.
- Two wrong at L1 → prerequisite probe (2–3 items on the weakest prerequisite).
- No item repeats within 14 days (except explicit retry). No more than 2 items in a row from the same archetype outside guided ladders.
- Held-out and check-up items are never served in practice.

### 9.6 Help ladder

| Situation | Response |
|---|---|
| Mastery ≥ 80%, single wrong answer | "Check again" retry; normal rating update |
| Mastery 40–80%, first wrong on this skill in session | Stored hint → retry |
| Wrong again after the hint, or second wrong | Step-by-step worked solution → similar item |
| Mastery < 40%, or 3 wrong on the skill in a session | Micro-lesson (3–7 min, stored) → guided ladder of 4–6 items |
| Two L1/L2 misses and a prerequisite is unknown or below required | Prerequisite probe → repair (time box 15 min, depth ≤ 2) |
| Chosen wrong option is linked to a known misconception | Misconception note shown with the solution |

**Guided ladder outcomes:** *success* = 3 correct in a row including ≥ 1 at L3, no hints. *Partial* → schedule a follow-up. *Struggling* → drop a level. *Time box reached* → stop and schedule.

### 9.7 Check-up (diagnostic)

- 12–15 items per covered subject, about 12–15 minutes each. It can be split across sessions.
- At least one item per in-scope topic group; the highest-share topics get two.
- Starts at L2 and adapts up or down within each topic.
- Output: provisional topic and skill ratings with confidence, and a first plan. **No score is shown.**
- After the check-up, every practice item keeps refining the ratings.

### 9.8 Assessments and mocks

| Type | Items | Source pool | When | Feedback |
|---|---|---|---|---|
| Check-up | 12–15 per subject | Check-up pool | Onboarding | After completion, no score |
| Mini-mock | 20 per subject | Held-out | Pilot weeks 0, 4, 8; then monthly | After submit |
| Full CBT mock | Configured (English 60, Maths 40) | Held-out | From mid-February | After submit, with full report |

- **Timing** is pro-rated from the real UTME time allowance (confirm the current allowance).
- **CBT interface:** question palette, flag for review, subject switching, keyboard shortcuts (A–D answer, N/P next/previous), auto-submit, unanswered questions counted separately from wrong ones.
- **Mock report** groups wrong and unanswered items by *likely* cause, showing the rule used for each:

| Likely cause | Rule |
|---|---|
| Knowledge gap | Skill mastery < 65%, or wrong and slower than expected |
| Time pressure | Answered in the last 10% of time, or unanswered |
| Likely careless | Skill mastery ≥ 80% and wrong faster than expected |
| Likely guess | Correct or wrong in < 25% of expected time |

- **Mock repair:** each wrong item's skill becomes a `MOCK_REPAIR` plan item within 24 hours, unless the cause is "likely careless" at ≥ 80% mastery. Repair ends after ≥ 2 correct non-mock items at the mock item's level.

### 9.9 Score range

```
model_score[subject] = Σ_skills E[q_skill] × marks_per_q × p_decayed(skill)
shown_range          = blend(model_score, recent mini-mock scores) ± width
width                = from calibration residuals (default ±12 until calibrated)
```

- **Unlocks** when the student has completed ≥ 1 held-out mini-mock **and** made ≥ 150 scored attempts in that subject. Until then: "Complete your first check-up mock to see your score range."
- **Shown per subject** as "62–74 / 100". A total is shown only when every selected subject is covered.
- **Updates** only after a mock or the weekly recalculation, never after a single practice session.
- **Calibration target:** 70–90% of later mock scores fall inside the range shown before them.

## 10. AI use and guardrails

**v1 AI features (text only):** "Explain this differently", "Why is my answer wrong?", and short follow-up questions on an item the student just answered.

| Guardrail | Rule |
|---|---|
| Grounding | Prompts include the stored worked solution, skill note and the student's chosen option. The model explains; it doesn't solve from scratch |
| Answer check | If the model's final answer differs from the stored key, the stored solution is shown instead |
| Assessments | No AI help during check-ups, mini-mocks or full mocks |
| Curriculum and plan | The AI never changes skills, weights, plans or ratings |
| Generated variants | Built from templates with parameter constraints; answers computed by code (e.g. SymPy); approved by a person; practice pool only |
| Cost | Tracked per request; per-student daily cap; target ≤ $0.25 per active student per month |
| Privacy | Provider settings exclude training on our data; no names sent in prompts |

## 11. Content system

**Hierarchy:** Exam → Subject → Syllabus version → Topic → Subtopic → Skill. Each syllabus version has an `effective_from` date.

**Required to approve an item:**

| Field | Notes |
|---|---|
| Primary skill | Exactly one in v1 |
| Level L1–L5 | Defined per skill in its skill note |
| Archetype | Recurring problem structure |
| Stem, 4 options (A–D), key | Maths notation supported |
| Worked solution | Numbered steps; Maths answers checked by code where possible |
| Hint | At least one |
| Distractor misconceptions | Required for the top 40 skills per subject; optional elsewhere in v1 |
| Expected seconds | Author estimate, recalibrated later |
| Pool | practice · check-up · held-out |
| Source and rights | original · licensed · historical (with rights noted) |
| Author and reviewer | Must be different people |

**Workflow:** Draft → In review → Approved → Live → Retired. Live items are never edited in place; edits create a new version.

**Quality controls:**
- 10% of items tagged independently by two people. Target: ≥ 80% agreement on primary skill, and level within ±1.
- Items flagged automatically when, after ≥ 50 attempts, the correct rate is < 10% or > 97%, or when students report the item ≥ 3 times.
- Student "Report a problem" reports are triaged within 48 hours.

**Rights.** Items are original and written in UTME style. Past papers are used for topic-share analysis and as style reference. Past questions are reproduced only where rights are clear.

**English.** Comprehension and cloze items share a passage record: word count, reading level, estimated reading seconds.

**Content volume targets** (re-baselined after the Sprint 1 throughput measurement):

| By | Coverage of expected exam questions | Practice items per in-scope skill | Held-out pool | Micro-lessons |
|---|---|---|---|---|
| Soft launch (22 Nov) | ≥ 50% | ≥ 12 | 40 per subject | Top 15 skills per subject |
| Engine ready (3 Jan) | ≥ 70% | ≥ 12 | Maths 80 · English 120 | Top 40 per subject |
| Week-4 mock (14 Feb) | ≥ 85% | ≥ 15 | Maths 120 · English 180 | Top 60 per subject |
| Exam run-in (11 Apr) | 100% | ≥ 15 (≥ 25 for top 20% by weight) | Maths 160 · English 240 | All Weak-prone skills |

## 12. Data model

**Principle:** stored events are never edited and are the source of truth. Mastery, plans, opportunities and metrics are derived, stamped with `engine_version`, and can be rebuilt by replaying events.

### Source-of-truth tables

| Group | Tables |
|---|---|
| Identity and organisations | `users`, `schools`, `classrooms`, `classroom_members`, `consents`, `research_assignments` |
| Exam configuration | `exams`, `exam_subjects`, `syllabus_versions` |
| Curriculum | `topics`, `subtopics`, `skills`, `skill_prerequisites`, `topic_weights` |
| Content | `items`, `item_versions`, `item_options`, `passages`, `misconceptions`, `micro_lessons`, `item_templates`, `content_reviews`, `item_reports` |
| Student setup | `student_profiles`, `student_subjects`, `student_goals` |
| Events (append-only) | `attempts`, `study_sessions`, `plan_events`, `assessment_sessions`, `assessment_responses`, `ai_requests`, `app_events`, `exam_results` |

### Derived tables (rebuildable)

`skill_ratings`, `review_state`, `topic_mastery`, `opportunities`, `plans`, `plan_items`, `score_ranges`, `item_stats`, `metrics_daily`, `metrics_weekly`

### Key fields

**`exams.config`** is written with other exams in mind (JSON, validated):
```
sections[]            name, question_count, time_allowance_min
score_scale           { min, max }
goal_types[]          maximise_score | reach_band | pass_all_papers
pass_rules            per paper / per section (null for UTME)
retake_cycle          e.g. annual
```

**`item_versions`**
```
id, item_id, version, skill_id, level, archetype_id, item_type (mcq | numeric | multi_part | written | spoken),
marking_method (auto | rubric | ai_assisted | human), stem, solution_steps[], hints[], expected_seconds,
pool, source_type, rights_note, author_id, reviewer_id, status, syllabus_version_id, created_at
```
v1 implements `item_type = mcq` and `marking_method = auto` only.

**`student_goals`**
```
student_id, exam_id, subject_id, goal_type, target_value, exam_date, minutes_per_day, study_days[], created_at
```

**`attempts`** (append-only)
```
id (client UUID, idempotent), student_id, item_version_id, context (checkup | practice | review | guided | mixed | timed),
plan_item_id, selected_option, is_correct, response_ms, hint_count, solution_viewed_before_answer,
answered_at_client, received_at_server, was_offline, app_version, engine_version
```

**`skill_ratings`** (derived)
```
student_id, skill_id, theta, scored_attempts, levels_seen[], confidence, last_attempt_at,
last_success_at, half_life_days, engine_version, computed_at
```

**`plan_items`** (derived, kept for audit)
```
plan_id, position, activity_type, skill_id, minutes, reason_code, gain_estimate, priority, status, engine_version
```

**`skill_prerequisites`**
```
skill_id, prerequisite_skill_id, strength (0–1), required_mastery (0–1), syllabus_version_id
```

**`topic_weights`**
```
topic_id, syllabus_version_id, historical_share, expert_share, alpha, sources[], updated_by, updated_at
```

**`research_assignments`**
```
student_id, study_id, group (A_plan | B_practice), unit (class | student), assigned_at, switched_at
```

## 13. Platform and non-functional requirements

| Area | Requirement |
|---|---|
| Client | Installable web app (PWA); reference device: 2 GB RAM Android phone; desktop Chrome in school labs |
| Offline | Prefetch the next 40 practice items with solutions; queue attempts with client UUIDs; syncing the same attempt twice stores it once |
| Mocks offline | Start and submit need connection; timer and answers survive drops and app backgrounding |
| Speed | Next practice item < 300 ms from cache; plan generation < 2 s; p95 API < 500 ms at 600 concurrent practising students |
| Data use | Target ≤ 1 MB per 30-minute practice session, excluding first install |
| Determinism | Same state + same engine version → same plan |
| Versioning | `engine_version`, content version and syllabus version stamped on every derived record |
| Availability | ≥ 99.5% uptime during Jan–May exam season |
| Observability | Error tracking, sync-loss reconciliation, AI cost dashboard, engine decision logs |

## 14. Privacy and safeguarding

Most users are 16–18, so the Nigeria Data Protection Act 2023 applies, with extra care for minors.

- **Consent:** guardian consent recorded per student before any attempt data is stored beyond the session. For the pilot, schools collect consent forms.
- **Data minimisation:** no home address and no national ID. The JAMB registration number is optional and only for opt-in result verification.
- **Research:** separate opt-in for research use; analysis data is pseudonymised; students can withdraw.
- **Access:** role-based; teachers see only their classes; group assignment is visible only to the research role.
- **No voice recording in v1.**
- **Contracts:** a data processing agreement with every school.
- **Retention:** deletion on request; retention periods defined before pilot launch.
- **Legal review** before the pilot launches (S7) and before results collection (S15).

## 15. Metrics

**North-star metric:** gain in held-out mini-mock score per 10 hours of active study, comparing Group A (My Plan) with Group B (practice only).

| Metric | Pilot target |
|---|---|
| Students studying ≥ 3 days/week at week 8 | ≥ 40% of enrolled |
| Median active minutes per week | ≥ 90 |
| Plan item completion | ≥ 60% |
| Week-8 mini-mock gain, A minus B | ≥ +5 marks per subject (hypothesis; tested per the frozen analysis plan) |
| Later mock scores inside the range shown | 70–90% |
| Content error reports | < 3 per 1,000 attempts |
| AI cost | ≤ $0.25 per active student per month |
| Teachers opening class view | ≥ 1 view per class per week |
| Pilot schools renewing on paid terms | ≥ 3 of 5 by 12 Sep 2027 |

## 16. Pilot study design

- **Who:** 3–5 schools; 300–600 consenting SS3 students writing UTME 2027 with English (and Maths where it's in their combination).
- **Groups:** randomised by class (or by student within a class, if the school agrees).
  - **Group A — My Plan:** the full product.
  - **Group B — Practice:** the same items, solutions and AI help, but students choose topics themselves; no plan and no opportunities screen.
- **Measurement:** held-out mini-mocks at weeks 0, 4 and 8.
- **Switch:** at week 8, Group B moves to My Plan, so every student has the full product for the last ~7 weeks before UTME.
- **Primary outcome:** change in mini-mock score from week 0 to week 8 per subject, adjusted for study hours and baseline.
- **Secondary outcomes:** engagement, plan completion, calibration of score ranges.
- **Analysis plan frozen** before any baseline result is viewed (S8).
- **Optional outcome:** actual UTME subject scores, opt-in, with the verification method recorded. Reported as *observational*, separately from the randomised mock result.

## 17. Expansion strategy

**Order:**
1. UTME English + Maths
2. UTME Biology, Chemistry, Physics (these complete the science combinations and make a total score possible)
3. Post-UTME and WAEC objective papers
4. A professional exam with mostly multiple-choice questions and demand in Nigeria (ICAN Foundation / ATSWA, or nurse licensing CBTs)
5. IELTS (before TOEFL)

**Gates before adding an exam:**

| Gate | Test |
|---|---|
| Engine proven | Pilot shows a positive randomised mock effect |
| Demand | 20–30 candidate interviews confirm the pain and willingness to pay |
| Format | ≥ 70% of marks can be marked automatically, or there is a credible marking plan |
| Content | Expert supply and content rights secured; update cadence understood (e.g. tax law) |
| Channel | A named distribution channel with a lower cost per customer than paid ads |

**Built now so expansion is configuration, not a rewrite:** the exam configuration, item types, marking method and goal types described in §12. For a `pass_all_papers` goal (e.g. ICAN), the planner puts time into the paper just below the pass mark before a paper that is already safely passing.

## 18. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Content throughput too slow for the pilot | High | High | Measure in S1; narrow pilot scope by topic share; paid holiday author sprint; subject leads own weekly targets |
| Students stop using it after a few weeks | High | High | In-school onboarding; teacher inactive lists; weekly commitment; winnable items in every session; parent digest |
| Pilot shows no difference between groups | Medium | High | Treat as a product signal; inspect engagement vs outcome; iterate before selling |
| Score ranges miscalibrated | Medium | High | Unlock only after mocks; calibration report each mock; wide default width |
| Wrong answer keys or solutions | Medium | High | Two-person review; code answer checks; student reports; stats-based flags |
| AI explanation contradicts the key | Medium | Medium | Grounding; answer-mismatch fallback; no AI in assessments |
| School calendar disruption (exams, strikes, holidays) | Medium | Medium | Confirm calendars in S0; home use supported; flexible mock windows |
| Randomisation contamination (students share accounts or plans) | Medium | Medium | Class-level assignment; account per phone number; measure contamination |
| Data protection breach or consent gap | Low | High | Consent gating in code; DPA with schools; legal review; least-privilege access |
| UTME format or dates change | Low | Medium | Exam configuration, not code; content syllabus versioning |
| Low-cost incumbents copy "AI study plan" | High | Medium | Differentiate on verified content and published outcome evidence |

## 19. Assumptions and open questions

| # | Assumption / question | Owner | Resolve by |
|---|---|---|---|
| 1 | UTME 2027 exam window around late April–mid May; registration ~Jan–Feb | PM | Confirm when JAMB publishes |
| 2 | English 60 items, other subjects 40, each out of 100; time allowance pro-rated | Subject leads | S0 |
| 3 | Team: founder/PM, 2 full-stack engineers, 1 data-leaning engineer, 1 half-time designer, 2 subject leads (~20 h/wk), 2–4 part-time authors, 1 school success lead from M1 | Founder | S0 |
| 4 | Pilot schools allow class-level randomisation and in-school onboarding sessions | School lead | S1 |
| 5 | Students have regular phone access; schools have computer labs for full mocks | School lead | S1 |
| 6 | Content throughput supports the volume table in §11 | Subject leads | S1 |
| 7 | Price hypotheses for schools and the season pass | PM | May 2027 (outside the engineering plan) |
| 8 | Parent digest channel: SMS, WhatsApp or email | PM | Before S11 |
| 9 | Payment provider (e.g. Paystack or Flutterwave) | Tech lead | Before S21 |
| 10 | Legal review of consent, research and results-collection flows | Founder | Before S7 and S15 |
