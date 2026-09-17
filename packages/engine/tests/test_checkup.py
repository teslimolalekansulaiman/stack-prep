"""Check-up rules (product spec §9.7)."""

from __future__ import annotations

import pytest

from engine.checkup import (
    DEFAULT_START_LEVEL,
    BlueprintSlot,
    TopicAnswers,
    TopicWeight,
    build_blueprint,
    confidence_for,
    next_level,
    summarise,
)
from engine.mastery import Attempt

LEXIS = TopicWeight("lexis", 0.50, "Lexis")
STRUCTURE = TopicWeight("structure", 0.30, "Structure")
IDIOMS = TopicWeight("idioms", 0.15, "Idioms")
ORAL = TopicWeight("oral", 0.05, "Oral English")
TOPICS = [LEXIS, STRUCTURE, IDIOMS, ORAL]


def answer(correct: bool, level: int = 3, response_ms: int = 40_000) -> Attempt:
    return Attempt(is_correct=correct, level=level, response_ms=response_ms, expected_seconds=45)


def counts(slots: list[BlueprintSlot]) -> dict[str, int]:
    tally: dict[str, int] = {}
    for slot in slots:
        tally[slot.topic_id] = tally.get(slot.topic_id, 0) + 1
    return tally


def test_blueprint_is_the_length_asked_for() -> None:
    assert len(build_blueprint(TOPICS, length=15)) == 15


def test_every_topic_gets_at_least_one_question() -> None:
    tally = counts(build_blueprint(TOPICS, length=15))

    assert set(tally) == {topic.topic_id for topic in TOPICS}
    assert min(tally.values()) >= 1


def test_slots_follow_exam_weight() -> None:
    tally = counts(build_blueprint(TOPICS, length=15))

    assert tally["lexis"] > tally["structure"] > tally["idioms"] >= tally["oral"]


def test_positions_are_sequential() -> None:
    slots = build_blueprint(TOPICS, length=15)

    assert [slot.position for slot in slots] == list(range(1, 16))


def test_topics_are_interleaved_so_an_abandoned_sitting_still_covers_breadth() -> None:
    slots = build_blueprint(TOPICS, length=15)

    first_four = {slot.topic_id for slot in slots[:4]}
    assert first_four == {topic.topic_id for topic in TOPICS}


def test_more_topics_than_questions_keeps_the_heaviest() -> None:
    slots = build_blueprint(TOPICS, length=4)
    tally = counts(slots)

    assert len(slots) == 4
    assert set(tally) == {"lexis", "structure", "idioms", "oral"}

    slots = build_blueprint(TOPICS, length=5)
    assert counts(slots)["lexis"] == 2


def test_a_check_up_cannot_be_trivially_short_or_empty() -> None:
    with pytest.raises(ValueError, match="at least 4 questions"):
        build_blueprint(TOPICS, length=3)
    with pytest.raises(ValueError, match="at least one topic"):
        build_blueprint([], length=15)


def test_the_next_question_follows_the_last_answer() -> None:
    assert next_level([]) == DEFAULT_START_LEVEL
    assert next_level([True]) == DEFAULT_START_LEVEL + 1
    assert next_level([False]) == DEFAULT_START_LEVEL - 1
    assert next_level([True, True]) == DEFAULT_START_LEVEL + 2
    assert next_level([True, False]) == DEFAULT_START_LEVEL


def test_levels_stay_in_range() -> None:
    assert next_level([True] * 6) == 5
    assert next_level([False] * 6) == 1


def test_confidence_reflects_how_much_was_asked() -> None:
    assert confidence_for(0) == "none"
    assert confidence_for(2) == "low"
    assert confidence_for(3) == "medium"
    # Fifteen questions across a syllabus never earns "high".
    assert confidence_for(15) == "medium"


def test_a_topic_never_reached_is_reported_as_unassessed_not_weak() -> None:
    summary = summarise(
        "eng",
        TOPICS,
        [TopicAnswers("lexis", (answer(True), answer(True), answer(False)))],
    )

    lexis = next(t for t in summary.topics if t.topic_id == "lexis")
    oral = next(t for t in summary.topics if t.topic_id == "oral")

    assert lexis.mastery is not None
    assert oral.mastery is None
    assert oral.confidence == "none"
    assert "oral" in summary.unassessed_topics
    assert "oral" not in summary.priority_topics


def test_stronger_answers_produce_a_higher_estimate() -> None:
    strong = summarise("eng", [LEXIS], [TopicAnswers("lexis", (answer(True), answer(True)))])
    weak = summarise("eng", [LEXIS], [TopicAnswers("lexis", (answer(False), answer(False)))])

    assert (strong.topics[0].mastery or 0) > (weak.topics[0].mastery or 0)


def test_the_weakest_topic_comes_first_in_the_priorities() -> None:
    summary = summarise(
        "eng",
        [LEXIS, STRUCTURE],
        [
            TopicAnswers("lexis", (answer(True), answer(True))),
            TopicAnswers("structure", (answer(False), answer(False))),
        ],
    )

    assert summary.priority_topics[0] == "structure"


def test_the_ceiling_and_floor_of_a_topic_are_recorded() -> None:
    summary = summarise(
        "eng",
        [LEXIS],
        [
            TopicAnswers(
                "lexis", (answer(True, level=3), answer(True, level=4), answer(False, level=5))
            )
        ],
    )

    lexis = summary.topics[0]
    assert lexis.highest_level_correct == 4
    assert lexis.lowest_level_wrong == 5
    assert lexis.answered == 3
    assert lexis.correct == 2


def test_knowing_it_slowly_is_flagged_separately_from_not_knowing_it() -> None:
    slow = summarise(
        "eng",
        [LEXIS],
        [
            TopicAnswers(
                "lexis", (answer(True, response_ms=120_000), answer(True, response_ms=90_000))
            )
        ],
    )
    quick = summarise("eng", [LEXIS], [TopicAnswers("lexis", (answer(True), answer(True)))])

    assert slow.topics[0].slow
    assert not quick.topics[0].slow
    # Being slow does not make the estimate lower; it is a different problem.
    assert slow.topics[0].mastery == quick.topics[0].mastery


def test_the_summary_counts_every_answer() -> None:
    summary = summarise(
        "eng",
        TOPICS,
        [
            TopicAnswers("lexis", (answer(True), answer(False))),
            TopicAnswers("structure", (answer(True),)),
        ],
    )

    assert summary.answered == 3
