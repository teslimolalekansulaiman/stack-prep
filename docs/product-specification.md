# Stackjunior Exam Coach Product Specification

Version 2.0 · 13 September 2026 · First examination NECO GCE Mathematics

## 1 Product decision

Stackjunior Exam Coach helps a learner decide what to practise, understand mistakes, and demonstrate learning independently. It uses a reviewed curriculum and question bank, a continuously updated learner record, and a flexible study plan. Targeted AI teaching supports that process.

The first release is a paid, supervised NECO GCE Mathematics learning pilot. Its purpose is to test whether students follow the plan, retain what they learn, and pay enough to support delivery. It is not yet a complete examination preparation programme. The full product will progressively cover the subject, support official-format mocks, and add richer teaching interactions after the learning loop is dependable.

The initial product promise is: **A practical daily Mathematics plan, help with the gaps that matter, and clear evidence of your progress.** Improved examination outcomes are the intended outcome, not a guaranteed claim.

This specification defines the resulting product. The companion delivery plan turns its requirements into milestones, two-week sprints, acceptance criteria, and release decisions. Unless explicitly labelled otherwise, numerical targets below are proposed operating thresholds to be agreed before the pilot; they are not established educational standards or achieved results.

## 2 Decisions and assumptions

| Item | Decision or assumption | Consequence |
| --- | --- | --- |
| First examination | NECO GCE Mathematics, confirmed product choice | One exam configuration and Mathematics content model in the pilot |
| Initial learner group | Candidates who can commit to six weeks and use a supported phone or computer | Recruit for a defined programme, not an unrestricted public launch |
| Initial buyer hypothesis | Parent or guardian for a dependent learner; adult candidates may pay directly | Test both demand and payment behaviour; do not assume every learner has a parent account |
| Initial acquisition hypothesis | One partner tutorial centre with an identified recruitment owner | The partner is a proposed channel, not an existing partnership |
| Delivery format | Responsive web application with text, mathematical notation, reviewed diagrams, and resumable sessions | Voice and handwriting are optional future capabilities |
| Pilot teaching scope | 12 to 18 foundational and exam-relevant skills, chosen through the content audit | Disclose the supported skills before payment |
| Curriculum scope | Map the complete applicable Mathematics syllabus; teach only the approved pilot subset initially | Uncovered skills remain visible as unsupported or unassessed |
| Programme duration | Six weeks plus a delayed assessment approximately seven days later | Recruit only where the calendar permits the complete measurement period |
| Commercial offer | One clearly described fixed-duration pilot package; exact fee set through discovery | No score guarantee and no automatic renewal in the pilot |
| Schedule | Relative sprint schedule; start date and capacity not yet committed | The original November target is not a delivery promise |

Before recruitment, the academic lead must verify the exact examination session, applicable syllabus, paper structure, permitted tools, marking approach, and dates against current examination-body material. An exam name alone does not establish these details. Record source, date checked, and content version. No unverified exam dates or paper specifications are embedded in this plan.

## 3 Problems and intended outcomes

Students can spend time practising familiar questions without discovering missing prerequisites or retaining a method. They may also know a method but struggle to identify when to use it. The product must make the next activity understandable and verify improvement after support is removed.

Parents and adult buyers need an understandable account of the programme, its cost, the expected commitment, and actual progress. A report should distinguish attendance, supported practice, and independent performance rather than compressing everything into one score.

The business needs evidence of demand, reliable content operations, acceptable support workload, and sustainable delivery costs. A technically impressive tutor is insufficient if students do not return or cannot afford its operation.

The primary pilot learning outcome is improvement on fresh, unaided Mathematics assessments covering the declared pilot skills, with a delayed assessment to check retention. This is a measured practice outcome. It is not automatically equivalent to an official NECO result or grade.

## 4 Users and responsibilities

