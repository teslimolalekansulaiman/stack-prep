# ADR-0014 · NECO objective papers for the POC, marks out of 100 per subject

- **Status:** Accepted
- **Date:** 2026-09-17
- **Supersedes:** the UTME pilot assumption in docs/product-spec.md and docs/roadmap.md

## Context

The product spec and delivery plan were written against UTME. The syllabus already
loaded into `stackprep` is NECO, and the data model handed over by the academic
team targets **NECO SSCE External**. The two exams are not interchangeable:

| | UTME | NECO SSCE External |
| --- | --- | --- |
| Papers | One multiple-choice paper per subject | Objective **and** theory papers, sometimes practical |
| Reported result | Four subjects, 400 total | Grades per subject (A1–F9) |
| Marking | Entirely automatic | Objective automatic, theory marked by examiners |

Every part of the engine that assumed "one multiple-choice paper, a score out of
100 per subject" needed a decision before the question schema could be written.

## Decision

**The POC covers NECO objective papers only.**

1. **Scope.** Objective (multiple-choice) items are authored, delivered, marked and
   fed to the adaptive engine. Theory items may be authored and stored, but are
   excluded from adaptive practice.
2. **Marking stays general.** Every item version carries `response_format`
   (`mcq_single`, `numeric`, `short_text`, `structured`, `essay`) and
   `marking_method` (`auto_key`, `auto_numeric`, `rubric`, `ai_assisted`, `human`).
   The POC implements `auto_key` and `auto_numeric`. A generated column,
   `adaptive_eligible`, is true only for automatically markable objective items, and
   the `adaptive_practice_questions` view filters on it. Adding rubric or AI-assisted
   marking later is a new marking path, not a schema change.
3. **Scoring.** Each subject is reported **out of 100 marks**. `exam_papers.score_out_of`
   defaults to 100, so marks per question are `score_out_of / question_count`. Grade
   bands (A1–F9) are deliberately **not** modelled yet: converting marks to an official
   NECO grade needs evidence we do not have, and a guessed boundary would be a claim
   about someone's result.
4. **Paper structure is recorded, not assumed.** `exam_papers` holds
   `question_count`, `duration_minutes` and `options_per_question`, with
   `values_confirmed` and a note naming the source. A paper cannot be marked
   `supported` for the pilot until those values are confirmed, so no scoring or mock
   assembly can rest on a guess.
5. **Chance level comes from the item.** `question_versions.option_count` is validated
   against the stored options at approval, and the engine computes chance level as
   `1 / option_count`.

## Consequences

- `packages/engine` no longer hard-codes a 0.25 chance level.
  `chance_level_for_options()` replaces the constant, `retained_mastery()` takes the
  item's chance level, both were mirrored in `packages/engine-ts`, the parity vectors
  were regenerated, and `ENGINE_VERSION` moved to 0.2.0.
- The score-range work in the spec still applies, but it predicts **marks out of 100
  per subject**, never a grade and never a total across subjects.
- The spec and roadmap still say UTME in places. They are being corrected; where the
  two disagree, this ADR wins.
- Theory content can be collected from day one without blocking the POC, which
  matters because NECO results depend on it even though our engine cannot yet help
  with it.
- If the product later targets UTME as well, it is another exam configuration plus
  its own content — no engine change.

## Alternatives considered

- **Stay on UTME.** The loaded syllabus, the source documents and the academic team's
  model are all NECO. Changing the data to match the plan would have cost more than
  changing the plan.
- **Model objective and theory together from the start.** Theory needs a rubric,
  a marking queue and marker agreement checks. That is a milestone, not a column, and
  it would delay a POC that can already prove the adaptive loop.
- **Predict NECO grades now.** Without published, verified grade boundaries this
  would be a fabricated result. Marks out of 100 are honest and still show progress.
