"""The generated parity vectors must stay in step with the engine (ADR-0005)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.fixtures import build
from engine.version import ENGINE_VERSION

VECTORS = Path(__file__).resolve().parents[3] / "packages" / "fixtures" / "vectors.json"


def test_every_case_has_a_unique_id() -> None:
    ids = [case["id"] for case in build()["cases"]]
    assert len(ids) == len(set(ids))


def test_all_rule_groups_are_covered() -> None:
    kinds = {case["kind"] for case in build()["cases"]}
    assert kinds == {
        "mastery.update",
        "mastery.retained",
        "mastery.chance_level",
        "ladder.next_level",
        "ladder.starting_level",
        "help.action",
    }


def test_checked_in_vectors_match_the_current_engine() -> None:
    if not VECTORS.exists():
        pytest.skip("vectors.json not generated yet — run `make fixtures`")

    stored = json.loads(VECTORS.read_text())
    # Compare through JSON so tuples and lists are not treated as different.
    current = json.loads(json.dumps(build()))

    assert stored["engine_version"] == ENGINE_VERSION, (
        "engine version changed; run `make fixtures` and review the diff"
    )
    assert stored == current, "vectors are stale; run `make fixtures` and review the diff"