| Role | Needs and responsibilities |
| --- | --- |
| Student | Choose a realistic commitment, take assessments, practise, request help, and see progress and limitations |
| Parent or authorised supporter | Understand the agreed commitment, receive concise progress reports, and help the learner recover after missed sessions |
| Adult candidate | Control their own account and reporting permissions; no mandatory guardian workflow |
| Academic lead | Own the syllabus map, skill definitions, question quality, prerequisite links, and assessment comparability |
| Content reviewer | Check mathematical validity, explanations, distractors, accessibility, and content provenance |
| Support or teaching reviewer | Resolve disputed marking, ambiguous work, repeated failed interventions, and technical interruptions |
| Product owner | Own scope, pricing experiments, pilot protocol, release decisions, and claim boundaries |
| Engineering and QA | Implement the learning workflow, preserve evidence, test failure paths, and maintain access controls |

## 5 Scope and release boundaries

| Capability | Focused pilot | Full subject release or later |
| --- | --- | --- |
| Onboarding | Exam session, baseline context, supported skills, study availability, consent and payment disclosures | More examinations and institutional management |
| Curriculum | Complete coverage map plus 12 to 18 teachable skills | Reviewed teaching coverage for the full Mathematics route |
| Diagnostics | Reviewed assessment with bounded follow-up probes and explicit uncertainty | Calibration and adaptive item selection after sufficient data |
| Planning | Transparent rules using observed need, prerequisites, review dates, syllabus relevance and time budget | Data-informed estimates of intervention effectiveness |
| Practice and teaching | Objective and optional typed working; reviewed examples, hints and short targeted explanations | Rich mathematical editor, validated handwriting and spoken reasoning |
| Assessment | Fresh weekly mixed checkpoints and timed sections within the disclosed skill scope | Verified full-paper simulations with broader subject coverage |
| Progress | Evidence states, counts, dates, support used, and fresh assessment results | Validated score forecasts with uncertainty |
| Accountability | Learner reminders, weekly report and practical recovery plan | More institutional reporting and integrations |
| Live teacher | Optional internal prototype, outside the critical delivery path | Student-facing voice and whiteboard after a separate quality and cost gate |
| Commercial promise | Defined service, content scope, price and ordinary service/refund terms | A separately approved outcome guarantee, if evidence supports it |

An unsupported skill must never appear complete. Pilot-level assessments must never be labelled full-subject readiness. Full-paper mocks become available when their content and format are ready; individual students do not have to complete the teaching route to access them.

## 6 Student experience

### 6.1 Join with informed expectations

The learner selects the configured examination session, enters available study time, and sees the exact pilot coverage and programme requirements. The product records self-reported history as context, not measured ability. A target is an aspiration and does not become a forecast.

REQ-01: Before payment, show included skills, programme dates, expected weekly commitment, device needs, assessment expectations, price, reporting arrangements and absence of an outcome guarantee. A learner can decline or leave without surrendering access to their own progress record.

### 6.2 Establish an initial picture

Use a broad, reviewed assessment of the pilot skills with a provisional 25 to 35 minute budget. Probe important uncertainties with a small number of follow-up questions. The academic lead approves the actual item count and blueprint in Sprint 2. Allow pause and resume; identify interrupted timing rather than treating it as uninterrupted speed evidence.

For the measured pilot, the common unaided baseline runs first under the same rules for both groups. Its responses may seed the learner model after submission. Adaptive diagnostic probes occur afterwards for the adaptive group and never alter the baseline score or form allocation. The diagnostic time budget and the common baseline assessment budget are specified separately in the protocol so a long onboarding assessment is not hidden.

REQ-02: A short diagnostic produces an initial plan and explicit evidence gaps. Unassessed skills stay unassessed. A single response cannot establish a durable misconception or mastery state. The learner can start useful practice without completing exhaustive testing.

### 6.3 Follow a manageable daily plan

Offer sessions such as 15, 30 or 45 minutes. A session can contain a short review, a targeted learning activity and independent practice. Explain each selection in ordinary language, for example: “Review fractions because they are making your algebra questions harder.”

