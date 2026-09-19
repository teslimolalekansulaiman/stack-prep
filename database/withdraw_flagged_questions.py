#!/usr/bin/env python3
"""Withdraw questions whose explanations say they cannot stand as printed.

    uv run python database/withdraw_flagged_questions.py \
        --explanations docs/questions/utme/english/explanations \
        --reviewer <academic_reviewers.id> --apply

WHERE THE LIST COMES FROM. Writing a worked explanation means reading the question properly,
and reading them properly turned up questions that cannot be answered as printed. Each one has
a sentence in its own explanation saying so, and that sentence is the record: this script does
not decide anything, it acts on decisions already written down and reviewable in the YAML.

Three kinds, and they are counted separately because they are different failures:

  * The published key is wrong. Not a parser fault — the direction is read correctly and the
    third-party key simply disagrees with the English. "Averred" keyed as "denied", "frugality"
    as "extravagance", "ignoble" as "honourable". This is the risk migration 011 named when it
    refused to call that key official, now measured rather than assumed.
  * The question is not an English question. "Which Question Paper Type is given to you?" is an
    invigilator's instruction that the import filter should have caught.
  * The passage the question asks about was never fully captured, so nothing in the stored text
    settles it.

WITHDRAWN, NOT DELETED. A student may have answered one of these, and their attempt still
points at the version. Withdrawing takes it out of `deliverable_questions` immediately —
nobody is asked it again — while leaving the row, the explanation and the reason in place for
whoever fixes the key.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import asyncpg
import yaml

ROOT = Path(__file__).resolve().parent.parent

#: Categories this script withdraws, and the sentence recorded against each question.
REASONS = {
    "key-suspect": (
        "The published answer key does not agree with the English of the question. Withdrawn "
        "until a person decides the key; the written explanation says which option the "
        "language actually supports."
    ),
    "paper-type": (
        "Not an English question: it asks which question paper type the candidate was given. "
        "Withdrawn, and the import filter that catches these needs widening."
    ),
    "passage-truncated": (
        "The passage this question asks about was not fully captured at import, so nothing in "
        "the stored text settles it. Withdrawn until the passage is restored."
    ),
}


#: The reason code each kind is filed under, so the review queue can be worked one kind at a
#: time: a wrong key is a different job from a missing passage.
CODES = {
    "key-suspect": "wrong_answer",
    "paper-type": "off_syllabus",
    "passage-truncated": "image_missing",
}


def flagged(folder: Path) -> dict[str, str]:
    """Question versions whose own explanation says they cannot stand, and why."""
    found: dict[str, str] = {}
    for path in sorted(folder.glob("*.yaml")):
        document = yaml.safe_load(path.read_text())
        for vid, entry in (document.get("explanations") or {}).items():
            text = " ".join(entry.get("steps") or [])
            if "flagged" not in text:
                continue
            if "removal" in text or "not an English question" in text:
                category = "paper-type"
            elif "unanswerable" in text or "does not reach" in text:
                category = "passage-truncated"
            elif "re-classification" in text:
                # Already put right by the parser; nothing to withdraw.
                continue
            else:
                category = "key-suspect"
            found[str(vid)] = category
    return found


async def run(folder: Path, reviewer_id: str, dsn: str | None, apply: bool) -> int:
    marked = flagged(folder)
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
            SELECT v.id, left(v.id::text, 8) AS short, v.review_status, q.exam_year,
                   q.question_number
            FROM question_versions v
            JOIN questions q ON q.id = v.question_id AND q.current_version_id = v.id
            WHERE left(v.id::text, 8) = ANY($1::text[])
            """,
            list(marked),
        )
        live = [row for row in rows if row["review_status"] == "approved"]
        counts: dict[str, int] = {}
        for row in live:
            counts[marked[row["short"]]] = counts.get(marked[row["short"]], 0) + 1

        print(f"{len(marked)} questions are flagged in their explanations.")
        for category, count in sorted(counts.items()):
            print(f"  {count:3}  {category}")
        missing = len(marked) - len(rows)
        if missing:
            print(f"  {missing} no longer resolve to a current version and are skipped.")
        if not apply:
            print("\nDry run; pass --apply to withdraw them.")
            return 0

        async with conn.transaction():
            for row in live:
                await conn.execute(
                    """
                    UPDATE question_versions
                       SET review_status = 'withdrawn', reviewed_by = $2, reviewed_at = now()
                     WHERE id = $1
                    """,
                    row["id"],
                    reviewer_id,
                )
                category = marked[row["short"]]
                await conn.execute(
                    """
                    INSERT INTO question_reports (question_version_id, reporter_kind, reason,
                      detail, status)
                    VALUES ($1, 'system', $2, $3, 'open')
                    """,
                    row["id"],
                    CODES[category],
                    REASONS[category],
                )

        remaining = await conn.fetchval(
            """
            SELECT count(*) FROM deliverable_questions d
            JOIN subjects s ON s.id = d.subject_id
            JOIN examinations e ON e.id = s.examination_id
            WHERE e.short_name = 'UTME' AND s.code = 'ENG'
            """
        )
        print(f"\n{len(live)} withdrawn. {remaining} UTME English questions still deliverable.")
        return 0
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--explanations", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    return asyncio.run(
        run(Path(args.explanations).resolve(), args.reviewer, args.database_url, args.apply)
    )


if __name__ == "__main__":
    sys.exit(main())
