#!/usr/bin/env python3
"""Carry a corrected key back into the explanation the correction was argued from.

    uv run python database/settle_corrected_explanations.py \
        --explanations docs/questions/utme/english/explanations --apply

An explanation written while a key was in doubt says so: "the published key gives penury ...
and this question is flagged for a second look". take_the_reading.py then corrects the key and
rewrites that clause on the version it writes, so the board tells a student the truth. What it
cannot do is reach back into the file the explanation was written in, which still argues a
question that has been settled.

That was survivable while the file's keys pointed at superseded versions and the loader
skipped them. It stopped being survivable the moment rekey_explanations.py pointed them at the
live versions: the next load wrote the doubt back over the settled text.

So the same rewrite is applied to the file, from the same function, using the key printed with
the source — version 1's, which is what the paper's own answer key said — and the key the
question carries now.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from take_the_reading import settle  # noqa: E402


def entry_span(text: str, key: str) -> tuple[int, int] | None:
    """Where one explanation's block starts and ends in the file."""
    start = re.search(rf"^  {key}:$", text, re.M)
    if start is None:
        return None
    nxt = re.search(r"^  [0-9a-f]{8}:$", text[start.end():], re.M)
    return start.start(), (start.end() + nxt.start() if nxt else len(text))


def rewrite(block: str, steps: list[str]) -> str:
    """Replace a block's steps, leaving its hint and any comments where they are."""
    body = "".join(f"      - {json.dumps(step, ensure_ascii=False)}\n" for step in steps)
    return re.sub(
        r"(^    steps:\n)(?:^      - .*\n)+",
        lambda m: m.group(1) + body,
        block,
        count=1,
        flags=re.M,
    )


async def run(folder: Path, dsn: str | None, apply: bool) -> int:
    corrections = json.loads((folder / "key_corrections.json").read_text())
    conn = await asyncpg.connect(
        dsn=dsn,
        host=None if dsn else str(ROOT / ".local/run"),
        port=None if dsn else 55439,
        database=None if dsn else "scorepilot",
    )
    try:
        await conn.execute("SET search_path = stackprep, public")
        rows = await conn.fetch(
            """
            SELECT left(v.id::text, 8) AS short,
                   (SELECT o.option_key FROM question_options o
                     JOIN question_versions first ON first.id = o.question_version_id
                    WHERE first.question_id = v.question_id AND first.version = 1
                      AND o.is_correct) AS printed
            FROM question_versions v
            WHERE left(v.id::text, 8) = ANY($1::text[])
            """,
            sorted(corrections),
        )
        printed = {row["short"]: row["printed"] for row in rows}

        settled = missing = unchanged = 0
        for path in sorted(folder.glob("*.yaml")):
            text = path.read_text()
            for key, now in corrections.items():
                span = entry_span(text, key)
                if span is None:
                    continue
                was = printed.get(key)
                if was is None or was == now:
                    missing += 1
                    continue
                block = text[span[0]:span[1]]
                steps = re.findall(r"^      - (.*)$", block, re.M)
                fresh = settle([json.loads(step) for step in steps], was, now)
                after = rewrite(block, fresh)
                if after == block:
                    unchanged += 1
                    continue
                text = text[:span[0]] + after + text[span[1]:]
                settled += 1
            if apply:
                path.write_text(text)

        print(f"{len(corrections)} corrected keys; {settled} explanation(s) rewritten to say so.")
        if unchanged:
            print(f"  {unchanged} already settled.")
        if missing:
            print(f"  {missing} could not be matched to the key printed with the source.")
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