REQ-03: Planned duration must fit the chosen budget. The learner can change availability, postpone an activity or select another supported skill. Essential prerequisite repair can temporarily redirect a specific activity, but cannot lock the learner out of the entire subject or assessment mode.

### 6.4 Investigate before teaching

After an error, inspect available evidence and choose a proportionate response: a quick check, a hint, a short explanation, a prerequisite probe or human review. A correct answer with limited evidence may trigger a fresh confirmation item. Legitimate shortcuts and alternative correct methods are accepted.

REQ-04: Misconception labels begin as hypotheses. A wrong option or fast answer alone cannot be recorded as confirmed misunderstanding or guessing. Request clarification where needed; record contradictory evidence and allow the label to be revised.

### 6.5 Teach and remove support

Use a reviewed explanation, one worked example, guided practice where needed, and fresh independent questions. Questions used to demonstrate a method cannot simultaneously be used as proof of independent performance.

REQ-05: Hints, revealed solutions, repeated items and assisted attempts are explicitly recorded. Only unaided, eligible attempts contribute to independent evidence. After two unsuccessful explanation routes in a session, offer a prerequisite activity, break or review request instead of an indefinite reteaching loop.

### 6.6 Revisit and mix

Bring skills back after a delay and mix them without revealing the method to use. A missed review is rescheduled according to current availability. Correctness and timing remain separate observations.

REQ-06: Mixed checkpoints are available early. Timed assessment can start from the first week, with context about scope and uncertainty. A learner does not need every skill or difficulty level cleared before assessment. Failed items create targeted repair suggestions without erasing unrelated progress.

### 6.7 Report and recover

Show completed activities, demonstrated strengths, uncertain skills, due reviews and independent checkpoint results. If sessions are missed, propose a smaller plan or a revised horizon and show the consequence openly.

REQ-07: Never silently lower a target, inflate completion or prescribe impossible catch-up hours. Weekly authorised-supporter reports state what happened and one practical next action. Adult candidates can use the programme without supporter reporting. No public comparisons, shame language or automatic punishment for inactivity.

## 7 Evidence and learner state

Maintain separate records for supported performance, independent accuracy, retention, transfer to different question forms, and timing. These dimensions can disagree. A learner may be accurate independently but still need more time; the interface should say so.

| Display state | Minimum interpretation | What it does not establish |
| --- | --- | --- |
| Not enough evidence | Missing, sparse or conflicting observations | Weakness or failure |
| Needs support | Repeated difficulty or confirmed prerequisite gap | Inability across the whole topic |
| Independent evidence emerging | Some fresh unaided success | Stable retention or broad transfer |
| Independent performance demonstrated | Meets the provisional evidence rule below | A predicted exam mark |
| Retention demonstrated | Eligible independent success after a delay | Permanent mastery |
| Timed performance demonstrated | Independent success under the specified assessment conditions | Readiness for every part of the subject |

Provisional evidence rule: at least eight eligible unaided attempts across at least three question families and two sessions, with at least 75 percent correct, is required before displaying independent performance demonstrated for a skill. Retention additionally requires at least four fresh unaided items at least seven days after the relevant teaching, with at least three correct. These are pilot operating rules, versioned and reviewed for usefulness; they are not validated mastery probabilities.

REQ-08: Display counts and context, such as “6 of 8 fresh questions correct across two sessions; delayed review due.” Do not show invented probabilities such as “72 percent mastered.” Never convert a missing response into a wrong answer except where a defined timed assessment scoring rule explicitly requires it. Later errors can mark evidence as needing review while preserving its history.

REQ-09: Record item family and exposure history. Changing only numbers or names does not make an item independent evidence of transfer. One response mapped to several skills must not be counted as several independent observations of each skill. Record the primary assessment target and treat secondary-skill implications as uncertain until probed.

## 8 Activity selection

The pilot uses a transparent prioritisation policy. It does not claim to calculate expected examination marks gained per hour.

Selection proceeds through explicit decisions: check time budget and fatigue; reserve space for due review; address a confirmed prerequisite blocking the selected skill; select a manageable supported weakness; include mixed confirmation and sufficient breadth. Near the examination, increase timed and mixed practice only where the learner has the relevant foundation.

