# ADR-0009 · AI explanations grounded in stored solutions, precomputed in batch

- **Status:** Accepted
- **Date:** 2026-09-17

## Context

Students get AI help: "explain this differently" and "why is my answer wrong?".
Two hard constraints:

1. **Correctness.** A tutor that confidently writes a wrong algebra step is worse
   than no tutor. Language models still make arithmetic slips.
2. **Cost.** The product spec caps AI spend at $0.25 per active student per month.
   Per-request generation at exam-season usage would exceed that.

## Decision

- **Batch first.** When an item is approved, a job generates its alternative
  explanation and per-distractor "why this is wrong" text. A reviewer approves them
  once, and they are stored with the item version. At runtime students are served
  stored text.
- **Runtime calls only for genuine follow-up questions**, grounded in the stored
  worked solution, the skill note and the student's chosen option.
- **Answer check.** Any final answer in a model response is compared with the stored
  key. On mismatch the stored solution is shown instead, and the event is logged for
  review.
- **Never during assessment.** AI endpoints refuse check-up, mini-mock and full mock
  items.
- **The model never decides curriculum, plans or ratings.** It explains what the
  engine chose.
- **Models:** Claude Haiku 4.5 at runtime, Claude Sonnet 5 for batch generation,
  behind our own interface so a provider change touches one module.
- **Controls:** every call logged with tokens, cost and latency; per-student daily
  cap; response caching; no student names in prompts; provider configured not to
  train on our data.

## Consequences

- Most help is instant and free at runtime, and has been read by a human before a
  student sees it.
- Content approval gains a step, and the authoring tools need a review screen for
  generated text.
- The cost dashboard, per-student caps and the nightly answer-check evaluation are
  build work, not configuration.

## Alternatives considered

- **Generate everything at runtime.** Simpler, unbounded cost, unreviewed text.
- **Fine-tuning.** No fixed dataset yet, and it would not fix arithmetic slips.
- **Retrieval over a vector store.** Content is structured and addressed by ID;
  similarity search adds machinery without improving grounding.
