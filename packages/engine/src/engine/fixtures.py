"""Generate the parity vectors shared with the TypeScript engine slice (ADR-0005).

    make fixtures      # writes packages/fixtures/vectors.json

Both test suites run these cases. Never hand-edit the output: change the rules,
regenerate, and review the diff.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Any

from engine.help import help_action
from engine.ladder import needs_prerequisite_probe, next_level, starting_level
from engine.mastery import (
    Attempt,
    SkillRating,
    band,
    chance_level_for_options,
    confidence,
    displayed_mastery,
    retained_mastery,
    update,
)
from engine.version import ENGINE_VERSION

_MASTERY_SCENARIOS: list[tuple[str, SkillRating, Attempt]] = [
    (
        "cold-start-correct-l3",
        SkillRating(),
        Attempt(is_correct=True, level=3, response_ms=70_000, expected_seconds=90),
    ),
    (
        "cold-start-wrong-l3",
        SkillRating(),
        Attempt(is_correct=False, level=3, response_ms=120_000, expected_seconds=90),
    ),
    (
        "experienced-correct-l4",
        SkillRating(theta=0.8, scored_attempts=24, levels_seen=(2, 3, 4)),
        Attempt(is_correct=True, level=4, response_ms=95_000, expected_seconds=120),
    ),
    (
        "correct-with-hint",
        SkillRating(theta=0.2, scored_attempts=6, levels_seen=(2, 3)),
        Attempt(
            is_correct=True, level=3, response_ms=80_000, expected_seconds=90, hint_used=True
        ),
    ),
    (
        "suspected-guess",
        SkillRating(theta=-0.5, scored_attempts=4, levels_seen=(1, 2)),
        Attempt(is_correct=True, level=4, response_ms=5_000, expected_seconds=120),
    ),
    (
        "solution-viewed-first",
        SkillRating(theta=0.1, scored_attempts=9, levels_seen=(2, 3)),
        Attempt(
            is_correct=True,
            level=3,
            response_ms=40_000,
            expected_seconds=90,
            solution_viewed_before_answer=True,
        ),
    ),
    (
        "wrong-at-foundation",
        SkillRating(theta=-1.2, scored_attempts=11, levels_seen=(1, 2)),
        Attempt(is_correct=False, level=1, response_ms=45_000, expected_seconds=60),
    ),
]

#: name, mastery, days since success, half-life, options on the item
_RETENTION_SCENARIOS: list[tuple[str, float, float, float, int]] = [
    ("fresh", 0.82, 0.0, 3.0, 4),
    ("one-half-life", 0.82, 3.0, 3.0, 4),
    ("three-half-lives", 0.82, 21.0, 7.0, 4),
    ("long-gap-strong-skill", 0.94, 60.0, 30.0, 4),
    ("five-option-item", 0.82, 3.0, 3.0, 5),
]

_OPTION_COUNTS: list[int] = [2, 3, 4, 5, 6]

_LADDER_SCENARIOS: list[tuple[str, int, list[bool]]] = [
    ("two-correct-moves-up", 2, [True, True]),
    ("two-wrong-moves-down", 4, [True, False, False]),
    ("mixed-holds", 3, [True, False, True]),
    ("ceiling", 5, [True, True]),
    ("floor", 1, [False, False]),
    ("single-answer-holds", 3, [True]),
]

_HELP_SCENARIOS: list[tuple[str, float, int, bool]] = [
    ("strong-slip", 0.86, 1, False),
    ("strong-slip-after-hint", 0.86, 1, True),
    ("developing-first-miss", 0.55, 1, False),
    ("developing-second-miss", 0.55, 2, False),
    ("weak-first-miss", 0.31, 1, False),
    ("third-miss-teaches", 0.70, 3, False),
]


def _mastery_cases() -> Iterator[dict[str, Any]]:
    for name, rating, attempt in _MASTERY_SCENARIOS:
        result = update(rating, attempt)
        yield {
            "id": f"mastery/{name}",
            "kind": "mastery.update",
            "input": {"rating": asdict(rating), "attempt": asdict(attempt)},
            "expected": {
                "rating": asdict(result),
                "displayed_mastery": displayed_mastery(result),
                "band": band(result),
                "confidence": confidence(result),
            },
        }


def _retention_cases() -> Iterator[dict[str, Any]]:
    for name, mastery, days, half_life, option_count in _RETENTION_SCENARIOS:
        chance = chance_level_for_options(option_count)
        yield {
            "id": f"retention/{name}",
            "kind": "mastery.retained",
            "input": {
                "mastery": mastery,
                "days_since_success": days,
                "half_life_days": half_life,
                "chance_level": chance,
            },
            "expected": {
                "retained_mastery": retained_mastery(mastery, days, half_life, chance)
            },
        }


def _chance_level_cases() -> Iterator[dict[str, Any]]:
    for option_count in _OPTION_COUNTS:
        yield {
            "id": f"chance-level/{option_count}-options",
            "kind": "mastery.chance_level",
            "input": {"option_count": option_count},
            "expected": {"chance_level": chance_level_for_options(option_count)},
        }


def _ladder_cases() -> Iterator[dict[str, Any]]:
    for name, level, outcomes in _LADDER_SCENARIOS:
        yield {
            "id": f"ladder/{name}",
            "kind": "ladder.next_level",
            "input": {"current_level": level, "recent_outcomes": outcomes},
            "expected": {
                "next_level": next_level(level, outcomes),
                "needs_prerequisite_probe": needs_prerequisite_probe(level, outcomes),
            },
        }
    for theta in (-2.0, -1.0, 0.0, 0.75, 2.0):
        rating = SkillRating(theta=theta, scored_attempts=10, levels_seen=(2, 3))
        yield {
            "id": f"ladder/start-theta-{theta}",
            "kind": "ladder.starting_level",
            "input": {"rating": asdict(rating)},
            "expected": {"starting_level": starting_level(rating)},
        }


def _help_cases() -> Iterator[dict[str, Any]]:
    for name, mastery, wrong_in_session, hint_shown in _HELP_SCENARIOS:
        yield {
            "id": f"help/{name}",
            "kind": "help.action",
            "input": {
                "mastery": mastery,
                "wrong_in_session": wrong_in_session,
                "hint_shown": hint_shown,
            },
            "expected": {
                "action": help_action(
                    mastery=mastery,
                    wrong_in_session=wrong_in_session,
                    hint_shown=hint_shown,
                )
            },
        }


def build() -> dict[str, Any]:
    """Every parity case, as a plain dictionary."""
    cases = [
        *_mastery_cases(),
        *_retention_cases(),
        *_chance_level_cases(),
        *_ladder_cases(),
        *_help_cases(),
    ]
    return {
        "engine_version": ENGINE_VERSION,
        "generated_by": "packages/engine (make fixtures)",
        "tolerance": 1e-9,
        "cases": cases,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m engine.fixtures OUTPUT_PATH", file=sys.stderr)
        return 2
    destination = Path(argv[1])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(build(), indent=2, sort_keys=False) + "\n")
    print(f"Wrote {destination} ({len(build()['cases'])} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
