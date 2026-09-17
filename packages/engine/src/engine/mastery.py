"""Elo-style mastery estimation (product spec §9.1).

One rating per student per skill. Each item has one primary skill and a
difficulty taken from its level. Mirrored in packages/engine-ts/src/mastery.ts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import exp
from typing import Literal

Band = Literal["not_assessed", "weak", "developing", "exam_ready", "strong", "maintained"]
Confidence = Literal["low", "medium", "high"]

#: Objective items carry between two and six options; the chance of guessing one
#: correctly is 1/option_count. Never assume four (ADR-0014).
MIN_OPTIONS = 2
MAX_OPTIONS = 6

#: Starting difficulty per level. Recalibrated from responses once an item has
#: enough attempts; these are the priors authors work with.
LEVEL_DIFFICULTY: dict[int, float] = {1: -1.5, 2: -0.75, 3: 0.0, 4: 0.75, 5: 1.5}

#: Displayed mastery is the chance of answering a standard exam-level item.
REFERENCE_LEVEL = 3

K_INITIAL = 0.4
K_DECAY = 0.1
K_FLOOR = 0.08

#: A hint caps the credit an answer can earn.
HINT_OUTCOME_CAP = 0.5

#: Correct in less than this fraction of the expected time reads as a guess.
GUESS_TIME_FRACTION = 0.25
GUESS_K_FACTOR = 0.5

MIN_SCORED_ATTEMPTS_FOR_BAND = 3
HIGH_CONFIDENCE_ATTEMPTS = 8


@dataclass(frozen=True)
class SkillRating:
    """What we believe about one student on one skill."""

    theta: float = 0.0
    scored_attempts: int = 0
    levels_seen: tuple[int, ...] = field(default=())


@dataclass(frozen=True)
class Attempt:
    """One answered item, as evidence for the rating."""

    is_correct: bool
    level: int
    response_ms: int
    expected_seconds: float
    hint_used: bool = False
    solution_viewed_before_answer: bool = False


def chance_level_for_options(option_count: int) -> float:
    """Probability of guessing an item with this many options correctly."""
    if not MIN_OPTIONS <= option_count <= MAX_OPTIONS:
        raise ValueError(f"option_count must be {MIN_OPTIONS}..{MAX_OPTIONS}, got {option_count}")
    return 1.0 / option_count


def difficulty_for_level(level: int) -> float:
    """Difficulty prior for an item level, 1 (foundation) to 5 (transfer)."""
    try:
        return LEVEL_DIFFICULTY[level]
    except KeyError:
        raise ValueError(f"level must be 1..5, got {level}") from None


def probability_correct(theta: float, difficulty: float) -> float:
    """Logistic chance of a correct answer."""
    return 1.0 / (1.0 + exp(-(theta - difficulty)))


def predicted_probability(rating: SkillRating, level: int) -> float:
    """Chance this student answers an item of this level correctly."""
    return probability_correct(rating.theta, difficulty_for_level(level))


def learning_rate(scored_attempts: int) -> float:
    """Step size, shrinking as evidence accumulates."""
    return max(K_FLOOR, K_INITIAL / (1.0 + K_DECAY * scored_attempts))


def is_suspected_guess(attempt: Attempt) -> bool:
    """A correct answer too fast to have been worked out."""
    if not attempt.is_correct:
        return False
    threshold_ms = GUESS_TIME_FRACTION * attempt.expected_seconds * 1000.0
    return attempt.response_ms < threshold_ms


def update(rating: SkillRating, attempt: Attempt) -> SkillRating:
    """Fold one attempt into a rating.

    Viewing the solution before answering teaches the student but tells us
    nothing about what they knew, so that attempt is not scored.
    """
    if attempt.solution_viewed_before_answer:
        return rating

    expected = probability_correct(rating.theta, difficulty_for_level(attempt.level))
    outcome = 1.0 if attempt.is_correct else 0.0
    if attempt.hint_used:
        outcome = min(outcome, HINT_OUTCOME_CAP)

    step = learning_rate(rating.scored_attempts)
    if is_suspected_guess(attempt):
        step *= GUESS_K_FACTOR

    return SkillRating(
        theta=rating.theta + step * (outcome - expected),
        scored_attempts=rating.scored_attempts + 1,
        levels_seen=tuple(sorted(set(rating.levels_seen) | {attempt.level})),
    )


def displayed_mastery(rating: SkillRating) -> float:
    """Mastery as a fraction: the chance of answering an exam-level item."""
    return predicted_probability(rating, REFERENCE_LEVEL)


def band(rating: SkillRating) -> Band:
    """The band shown to students and used by the planner."""
    if rating.scored_attempts < MIN_SCORED_ATTEMPTS_FOR_BAND:
        return "not_assessed"
    mastery = displayed_mastery(rating)
    if mastery < 0.40:
        return "weak"
    if mastery < 0.65:
        return "developing"
    if mastery < 0.80:
        return "exam_ready"
    if mastery < 0.90:
        return "strong"
    return "maintained"


def confidence(rating: SkillRating) -> Confidence:
    """How much the evidence behind a rating can be trusted."""
    if rating.scored_attempts < MIN_SCORED_ATTEMPTS_FOR_BAND:
        return "low"
    if rating.scored_attempts >= HIGH_CONFIDENCE_ATTEMPTS and len(rating.levels_seen) >= 2:
        return "high"
    return "medium"


def retained_mastery(
    mastery: float,
    days_since_success: float,
    half_life_days: float,
    chance_level: float,
) -> float:
    """Mastery decayed towards chance level, for planning (product spec §9.1).

    Memory is modelled as a retention probability that halves every
    ``half_life_days``. What is forgotten falls back to guessing, not to zero, so
    the caller passes the item's own chance level — see
    :func:`chance_level_for_options`.
    """
    if half_life_days <= 0:
        raise ValueError("half_life_days must be positive")
    if days_since_success < 0:
        raise ValueError("days_since_success cannot be negative")
    if not 0.0 <= chance_level < 1.0:
        raise ValueError("chance_level must be in [0, 1)")
    retention: float = 2.0 ** (-days_since_success / half_life_days)
    return mastery * retention + chance_level * (1.0 - retention)
