#!/usr/bin/env python3
"""Load written explanations onto approved questions.

    uv run python database/load_explanations.py \
        --explanations docs/questions/utme/english/explanations --apply

Explanations are the one part of an approved question that may be improved in place — 017
took solution_steps and hints out of the frozen set, kept the replaced text in
question_explanation_history, and made changing them require saying where the new text came
from. This is what says so: every question it touches gets solution_source = 'expert_verified',
because a person wrote the prose against the question. That is a claim about the prose and
about nothing else; the answer key's provenance is untouched.

Entries are keyed on the first eight characters of the question version's id, which is enough
to be unique within a subject and short enough to read. A key that no longer resolves is
reported rather than skipped: it means the question has been re-versioned or withdrawn since
the explanation was written, and the explanation needs checking against whatever replaced it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import asyncpg
import yaml

ROOT = Path(__file__).resolve().parent.parent


async def run(folder: Path, dsn: str | None, apply: bool) -> int:
    written: dict[str, dict[str, object]] = {}
    for path in sorted(folder.glob("*.yaml")):
        document = yaml.safe_load(path.read_text())
        for key, entry in (document.get("explanations") or {}).items():
            written[str(key)] = entry

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
        rows = await conn.fetch(
            """
            SELECT v.id, left(v.id::text, 8) AS short, v.review_status, v.solution_source,
                   v.solution_steps, v.hints
            FROM question_versions v
            JOIN questions q ON q.id = v.question_id AND q.current_version_id = v.id
            WHERE left(v.id::text, 8) = ANY($1::text[])
            """,
            list(written),
        )
        current = {row["short"]: row for row in rows}
        missing = sorted(set(written) - set(current))
        stale = [key for key, row in current.items() if row["review_status"] != "approved"]

        print(f"{len(written)} explanations written, {len(current)} match a current question.")
        if missing:
            print(
                f"{len(missing)} no longer resolve — the question was re-versioned or "
                f"withdrawn after the explanation was written: {', '.join(missing[:10])}"
            )
        if stale:
            print(f"{len(stale)} match a question that is no longer approved: {stale[:6]}")
        if not apply:
            print("\nDry run; pass --apply to write them.")
            return 0

        updated = 0
        unchanged = 0
        async with conn.transaction():
            for key, row in current.items():
                entry = written[key]
                steps = [str(step) for step in (entry.get("steps") or [])]
                hint = str(entry.get("hint") or "").strip()
                if not steps or not hint:
                    continue
                # Skip a row whose explanation is already exactly this. Re-running the loader
                # should be free, and an update that changes nothing still trips the rule that
                # a rewrite must restate its provenance.
                # asyncpg hands jsonb back as text, so these have to be parsed before they
                # can be compared; comparing the raw strings would never match.
                stored_steps = json.loads(row["solution_steps"] or "[]")
                stored_hints = json.loads(row["hints"] or "[]")
                if (
                    row["solution_source"] == "expert_verified"
                    and stored_steps == steps
                    and stored_hints == [hint]
                ):
                    unchanged += 1
                    continue
                await conn.execute(
                    """
                    UPDATE question_versions
                       SET solution_steps = $2::jsonb, hints = $3::jsonb,
                           solution_source = 'expert_verified'
                     WHERE id = $1
                    """,
                    row["id"],
                    json.dumps(steps),
                    json.dumps([hint]),
                )
                updated += 1

        waiting = await conn.fetchval(
            "SELECT count(*) FROM questions_awaiting_explanation_check"
        )
        print(
            f"{updated} explanations loaded, {unchanged} already as written."
        )
        print(f"{waiting} questions still waiting for one.")
        return 0
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--explanations", required=True)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    return asyncio.run(run(Path(args.explanations).resolve(), args.database_url, args.apply))


if __name__ == "__main__":
    sys.exit(main())
