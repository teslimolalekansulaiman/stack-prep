# ADR-0015 · WAEC WASSCE replaces NECO as the POC exam

- **Status:** Accepted
- **Date:** 2026-09-17
- **Supersedes:** the exam choice in [ADR-0014](0014-neco-objective-poc.md). Its decisions on
  marking flexibility and marks-based reporting still stand.

## Context

ADR-0014 chose NECO SSCE External because that was the syllabus we had. WAEC syllabuses
and past questions turned out to be the material actually available, so the pilot follows
the content.

The WAEC 2027 syllabuses for Mathematics and English Language have been imported as draft
curriculum (PDF pages 1–18 and 2–9 respectively). They state the paper structure:

| Subject | Paper | Format | Questions | Time | Marks |
| --- | --- | --- | ---: | ---: | ---: |
| Mathematics | 1 | Multiple choice | 50 | 90 min | 50 |
| Mathematics | 2 | Essay, 13 questions, answer 10 | 13 | 150 min | 100 |
| English | 1 | Multiple choice (40 lexis, 40 structure), four options | 80 | 60 min | 40 |
| English | 2 | Essay, comprehension, summary | — | 120 min | 100 |
| English | 3 | Multiple choice (Test of Orals, or Listening Comprehension) | 60 | 45 min | 30 |

## Decision

1. **The POC targets WAEC WASSCE objective papers**: Mathematics Paper 1, English Papers 1
   and 3. Theory papers are recorded but not delivered adaptively.
2. **NECO stays in the database.** Its syllabus version is separate and still draft; it is
   not deleted and not reused. A WAEC question can never be classified against a NECO
   skill — the composite foreign key blocks it.
3. **Reporting changes from "subject out of 100" to "objective paper marks, scaled to
   100".** ADR-0014 assumed a subject was one objective paper. It is not:

   | Subject | Objective marks | Subject total | Objective share |
   | --- | ---: | ---: | ---: |
   | Mathematics | 50 (Paper 1) | 150 | **33%** |
   | English | 70 (Papers 1 and 3) | 170 | **41%** |

   The product must not present an objective-paper estimate as a WAEC subject result. Until
   theory marking exists, a student sees "Paper 1 practice score, out of 100" and a plain
   statement of what it does not cover.
4. **Marks per question come from the paper**, as `exam_papers.score_out_of / question_count`
   — Mathematics Paper 1 is 1 mark per question, English Paper 1 is 0.5.
5. **English Paper 1 has four options (A–D)**, printed in the syllabus. The engine still
   reads `option_count` per item rather than assuming it.
6. **Country variants are recorded.** English Paper 3 is the Test of Orals in Nigeria and
   Liberia, and a Listening Comprehension Test elsewhere; the Listening alternative is
   imported with a boundary note so a reviewer can mark it unsupported for Nigeria.

## Consequences

- The imported WAEC curriculum is 9 topics / 42 subtopics / 117 skills for Mathematics, and
  6 topics / 18 subtopics / 62 skills for English — all draft, all evidence pending, nothing
  published.
- The score-range work now predicts an objective-paper mark, not a subject grade. That is a
  narrower claim, and an honest one.
- Covering a full WAEC subject later means theory marking: a rubric path, a marking queue
  and marker agreement checks. That is a milestone, not a column.
- `docs/product-spec.md` and `docs/roadmap.md` still describe a UTME pilot in places. Where
  they disagree with this ADR, this ADR wins.
- The loader no longer hard-codes one syllabus's shape: `validation.source_page_range` and
  `validation.expected_topic_count` now come from each seed, so a mistyped page or a dropped
  topic fails the import.

## Alternatives considered

- **Stay on NECO.** We would be building against a syllabus while holding another body's
  past questions. Question provenance and syllabus would not match.
- **Import both and decide later.** Doubles the review work before anything is validated.
  NECO remains in the database, so this stays possible without being paid for now.
- **Claim a full subject score from objective practice.** It would look better on a landing
  page and be untrue: two thirds of the Mathematics marks are essay marks we do not touch.
