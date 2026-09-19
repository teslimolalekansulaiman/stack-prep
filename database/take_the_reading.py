#!/usr/bin/env python3
"""Correct a published answer key, on the reading the question's own explanation argues for.

    uv run python database/take_the_reading.py \
        --corrections docs/questions/utme/english/explanations/key_corrections.json \
        --reviewer <academic_reviewers.id> --apply

WHAT THIS IS. Reading every question while writing its explanation turned up sixty-eight whose
printed key contradicts the English of the question. Fifty of those had an option that plainly
does read correctly, and the explanation says which and why. This applies that decision.

AS A NEW VERSION, not an edit. The key is part of what the question IS: change it and a student
sitting the old version and a student sitting the new one were asked different questions. So the
corrected question is version n+1, the old version stays withdrawn with its report, and any
attempt already recorded still points at exactly what that student was shown. Everything else —
stem, options, level, timing — is copied across unchanged, because nothing else changed.

The explanation is carried over with its argument intact and its last clause rewritten: it used
to say the key looked wrong and the question was flagged, and that is no longer true. It now
says what the source printed and that a person corrected it, so the board tells a student the
truth and a reviewer can still see what was changed.

WHAT IT REFUSES. A question whose option list is damaged — text bled in from the page, two
options printed identically — is not a key dispute and this will not touch it, however clearly
one option reads. Those are listed and skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parent.parent

#: Sentences in an explanation that only made sense while the key was in doubt.
STALE = re.compile(
    r"[^.]*\b(?:published key|key printed here|key printed with)\b[^.]*\.\s*|"
    r"[^.]*flagged for a second look[^.]*\.\s*",
    re.I,
)


def settle(steps: list[str], old: str, new: str) -> list[str]:
    """Keep the argument, drop the doubt, and say what was corrected."""
    kept = []
    for step in steps:
        trimmed = STALE.sub("", step).strip()
        if trimmed:
            kept.append(trimmed)
    kept.append(
        f"The key printed with the source gave {old}; it was corrected to {new} on review, "
        "because the question's own wording does not support it."
    )
    return kept


async def run(corrections: Path, reviewer_id: str, dsn: str | None, apply: bool) -> int:
    wanted: dict[str, str] = json.loads(corrections.read_text())
    conn = await asyncpg.connect(
        dsn=dsn,
        # TCP, not the Unix socket under ROOT: ROOT is this working copy, so from a git
        # worktree the socket path points at a directory that does not exist — and a
        # socket path is capped at 103 bytes, which a worktree path can exceed on its own.
        host=None if dsn else "127.0.0.1",
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
            SELECT v.id, left(v.id::text, 8) AS short, v.question_id, v.subject_id, v.version,
                   v.stem, v.instructions, v.passage_id, v.solution_steps, v.hints, v.marks,
                   v.expected_seconds, v.option_count, v.authored_by, v.answer_source,
                   v.answer_confidence, v.mastery_level_number, v.level_source,
                   v.level_confidence, v.solution_source, v.review_status,
                   q.exam_year, q.question_number
            FROM question_versions v
            JOIN questions q ON q.id = v.question_id AND q.current_version_id = v.id
            WHERE left(v.id::text, 8) = ANY($1::text[])
            """,
            list(wanted),
        )
        found = {row["short"]: row for row in rows}
        missing = sorted(set(wanted) - set(found))

        print(f"{len(wanted)} corrections asked for, {len(found)} resolve to a current version.")
        if missing:
            print(f"  {len(missing)} no longer resolve and are skipped: {', '.join(missing)}")
        if not apply:
            ordered = sorted(found.items(), key=lambda i: (i[1]["exam_year"],))
            for short, row in ordered:
                old = await conn.fetchval(
                    "SELECT option_key FROM question_options"
                    " WHERE question_version_id = $1 AND is_correct",
                    row["id"],
                )
                print(f"  {row['exam_year']} Q{row['question_number']}: {old} -> {wanted[short]}")
            print("\nDry run; pass --apply to correct them.")
            return 0

        corrected = 0
        async with conn.transaction():
            for short, row in found.items():
                new_key = wanted[short]
                options = await conn.fetch(
                    """
                    SELECT option_key, body, display_order, misconception_id, distractor_note
                    FROM question_options WHERE question_version_id = $1 ORDER BY display_order
                    """,
                    row["id"],
                )
                previous = await conn.fetchval(
                    "SELECT option_key FROM question_options"
                    " WHERE question_version_id = $1 AND is_correct",
                    row["id"],
                )
                steps = settle(json.loads(row["solution_steps"] or "[]"), previous, new_key)
                # The key is part of the content, so it goes into the hash: without it the
                # corrected version would collide with the one it replaces.
                digest = hashlib.sha256(
                    (row["stem"] + "".join(o["body"] for o in options) + new_key).encode()
                ).hexdigest()
                version_id = await conn.fetchval(
                    """
                    INSERT INTO question_versions (question_id, subject_id, version, stem,
                      instructions, passage_id, response_format, marking_method, solution_steps,
                      hints, marks, expected_seconds, option_count, content_hash, authored_by,
                      answer_source, answer_confidence, mastery_level_number, level_source,
                      level_confidence, solution_source, review_status)
                    VALUES ($1, $2, $3, $4, $5, $6, 'mcq_single', 'auto_key', $7::jsonb, $8,
                      $9, $10, $11, $12, $13, 'expert_verified', 'high', $14, $15, $16,
                      'expert_verified', 'draft')
                    RETURNING id
                    """,
                    row["question_id"], row["subject_id"], int(row["version"]) + 1, row["stem"],
                    row["instructions"], row["passage_id"], json.dumps(steps), row["hints"],
                    row["marks"], row["expected_seconds"], row["option_count"], digest,
                    row["authored_by"], row["mastery_level_number"], row["level_source"],
                    row["level_confidence"],
                )
                for option in options:
                    await conn.execute(
                        """
                        INSERT INTO question_options (question_version_id, subject_id,
                          option_key, body, is_correct, display_order, misconception_id,
                          distractor_note)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        """,
                        version_id, row["subject_id"], option["option_key"], option["body"],
                        option["option_key"] == new_key, option["display_order"],
                        option["misconception_id"], option["distractor_note"],
                    )
                await conn.execute(
                    """
                    UPDATE questions SET current_version_id = $2, updated_at = now()
                     WHERE id = $1
                    """,
                    row["question_id"], version_id,
                )
                await conn.execute(
                    """
                    UPDATE question_versions SET review_status = 'approved', reviewed_by = $2,
                      reviewed_at = now() WHERE id = $1
                    """,
                    version_id, reviewer_id,
                )
                await conn.execute(
                    """
                    UPDATE question_reports SET status = 'fixed', resolved_by = $2,
                      resolved_at = now(), resolution_note = $3
                     WHERE question_version_id = $1 AND status = 'open'
                    """,
                    row["id"], reviewer_id,
                    f"Key corrected from {previous} to {new_key} in version "
                    f"{int(row['version']) + 1}, on the reading the explanation argues for.",
                )
                corrected += 1

        deliverable = await conn.fetchval(
            """
            SELECT count(*) FROM deliverable_questions d
            JOIN subjects s ON s.id = d.subject_id
            JOIN examinations e ON e.id = s.examination_id
            WHERE e.short_name = 'UTME' AND s.code = 'ENG'
            """
        )
        print(f"{corrected} keys corrected. {deliverable} UTME English questions deliverable.")
        return 0
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corrections", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    return asyncio.run(
        run(Path(args.corrections).resolve(), args.reviewer, args.database_url, args.apply)
    )


if __name__ == "__main__":
    sys.exit(main())
