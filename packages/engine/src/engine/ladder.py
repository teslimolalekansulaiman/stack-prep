"""Item difficulty ladder (product spec §9.5).

Chooses the level of the next practice item. Runs offline on the device, so it
is mirrored in packages/engine-ts/src/ladder.ts.
"""

from __future__ import annotations

from collections.abc import Sequence

from engine.mastery import SkillRating, predicted_probability

MIN_LEVEL = 1
MAX_LEVEL = 5

#: Aim just above a coin-flip: hard enough to teach, easy enough to keep going.
TARGET_PROBABILITY = 0.7

#: Consecutive answers at the current level before moving.
STEP_THRESHOLD = 2


def starting_level(rating: SkillRating) -> int:
    """The level whose predicted success sits closest to the target.

    Ties go to the easier level, so a student never opens a session above their
    demonstrated ceiling.
    """
    best_level = MIN_LEVEL
    best_distance = float("inf")
    for level in range(MIN_LEVEL, MAX_LEVEL + 1):
        distance = abs(predicted_probability(rating, level) - TARGET_PROBABILITY)
        if distance < best_distance - 1e-12:
            best_level, best_distance = level, distance
    return best_level


def _tail_all(outcomes: Sequence[bool], value: bool) -> bool:
    tail = outcomes[-STEP_THRESHOLD:]
    return len(tail) == STEP_THRESHOLD and all(outcome is value for outcome in tail)


def next_level(current_level: int, recent_outcomes: Sequence[bool]) -> int:
    """Two correct in a row moves up; two wrong in a row moves down.

    ``recent_outcomes`` is the run of answers at ``current_level``, oldest first.
    """
    if not MIN_LEVEL <= current_level <= MAX_LEVEL:
        raise ValueError(f"current_level must be 1..5, got {current_level}")
    if _tail_all(recent_outcomes, True):
        return min(MAX_LEVEL, current_level + 1)
    if _tail_all(recent_outcomes, False):
        return max(MIN_LEVEL, current_level - 1)
    return current_level


def needs_prerequisite_probe(current_level: int, recent_outcomes: Sequence[bool]) -> bool:
    """Two misses at the foundation level means the gap is probably earlier.

    There is nowhere easier to go inside this skill, so the next questions should
    test its prerequisites instead.
    """
    return current_level == MIN_LEVEL and _tail_all(recent_outcomes, False)
