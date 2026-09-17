"""Command line entry points.

    uv run python -m app.cli migrate     apply pending SQL migrations
    uv run python -m app.cli baseline    record existing migrations as applied
    uv run python -m app.cli openapi     print the OpenAPI schema
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.migrations import apply_pending, baseline


def _migrate() -> int:
    applied = asyncio.run(apply_pending())
    if not applied:
        print("Schema is up to date.")
    else:
        for version in applied:
            print(f"Applied {version}")
    return 0


def _baseline() -> int:
    recorded = asyncio.run(baseline())
    if not recorded:
        print("Every migration was already recorded.")
    else:
        for version in recorded:
            print(f"Recorded {version} as applied (not run)")
        print("Verify the schema matches these files before trusting the ledger.")
    return 0


def _openapi() -> int:
    from app.main import app

    json.dump(app.openapi(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    parser.add_argument("command", choices=["migrate", "baseline", "openapi"])
    args = parser.parse_args(argv)
    return {"migrate": _migrate, "baseline": _baseline, "openapi": _openapi}[args.command]()


if __name__ == "__main__":
    raise SystemExit(main())
