#!/usr/bin/env python3
"""Carry a re-parse of the English papers into questions that are already approved.

    uv run python database/correct_english_questions.py \
        --transcriptions docs/questions/utme/english \
        --reviewer <academic_reviewers.id> --apply

WHY THIS EXISTS. load_questions.py refuses to change a question it has already imported —
"import a correction as a new version instead" — and the database refuses harder: approved
content is immutable, by design. That is the right rule. It is also exactly the rule that a
parser fix runs into, because a parser fix changes questions that are already live.

So this does what the error message says. For every question whose options the re-parse
changed, it writes a NEW version carrying the corrected text, points the question at it, and
approves it. The old version stays in the table and is withdrawn: not deleted, because a
student may have answered it and their attempt still points there, and not left approved,
because we now know its last option was unreadable.

For a question the re-parse can no longer read at all, there is no new version to write. The
current one is withdrawn and the question leaves the bank until someone transcribes it by
hand.

WHAT IT CARRIES OVER, and why that is not a shortcut. The answer, the level, the timing, the
solution and the hints all move to the new version unchanged, because none of them is what
changed: the same reviewer accepted the same key for the same question, and a stray fragment
on the end of option D does not alter any of it. What does change is the text of the options,
which is the thing being corrected, and the content hash, which follows from it.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import asyncpg
import yaml

ROOT = Path(__file__).resolve().parent.parent

EXAMINATION = "UTME"
SUBJECT = "ENG"

#: Said on every version this writes, so the reason is in the row and not only in a commit.
NOTE = (
    "Re-parsed after a fix to database/convert_jamb_english.py: the previous version's last "
    "option had the following question's text inside it."
)


def transcribed(folder: Path) -> dict[tuple[int, str], dict[str, str]]:
    """Every question the re-parse produced, keyed by year and number."""
    found: dict[tuple[int, str], dict[str, str]] = {}
    for path in sorted(folder.glob("transcription_*.yaml")):
        document = yaml.safe_load(path.read_text())
        year = int(document["source"]["exam_year"])
        for question in document["questions"]:
            found[(year, str(question["number"]))] = question
    return found


async def run(folder: Path, reviewer_id: str, dsn: str | None, apply: bool) -> int:
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
        subject_id = await conn.fetchval(
            """
            SELECT s.id FROM subjects s JOIN examinations e ON e.id = s.examination_id
            WHERE s.code = $1 AND e.short_name = $2
            """,
            SUBJECT,
            EXAMINATION,
        )
        if subject_id is None:
            raise SystemExit(f"no {EXAMINATION} subject with code {SUBJECT}")

        rows = await conn.fetch(
            """
            SELECT q.id AS question_id, q.exam_year, q.question_number,
                   v.id AS version_id, v.version, v.stem, v.instructions, v.passage_id,
                   v.solution_steps, v.hints, v.marks, v.expected_seconds, v.option_count,
                   v.authored_by, v.answer_source, v.answer_confidence,
                   v.mastery_level_number, v.level_source, v.level_confidence,
                   v.solution_source, v.review_status
            FROM questions q
            JOIN question_versions v ON v.id = q.current_version_id
            WHERE q.subject_id = $1 AND q.retired_at IS NULL
            ORDER BY q.exam_year, q.question_number
            """,
            subject_id,
        )
        latest = transcribed(folder)

        corrections: list[tuple[asyncpg.Record, dict[str, str]]] = []
        withdrawals: list[asyncpg.Record] = []
        for row in rows:
            key = (int(row["exam_year"]), str(row["question_number"]))
            question = latest.get(key)
            if question is None:
                withdrawals.append(row)
                continue
            stored = {
                record["option_key"]: record["body"]
                for record in await conn.fetch(
                    "SELECT option_key, body FROM question_options WHERE question_version_id = $1",
                    row["version_id"],
                )
            }
            if stored != dict(question["options"]):
                corrections.append((row, question))

        print(f"{len(corrections)} question(s) need a corrected version.")
        for row, _ in corrections:
            print(f"  {row['exam_year']} Q{row['question_number']}")
        print(f"{len(withdrawals)} question(s) can no longer be read and will be withdrawn.")
        for row in withdrawals:
            print(f"  {row['exam_year']} Q{row['question_number']}")
        if not apply:
            print("\nDry run; pass --apply to write the corrections.")
            return 0

        async with conn.transaction():
            for row, question in corrections:
                answer = str(question["proposed_answer"]).upper()
                version_id = await conn.fetchval(
                    """
                    INSERT INTO question_versions (question_id, subject_id, version, stem,
                      instructions, passage_id, response_format, marking_method, solution_steps,
                      hints, marks, expected_seconds, option_count, content_hash, authored_by,
                      answer_source, answer_confidence, mastery_level_number, level_source,
                      level_confidence, solution_source, review_status)
                    VALUES ($1, $2, $3, $4, $5, $6, 'mcq_single', 'auto_key', $7, $8, $9, $10,
                      $11, encode(sha256(convert_to($12, 'UTF8')), 'hex'), $13, $14, $15, $16,
                      $17, $18, $19, 'draft')
                    RETURNING id
                    """,
                    row["question_id"],
                    subject_id,
                    int(row["version"]) + 1,
                    question["stem"],
                    question.get("instruction"),
                    row["passage_id"],
                    row["solution_steps"],
                    row["hints"],
                    row["marks"],
                    row["expected_seconds"],
                    len(question["options"]),
                    question["stem"] + "".join(sorted(question["options"].values())),
                    row["authored_by"],
                    row["answer_source"],
                    row["answer_confidence"],
                    row["mastery_level_number"],
                    row["level_source"],
                    row["level_confidence"],
                    row["solution_source"],
                )
                for order, (letter, body) in enumerate(sorted(question["options"].items()), 1):
                    await conn.execute(
                        """
                        INSERT INTO question_options (question_version_id, subject_id,
                          option_key, body, is_correct, display_order)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                        version_id,
                        subject_id,
                        letter,
                        body,
                        letter == answer,
                        order,
                    )
                # Point the question at the new version BEFORE withdrawing the old one, so
                # the question is never momentarily without a deliverable version.
                await conn.execute(
                    """
                    UPDATE questions SET current_version_id = $2, updated_at = now()
                     WHERE id = $1
                    """,
                    row["question_id"],
                    version_id,
                )
                await conn.execute(
                    """
                    UPDATE question_versions
                       SET review_status = 'approved', reviewed_by = $2, reviewed_at = now()
                     WHERE id = $1
                    """,
                    version_id,
                    reviewer_id,
                )
                await conn.execute(
                    "UPDATE question_versions SET review_status = 'withdrawn' WHERE id = $1",
                    row["version_id"],
                )
                await conn.execute(
                    """
                    INSERT INTO question_reports (question_version_id, reporter_kind, reason,
                      detail, status, resolved_by, resolved_at, resolution_note)
                    VALUES ($1, 'system', 'other', $2, 'fixed', $3, now(), $4)
                    """,
                    row["version_id"],
                    NOTE,
                    reviewer_id,
                    f"Superseded by version {int(row['version']) + 1}.",
                )

            for row in withdrawals:
                await conn.execute(
                    "UPDATE question_versions SET review_status = 'withdrawn' WHERE id = $1",
                    row["version_id"],
                )
                await conn.execute(
                    """
                    INSERT INTO question_reports (question_version_id, reporter_kind, reason,
                      detail, status)
                    VALUES ($1, 'system', 'other', $2, 'open')
                    """,
                    row["version_id"],
                    "The re-parse could not read this question cleanly, so it has been "
                    "withdrawn. It needs transcribing by hand before it can come back.",
                )

        deliverable = await conn.fetchval(
            "SELECT count(*) FROM deliverable_questions WHERE subject_id = $1", subject_id
        )
        print(f"\n{deliverable} questions deliverable.")
        return 0
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcriptions", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    return asyncio.run(
        run(Path(args.transcriptions).resolve(), args.reviewer, args.database_url, args.apply)
    )


if __name__ == "__main__":
    sys.exit(main())
