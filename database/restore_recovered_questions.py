#!/usr/bin/env python3
"""Bring back questions a parser fix has recovered.

    uv run python database/restore_recovered_questions.py \
        --transcriptions docs/questions/utme/english \
        --reviewer <academic_reviewers.id> --apply

A question withdrawn because its stem was lost is not withdrawn on a judgement — it is
withdrawn on a defect, and a defect can be fixed. When the parser is corrected and the
re-parse produces a real stem where there was "Gap 23 in the cloze passage", the question
comes back.

It comes back as a NEW VERSION, for the same reason a corrected key does: the stem is what
the question IS, and a student who saw the broken one was asked something else. The damaged
version stays withdrawn with its report resolved, so their attempt still points at what they
were actually shown.

It comes back as a DRAFT. The recovered text has never been read by anyone, and the level,
timing and explanation all have to be settled before it can be approved — which is the normal
route every other question took. Nothing here shortcuts that.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from pathlib import Path

import asyncpg
import yaml

ROOT = Path(__file__).resolve().parent.parent

EXAMINATION = "UTME"
SUBJECT = "ENG"


def levels(folder: Path) -> dict[tuple[int, str], dict]:
    """The proposed difficulty for each question, from the levels files beside the papers.

    A restored version is a new row and does not inherit the level the loader set on the
    original, so it is read here rather than left null — a question with no level cannot be
    approved, and leaving it to be noticed later is how a restored question quietly never
    comes back.
    """
    found = {}
    for path in sorted(folder.glob("levels_*.yaml")):
        document = yaml.safe_load(path.read_text())
        year = int(document["paper"]["exam_year"])
        for entry in document["levels"]:
            found[(year, str(entry["number"]))] = entry
    return found


def transcribed(folder: Path) -> dict[tuple[int, str], dict]:
    found = {}
    for path in sorted(folder.glob("transcription_*.yaml")):
        document = yaml.safe_load(path.read_text())
        year = int(document["source"]["exam_year"])
        for question in document["questions"]:
            found[(year, str(question["number"]))] = question
    return found


async def run(folder: Path, reviewer_id: str, dsn: str | None, apply: bool) -> int:
    latest = transcribed(folder)
    proposed = levels(folder)
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
        subject_id = await conn.fetchval(
            """
            SELECT s.id FROM subjects s JOIN examinations e ON e.id = s.examination_id
            WHERE s.code = $1 AND e.short_name = $2
            """,
            SUBJECT, EXAMINATION,
        )

        rows = await conn.fetch(
            """
            SELECT q.id AS question_id, q.exam_year, q.question_number, v.id AS version_id,
                   v.version, v.stem, v.instructions, v.passage_id, v.marks,
                   v.expected_seconds, v.authored_by
            FROM questions q
            JOIN question_versions v ON v.id = q.current_version_id
            WHERE q.subject_id = $1 AND q.retired_at IS NULL
              AND v.review_status = 'withdrawn'
            ORDER BY q.exam_year, q.question_number
            """,
            subject_id,
        )

        recovered = []
        for row in rows:
            question = latest.get((int(row["exam_year"]), str(row["question_number"])))
            if question is None:
                continue
            # Recovered means the re-parse now has a stem that is not the placeholder, and
            # differs from what is stored. A question whose stem is unchanged was withdrawn for
            # some other reason and is left alone.
            stem = str(question.get("stem") or "").strip()
            if not stem or stem.startswith("Gap ") or stem == (row["stem"] or "").strip():
                continue
            recovered.append((row, question))

        print(f"{len(rows)} withdrawn questions; {len(recovered)} now have a recovered stem.")
        for row, question in recovered:
            print(f"  {row['exam_year']} Q{row['question_number']}: {question['stem'][:62]}")
        if not apply:
            print("\nDry run; pass --apply to restore them as drafts.")
            return 0

        restored = 0
        async with conn.transaction():
            for row, question in recovered:
                options = dict(question["options"])
                answer = str(question.get("proposed_answer") or "").upper()
                if answer not in options:
                    continue
                level = proposed.get(
                    (int(row["exam_year"]), str(row["question_number"])), {}
                )
                digest = hashlib.sha256(
                    (question["stem"] + "".join(options[k] for k in sorted(options)) + answer)
                    .encode()
                ).hexdigest()
                version_id = await conn.fetchval(
                    """
                    INSERT INTO question_versions (question_id, subject_id, version, stem,
                      instructions, passage_id, response_format, marking_method, solution_steps,
                      hints, marks, expected_seconds, option_count, content_hash, authored_by,
                      answer_source, answer_confidence, mastery_level_number, level_source,
                      level_confidence, review_status)
                    VALUES ($1, $2, $3, $4, $5, $6, 'mcq_single', 'auto_key', '[]'::jsonb,
                      '[]'::jsonb, $7, $8, $9, $10, $11, 'published_key', 'medium', $12,
                      'model_proposed', $13, 'draft')
                    RETURNING id
                    """,
                    row["question_id"], subject_id, int(row["version"]) + 1, question["stem"],
                    question.get("instruction"), row["passage_id"], row["marks"],
                    row["expected_seconds"], len(options), digest, row["authored_by"],
                    level.get("proposed_level"), level.get("level_confidence", "low"),
                )
                for order, letter in enumerate(sorted(options), 1):
                    await conn.execute(
                        """
                        INSERT INTO question_options (question_version_id, subject_id,
                          option_key, body, is_correct, display_order)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                        version_id, subject_id, letter, options[letter],
                        letter == answer, order,
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
                    UPDATE question_reports SET status = 'fixed', resolved_by = $2,
                      resolved_at = now(), resolution_note = $3
                     WHERE question_version_id = $1 AND status = 'open'
                    """,
                    row["version_id"], reviewer_id,
                    f"Fixed by a parser correction: the stem was recovered and restored as "
                    f"version {int(row['version']) + 1}, which starts again as a draft.",
                )
                restored += 1

        print(f"\n{restored} restored as drafts. They need a level, timing and an explanation "
              "before they can be approved.")
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