REQ-10: Every recommendation records the eligible candidates, selected activity, reason, evidence references, estimated duration and policy version. Historical frequency is optional supporting information only when its source and comparability are reviewed. It must not remove syllabus areas, imply access to future papers, or double-count exam importance through several overlapping multipliers.

REQ-11: Duration estimates begin as academic estimates and are updated with observed completion times. The system must handle sparse evidence, no due reviews, unsupported topics, insufficient content, changed availability and a learner repeatedly skipping an activity. When evidence is weak, a short probe is an acceptable next action.

## 9 Curriculum and content operations

A reviewed syllabus map defines subject, topic, skill, prerequisites and examination relevance. Prerequisite edges are explanations of dependency, not a compulsory linear course. The pilot subset is chosen for coherent teachability and learner need, not solely historic frequency.

REQ-12: Every published question has a unique version, skill target, question family, answer, rationale, reviewed difficulty label, estimated time, provenance, publication state and reviewer record. Assessment questions also have an assessment allocation and exposure restrictions. Ambiguous or disputed content can be quarantined and replaced without destroying attempt history.

Initial bank target: at least 12 reviewed practice items for each pilot skill, spanning at least three question families, plus reviewed teaching examples. Separately prepare two comparable 30-item baseline/endline forms, six 15-item weekly checkpoint forms, and a 20-item delayed assessment form. This is at least 170 assessment items outside the practice bank. Increase the bank where coverage or exposure review finds it insufficient.

REQ-13: The baseline and endline forms sample comparable skills and difficulty. Counterbalance their assignment where feasible. Exact items and close variants from protected assessments are excluded from tutoring, practice retrieval and generation. The delayed form must support the declared retention analysis; it does not establish retention for every individual skill unless the evidence count is sufficient.

After a protected assessment, planning and tutoring can receive skill-level result summaries. They must not receive protected question text or solutions through the learner's attempt history. Any diagnostic follow-up uses the approved practice/probe pool.

REQ-14: AI-generated material is draft content until academic review and mathematical validation are complete. Content sources and reuse permissions must be documented before publication. The pilot does not depend on an unreviewed generator producing live assessment questions.

## 10 Teaching reliability and review

The tutor receives the current item, reviewed solution, approved context, available learner evidence and a bounded teaching objective. It should explain from that evidence and ask short questions rather than provide an unrestricted lecture.

REQ-15: Validate mathematical results where a reliable independent check is available. If interpretation or marking is uncertain, disclose the uncertainty and offer clarification or review. Preserve the student's original response alongside any normalisation. Do not mark an unfamiliar but valid method wrong because it differs from the exemplar.

REQ-16: Review requests include the item version, original response, explanation shown and relevant evidence. A reviewer can correct a result, remove an incorrect misconception label and trigger recomputation of affected recommendations. The user sees the correction. Pilot support target: acknowledge within one working day and resolve or provide a useful update within two working days, with published operating hours.

## 11 Progress and forecasts

The pilot dashboard reports observed assessment results, item counts, the supported skill scope, review status and change over comparable assessments. Small daily changes in practice accuracy do not become daily predicted exam-score gains.

REQ-17: Keep three concepts separate: the learner's goal, measured current assessment performance and any future validated forecast. A Mathematics-only pilot cannot produce a total UTME score, a complete NECO result or a defensible whole-exam readiness claim. Forecast functionality remains unavailable until its own release gate passes.

Forecast release requires verified outcome data, clear separation of training and evaluation cohorts, comparison with a simple mock-score baseline, uncertainty intervals, subgroup error review and monitoring of missing results. The model and evaluation protocol must be frozen before testing on the evaluation cohort. Pilot participation alone is not sufficient evidence to enable it.

## 12 Commercial design and guarantee boundary

