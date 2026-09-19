#!/usr/bin/env python3
"""Re-point written explanations at the versions their questions now have.

    uv run python database/rekey_explanations.py \
        --explanations docs/questions/utme/english/explanations --apply

An explanation is filed under the first eight characters of the question version it was
written against. That is a good key while nothing moves, and every correction moves it: a
changed option or a corrected answer is a new version, so the file's key stops resolving and
the loader reports it as "no longer resolves". The explanation itself is not lost — the
correction scripts carry it onto the new version — but the file drifts away from the bank,
and after enough corrections most of it points at rows nobody reads.

So this walks the keys back to their question and forward to whatever version that question
is on now. The question is the thing that persists; the version is an address.

It refuses to merge. If a file already has an entry under the new address, the old one is
left where it is and reported, because two explanations for one question is a decision for a
person to make rather than a rename to guess at.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parent.parent


def keys_in(path: Path) -> list[str]:
    """Every explanation key in a YAML file, in the order it appears.

    Read with a regex rather than a YAML parse because the files are rewritten in place and
    the comments above each section are part of what a reviewer reads. A load-and-dump would
    lose them.
    """
    return re.findall(r"^  ([0-9a-f]{8}):\s*$", path.read_text(), re.M)


async def run(folder: Path, dsn: str | None, apply: bool) -> int:
    conn = await asyncpg.connect(
        dsn=dsn,
        host=None if dsn else str(ROOT / ".local/run"),
        port=None if dsn else 55439,
        database=None if dsn else "scorepilot",
    )
    try:
        await conn.execute("SET search_path = stackprep, public")
        files = sorted(folder.glob("*.yaml"))
        corrections = folder / "key_corrections.json"
        wanted = {key for path in files for key in keys_in(path)}
        if corrections.exists():
            wanted |= set(json.loads(corrections.read_text()))

        rows = await conn.fetch(
            """
            SELECT left(old.id::text, 8) AS was, left(now_.id::text, 8) AS is_now
            FROM question_versions old
            JOIN questions q ON q.id = old.question_id
            JOIN question_versions now_ ON now_.id = q.current_version_id
            WHERE left(old.id::text, 8) = ANY($1::text[])
            """,
            sorted(wanted),
        )
        moved = {row["was"]: row["is_now"] for row in rows if row["was"] != row["is_now"]}
        print(f"{len(wanted)} keys in the files; {len(moved)} point at a superseded version.")

        changed = clashed = 0
        for path in files:
            text = path.read_text()
            present = set(keys_in(path))
            for was, is_now in moved.items():
                if was not in present:
                    continue
                if is_now in present:
                    print(f"  {path.name}: {was} -> {is_now}, which already has an entry; left")
                    clashed += 1
                    continue
                text = text.replace(f"\n  {was}:\n", f"\n  {is_now}:\n")
                present.discard(was)
                present.add(is_now)
                changed += 1
            if apply:
                path.write_text(text)

        if corrections.exists():
            recorded = json.loads(corrections.read_text())
            renamed = {moved.get(key, key): value for key, value in recorded.items()}
            if apply:
                corrections.write_text(json.dumps(dict(sorted(renamed.items())), indent=2) + "\n")

        print(f"{changed} explanation(s) re-pointed, {clashed} left for a person to settle.")
        if not apply:
            print("\nDry run; pass --apply to rewrite the files.")
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
