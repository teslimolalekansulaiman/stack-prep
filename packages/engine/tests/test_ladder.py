"""Item ladder rules (product spec §9.5)."""

from __future__ import annotations

import pytest

from engine.ladder import (
    MAX_LEVEL,
    MIN_LEVEL,
    needs_prerequisite_probe,
    next_level,
    starting_level,
)
from engine.mastery import SkillRating


def test_two_correct_in_a_row_moves_up() -> None:
    assert next_level(2, [True, True]) == 3


def test_two_wrong_in_a_row_moves_down() -> None:
    assert next_level(4, [True, False, False]) == 3


def test_mixed_results_hold_the_level() -> None:
    assert next_level(3, [True, False, True]) == 3
    assert next_level(3, [False, True]) == 3


def test_a_single_answer_is_not_enough_to_move() -> None:
    assert next_level(3, [True]) == 3
    assert next_level(3, [False]) == 3


def test_levels_are_clamped() -> None:
    assert next_level(MAX_LEVEL, [True, True]) == MAX_LEVEL
    assert next_level(MIN_LEVEL, [False, False]) == MIN_LEVEL


def test_invalid_level_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"current_level must be 1\.\.5"):
        next_level(0, [True, True])


def test_probe_only_at_the_foundation_level() -> None:
    assert needs_prerequisite_probe(1, [False, False])
    assert not needs_prerequisite_probe(2, [False, False])
    assert not needs_prerequisite_probe(1, [False, True])


def test_starting_level_rises_with_ability() -> None:
    weak = starting_level(SkillRating(theta=-2.0, scored_attempts=10))
    average = starting_level(SkillRating(theta=0.0, scored_attempts=10))
    strong = starting_level(SkillRating(theta=2.0, scored_attempts=10))

    assert weak <= average <= strong
    assert weak == MIN_LEVEL
    assert strong > average


def test_starting_level_stays_in_range() -> None:
    for theta in (-8.0, -1.0, 0.0, 1.0, 8.0):
        assert MIN_LEVEL <= starting_level(SkillRating(theta=theta)) <= MAX_LEVEL