The initial offer is a fixed-duration paid programme with clear coverage and support. Discovery should establish the payer, alternatives used today, willingness to make an actual payment, acceptable time commitment and a workable acquisition channel. Price is an explicit decision before recruitment, not a fabricated number in a forecast.

REQ-18: Maintain a programme cost record containing net collected revenue, AI and hosting usage, payment fees, refunds, content review, support effort and partner acquisition cost. Report one-time research and development expenditure separately, while including recurring content and support costs in the scale scenario. Founder labour must not be silently treated as free.

Report contribution per paying learner as net collected programme revenue less attributable variable delivery and acquisition costs. Track fixed operating and development costs separately. Publish assumptions behind both actual pilot costs and any larger-cohort projection; a projection is not observed profitability.

REQ-19: No outcome guarantee in the pilot. Before any later guarantee, define the exact result unit, measurement source, reasonable participation requirements, commitment agreed before purchase, guarantee lock point, refund amount, result verification, dispute process and treatment of service outages or plan changes. The engine cannot unilaterally increase workload and then void eligibility when a learner fails to comply.

A future guarantee requires validated forecasts in the same examination and population, independently reviewed terms, a bounded financial exposure assessment and an operating process for refunds. Its wording and eligibility must be understandable without relying on an impractical completion burden. These are future product release requirements, not permission to launch a guarantee now.

## 13 Pilot measurement and decisions

Recruit 30 to 50 paying learners for a six-week feasibility pilot, followed by a delayed assessment approximately seven days later. This sample is intended to test operation, engagement and preliminary learning signals; it cannot by itself establish broad causal efficacy or validate a score guarantee.

Where participants consent, randomly assign learners to adaptive planning and teaching or ordinary structured practice, stratifying by baseline band. Both groups receive disclosed services, reviewed materials and comparable expected study time. Explain the allocation before payment and offer the comparison group adaptive access after measurement. If randomisation is not feasible, report the comparison as observational and record differences in starting ability, study time and additional tuition.

REQ-20: Freeze the protocol, primary outcome, thresholds, form allocation, group handling and analysis plan before the first baseline. Report all enrolled learners in participation results; do not report only successful completers. Report missing assessments, external tuition, exclusions, uncertainty and sensitivity to dropout. A short delayed test measures pilot-skill retention, not overall examination readiness.

| Measure | Definition | Proposed pilot decision target |
| --- | --- | --- |
| Paid demand | Learners who pay the disclosed fee without an outcome guarantee | At least 30 before cohort start; otherwise change the recruitment plan or cohort design explicitly |
| Activation | Paid starters who finish baseline and the first learning session within seven days | At least 75 percent |
| Week four participation | All paid starters completing at least two substantive sessions in week four | At least 60 percent; report withdrawals separately without removing them from the denominator |
| Plan adherence | Median completed agreed weekly sessions divided by agreed sessions; revisions remain visible | At least 60 percent over the teaching period |
| Measurement completion | Paid starters providing baseline, endline and delayed assessments | At least 80 percent; lower completion requires an explicit missing-data investigation |
| Preliminary learning | Baseline-adjusted difference in endline percentage correct versus comparison, plus delayed retention | A proposed signal of at least 5 percentage points at endline and no negative delayed difference; report intervals and treat inconclusive results as inconclusive |
| Academic reliability | Confirmed material teaching or marking defects in a stratified audit of at least 100 interactions | No unresolved critical defect before expansion; report defect rate and severity, not only a pass label |
| Economics | Observed delivery cost and a fully costed repeat-cohort model at the tested price | A credible positive contribution scenario without omitted recurring labour; negative actual pilot economics must remain visible |

REQ-21: A release decision may be proceed, iterate or stop. Meeting a directional learning threshold is not permission to claim proven efficacy. Missing comparator data, wide uncertainty, negative delayed results or unresolved critical content issues require further work before expansion claims.

## 14 Data and service requirements

REQ-22: Preserve versioned records for exam configuration, skills, prerequisite edges, item families, questions, assessments, attempts, interventions, review decisions, evidence states, plans and recommendation reasons. Each attempt records assistance, exposure, answer state, timing interruptions and assessment context. Restrict protected assessment content from the tutor's retrieval context.

