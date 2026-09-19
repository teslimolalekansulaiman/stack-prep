#!/usr/bin/env python3
"""Retire the questions whose key is wrong and whose options offer nothing to correct it to.

    uv run python database/drop_unfixable_questions.py \
        --reviewer <academic_reviewers.id> --apply

WHY THESE ARE DIFFERENT. A wrong key with a right option among the others is a correction: the
key moves and the question comes back. These are the remainder — the printed key contradicts
the question AND no option reads correctly, so there is nothing to move the key to. "No
alternative than to hold you responsible" wants but, "the past participle of split" wants
split, and neither word is among the four. The question would have to be rewritten, and a
rewritten question is a new question rather than a corrected one.

RETIRED, NOT DELETED. retired_at takes them out of every view a student or a plan reads, and
the schema insists on a reason beside it. The rows stay: the question, its options, its written
explanation, its report, and any attempt a student made on it. Someone who wants to write a
replacement has the original in front of them, and a student's history still says what they
were asked.

The list is not typed out here. It is exactly the set whose current version is withdrawn with
an unresolved wrong-answer report — which is what the earlier passes left behind, and which
reads back the same way in six months.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parent.parent

REASON = (
    "The published answer key contradicts the question and no option reads correctly, so "
    "there is nothing to correct the key to. Retired on review; the question would have to "
    "be rewritten rather than fixed."
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
            SELECT q.id AS question_id, v.id AS version_id, q.exam_year, q.question_number,
                   left(v.stem, 64) AS stem
            FROM questions q
            JOIN question_versions v ON v.id = q.current_version_id
            JOIN question_reports r ON r.question_version_id = v.id
            WHERE v.review_status = 'withdrawn'
              AND r.reason = 'wrong_answer' AND r.status = 'open'
              AND q.retired_at IS NULL
            ORDER BY q.exam_year, q.question_number
            """
        )
        print(f"{len(rows)} questions have a wrong key and no option to correct it to.")
        for row in rows:
            print(f"  {row['exam_year']} Q{row['question_number']}: {row['stem']}")
        if not apply:
            print("\nDry run; pass --apply to retire them.")
            return 0

        async with conn.transaction():
            for row in rows:
                await conn.execute(
                    """
                    UPDATE questions SET retired_at = now(), retired_reason = $2,
                      updated_at = now()
                     WHERE id = $1
                    """,
                    row["question_id"],
                    REASON,
                )
                await conn.execute(
                    """
                    UPDATE question_reports SET status = 'rejected', resolved_by = $2,
                      resolved_at = now(), resolution_note = $3
                     WHERE question_version_id = $1 AND status = 'open'
                    """,
                    row["version_id"],
                    reviewer_id,
                    "Not fixed: the question was retired instead, because no option reads "
                    "correctly and the key had nothing to be corrected to.",
                )

        deliverable = await conn.fetchval(
            """
            SELECT count(*) FROM deliverable_questions d
            JOIN subjects s ON s.id = d.subject_id
            JOIN examinations e ON e.id = s.examination_id
            WHERE e.short_name = 'UTME' AND s.code = 'ENG'
            """
        )
        remaining = await conn.fetchval(
            "SELECT count(*) FROM question_reports"
            " WHERE reason = 'wrong_answer' AND status = 'open'"
        )
        print(f"\n{len(rows)} retired. {deliverable} UTME English questions deliverable, "
              f"{remaining} key reports still open.")
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
