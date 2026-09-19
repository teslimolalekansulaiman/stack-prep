#!/usr/bin/env python3
"""Retire the questions set on an approved reading text, and file them where they belong first.

    uv run python database/retire_reading_text_questions.py \
        --reviewer <academic_reviewers.id> --apply

WHY THESE GO RATHER THAN WAIT. Every other kind of question in this bank keeps: a synonym
question from 2011 is as good in 2027 as it was then. A reading-text question is not like that.
JAMB announces a novel for each cycle and then replaces it, so a question about The Potter's
Wheel is worth nothing to a candidate sitting a paper set on something else. Licensing the
novels would not change that — the problem is the cycle, not the copyright.

They were filed under Comprehension because the paper prints them in the same block. That is
put right before they are retired: Approved Reading Text held nothing at all until now, and a
subtopic the syllabus names should show what was set against it even when none of it is live.

WHAT SURVIVES. The questions, their options, their explanations and the record of which novel
each paper was set on, which is written up in docs/questions/utme/english/reading_texts.md.
When a current text is announced and licensed, those are the model to write against.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parent.parent

#: The novel each paper names above these questions, transcribed from the paper itself. Where
#: the attribution line did not survive extraction the year is absent and the question is
#: retired with the general reason.
TEXTS = {
    2013: "Chukwuemeka Ike's The Potter's Wheel and Jerry Agada's The Successors",
    2014: "Chukwuemeka Ike's The Potter's Wheel and Jerry Agada's The Successors",
    2015: "A. H. Mohammed's The Last Days at Forcados High School",
    2016: "A. H. Mohammed's The First Days at Forcados High School",
    2017: "S. I. Manyika's Independence",
}

#: The range each paper prints above the block, read off the attribution line itself —
#: "Questions 21 to 30 are based on Chukwuemeka Ike's The Potter's Wheel". The reports below
#: only reach a question someone wrote an explanation for, and the papers set more of these
#: than anyone has read: 2013's question 21 sat approved and live because its stem says
#: "David and others" rather than "in the novel", which is no kind of evidence either way.
#: The printed range is the paper's own statement of what the block covers, so it is used.
#:
#: 2015 prints "question 21 to 36", but 36 is "The workers tightened their hold on the
#: capital" with four paraphrases under it — a sentence-interpretation item, printed with the
#: block that follows. The range is recorded as the paper means it rather than as it reads.
RANGES: dict[int, list[tuple[int, int]]] = {
    2013: [(21, 35)],
    2014: [(21, 35)],
    2015: [(21, 35)],
}

GENERAL = (
    "Set on the approved reading text for its own cycle. JAMB replaces that text periodically, "
    "so the question cannot serve a candidate sitting a paper set on a different novel. "
    "Retired; see docs/questions/utme/english/reading_texts.md for what each paper was set on."
)


async def run(reviewer_id: str, dsn: str | None, apply: bool) -> int:
    conn = await asyncpg.connect(
        dsn=dsn,
        host=None if dsn else str(ROOT / ".local/run"),
        port=None if dsn else 55439,
        database=None if dsn else "scorepilot",
    )
    try:
        await conn.execute("SET search_path = stackprep, public")
        if await conn.fetchval(
            "SELECT 1 FROM academic_reviewers WHERE id = $1 AND active", reviewer_id
        ) is None:
            raise SystemExit("no active reviewer with that id")

        rows = await conn.fetch(
            """
            SELECT q.id AS question_id, v.id AS version_id, q.exam_year, ci.code AS skill
            FROM questions q
            JOIN question_versions v ON v.id = q.current_version_id
            JOIN question_reports r ON r.question_version_id = v.id
            JOIN question_classifications c
              ON c.question_id = q.id AND c.classification_role = 'primary'
            JOIN curriculum_items ci ON ci.id = c.curriculum_item_id
            WHERE r.reason = 'off_syllabus' AND r.status = 'open'
              AND q.retired_at IS NULL
              AND r.detail LIKE '%approved reading text%'
            ORDER BY q.exam_year, q.question_number
            """
        )
        in_range = await conn.fetch(
            """
            SELECT q.id AS question_id, v.id AS version_id, q.exam_year, ci.code AS skill
            FROM questions q
            JOIN question_versions v ON v.id = q.current_version_id
            JOIN subjects s ON s.id = q.subject_id
            JOIN examinations e ON e.id = s.examination_id
            LEFT JOIN question_classifications c
              ON c.question_id = q.id AND c.classification_role = 'primary'
            LEFT JOIN curriculum_items ci ON ci.id = c.curriculum_item_id
            WHERE e.short_name = 'UTME' AND s.code = 'ENG' AND q.retired_at IS NULL
              AND (q.exam_year, q.question_number::int) IN (
                SELECT * FROM unnest($1::int[], $2::int[]))
            ORDER BY q.exam_year, q.question_number
            """,
            [year for year, spans in RANGES.items() for low, high in spans
             for _ in range(low, high + 1)],
            [number for _, spans in RANGES.items() for low, high in spans
             for number in range(low, high + 1)],
        )
        seen = {row["question_id"] for row in rows}
        rows = list(rows) + [row for row in in_range if row["question_id"] not in seen]
        rows.sort(key=lambda row: row["exam_year"])
        misfiled = [row for row in rows if row["skill"] != "ENG.A.4.i"]
        by_year: dict[int, int] = {}
        for row in rows:
            by_year[row["exam_year"]] = by_year.get(row["exam_year"], 0) + 1

        print(f"{len(rows)} questions are set on an approved reading text.")
        for year in sorted(by_year):
            print(f"  {year}: {by_year[year]:3}  {TEXTS.get(year, 'text not named in the paper')}")
        print(f"{len(misfiled)} of them are still filed under comprehension and will be re-filed.")
        if not apply:
            print("\nDry run; pass --apply to re-file and retire them.")
            return 0

        skill_id = await conn.fetchval(
            """
            SELECT ci.id FROM curriculum_items ci
            JOIN syllabus_versions sv ON sv.id = ci.syllabus_version_id
            JOIN subjects s ON s.id = sv.subject_id
            JOIN examinations e ON e.id = s.examination_id
            WHERE ci.code = 'ENG.A.4.i' AND sv.version_label = 'utme-2027'
              AND e.short_name = 'UTME' AND s.code = 'ENG'
            """
        )
        if skill_id is None:
            raise SystemExit("no ENG.A.4.i skill in the current UTME English syllabus")

        async with conn.transaction():
            for row in misfiled:
                await conn.execute(
                    """
                    UPDATE question_classifications
                       SET curriculum_item_id = $2,
                           classification_reason = 'Set on the approved reading text, not on a '
                             'comprehension passage. Filed under comprehension only because the '
                             'paper prints them in the same block.',
                           reviewed_by = $3, reviewed_at = now()
                     WHERE question_id = $1 AND classification_role = 'primary'
                    """,
                    row["question_id"], skill_id, reviewer_id,
                )
            for row in rows:
                named = TEXTS.get(row["exam_year"])
                reason = (
                    f"Set on {named}, the approved reading text for that cycle. " + GENERAL
                    if named else GENERAL
                )
                await conn.execute(
                    """
                    UPDATE questions SET retired_at = now(), retired_reason = $2,
                      updated_at = now() WHERE id = $1
                    """,
                    row["question_id"], reason,
                )
                # A retired question's version must not read "approved". Most of these were
                # withdrawn before they were retired, because they came in through a report;
                # one reached here straight off the printed range while it was still live.
                await conn.execute(
                    """
                    UPDATE question_versions SET review_status = 'withdrawn'
                     WHERE id = $1 AND review_status = 'approved'
                    """,
                    row["version_id"],
                )
                await conn.execute(
                    """
                    UPDATE question_reports SET status = 'rejected', resolved_by = $2,
                      resolved_at = now(), resolution_note = $3
                     WHERE question_version_id = $1 AND status = 'open'
                    """,
                    row["version_id"], reviewer_id,
                    "Not fixed: the question was retired. The text it is set on has been "
                    "replaced, and licensing it would not make the question useful again.",
                )

        held = await conn.fetchval(
            """
            SELECT count(*) FROM questions q
            JOIN question_classifications c
              ON c.question_id = q.id AND c.classification_role = 'primary'
            JOIN curriculum_items ci ON ci.id = c.curriculum_item_id
            WHERE ci.code = 'ENG.A.4.i'
            """
        )
        print(f"\n{len(rows)} retired, {len(misfiled)} re-filed. "
              f"Approved Reading Text now holds {held} questions, all retired.")
        return 0
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    return asyncio.run(run(args.reviewer, args.database_url, args.apply))


if __name__ == "__main__":
    sys.exit(main())