REQ-23: Enforce role-based access to learner records and supporter reports. Record required consent and reporting permissions; revoke supporter access when permission is removed. Establish retention and deletion rules before recruitment. Student work is not used to train external models by default. Sensitive account and payment information is excluded from general tutor context.

REQ-24: Support keyboard use, readable mathematical notation, phone layouts, connection interruptions and a text path for all essential learning activities. Draft answers must recover after reload; a retried submission must not duplicate the attempt or learning event. If the tutor is unavailable, serve an approved explanation or a review route and keep the learner's work.

Provisional service targets for pilot verification: ordinary plan and question actions complete within two seconds at the 95th percentile in the agreed test environment; tutoring shows an acknowledgement within two seconds and a useful response or clear fallback within 15 seconds. Load testing uses twice the expected peak cohort concurrency. Define and record the device, connection profile and concurrency model before measurement; do not present these lab targets as guaranteed live performance.

## 15 Product architecture

Use a modular application with clear responsibilities. A separate deployed service for every concept is unnecessary for the pilot.

| Responsibility | Owns | Boundary |
| --- | --- | --- |
| Student experience | Onboarding, plan, practice, assessment, progress and recovery | Displays supported scope and uncertainty |
| Content and assessment | Curriculum, item versions, forms and publication | Protects assessment pools from practice and tutor retrieval |
| Learner evidence | Eligible observations, assistance and evidence states | Produces inspectable state, not invented precision |
| Planning policy | Candidate selection, time budget and recommendation reasons | Versioned deterministic rules initially |
| Teaching | Reviewed context, hints, short explanations and checks | Cannot publish unreviewed items or modify official scoring rules |
| Review operations | Disputes, corrections, quarantine and recomputation | Preserves history and communicates corrections |
| Programme operations | Consent, payment status, reports, cost and pilot measurements | No implicit score guarantee or hidden sharing |

## 16 Later capabilities and their gates

Voice and a live whiteboard remain part of the product vision. Enable them for a small group only after they preserve mathematical correctness, handle interruptions without losing the learning step, offer a complete text fallback, and meet a measured cost and latency budget.

Handwritten and spoken reasoning require student confirmation of uncertain transcription, preserved originals, alternative valid-method handling, and a reviewed benchmark from the target learner population. Neither input format should silently influence mastery when interpretation is unresolved.

Expand to full Mathematics coverage by passing the same content, assessment and review requirements for each added skill. Add verified full-paper mocks without learner completion locks. English then needs its own skill taxonomy, passage and writing assessment approach; it is not a copy of the Mathematics model.

Score forecasts, outcome guarantees, additional examinations and school administration are separate investments. They are not hidden requirements of the first pilot and do not become automatically approved when its software ships.

## 17 Release invariants

Every sprint and release must preserve these rules: assessments remain accessible without whole-course gates; uncertain diagnoses stay uncertain; assisted work is distinguishable from independent evidence; unsupported content stays visible; recommendations fit a realistic time budget; predictions and guarantees remain disabled until validated; and corrections preserve a traceable history.

The first complete demonstration is a learner who struggles with a prerequisite, receives a short investigation and appropriate teaching, succeeds on different unaided questions, returns for a delayed check, and receives a changed plan supported by that evidence. The system must also behave honestly when that learner does not improve.

## 18 Source and decision record

This version supersedes the planning rules in Stackjunior Exam Coach Product Blueprint version 1.2 dated 13 September 2026 and the supplied score-optimisation concept. It incorporates the review decisions to remove universal mastery gates, separate observations from forecasts, make diagnoses provisional, use transparent initial prioritisation, defer the guarantee, narrow the release and validate commercial assumptions. The selected first examination is NECO GCE Mathematics.

No pilot outcomes, prices, partnerships, official paper details or staffing commitments are asserted as existing facts. These are inputs to establish through the milestone gates in the delivery plan.
