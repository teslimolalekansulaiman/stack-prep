"""The check-up: the short adaptive sitting that establishes where a student stands.

It is not an exam. There is no score, no deadline and no fixed paper: the questions adapt
to the answers, and the point is to learn enough about the student to plan their study.
A mock measures; a check-up diagnoses (product spec §9.7).

Three jobs live here, all pure functions:

1. :func:`build_blueprint` decides how the few slots are spread across the syllabus —
   weighted by how much of the exam each topic is worth, with a floor so nothing important
   is left unlooked-at.
2. :func:`next_level` picks how hard the next question in a topic should be, given how the
   previous ones went.
3. :func:`summarise` turns the answers into a per-topic estimate, each carrying how much
   evidence stands behind it — including "we did not find out", which is a real answer.

This runs server-side only, so unlike the practice ladder it is not mirrored in TypeScript
(ADR-0005).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from engine.ladder import MAX_LEVEL, MIN_LEVEL
from engine.mastery import Attempt, SkillRating, displayed_mastery, update

#: A check-up should fit in one sitting; students abandon long ones before they finish.
DEFAULT_LENGTH = 15
MIN_LENGTH = 4

#: Where a topic starts when we know nothing: a standard exam-level item, so one answer
#: already separates comfortable from struggling.
DEFAULT_START_LEVEL = 3

#: Evidence needed before a topic estimate is worth acting on.
CONFIDENT_ANSWERS = 3


@dataclass(frozen=True)
class TopicWeight:
    """One topic, and how much of the exam it is worth."""

    topic_id: str
    #: Share of the subject's expected questions, 0 to 1 across all topics.
    share: float
    name: str = ""


@dataclass(frozen=True)
class BlueprintSlot:
    """One question the check-up intends to ask."""

    position: int
    topic_id: str
    #: Where to start if this is the first question in its topic.
    start_level: int = DEFAULT_START_LEVEL


@dataclass(frozen=True)
class TopicAnswers:
    """What happened in one topic during the sitting."""

    topic_id: str
    attempts: tuple[Attempt, ...] = ()


@dataclass(frozen=True)
class TopicEstimate:
    topic_id: str
    name: str
    answered: int
    correct: int
    #: None when the topic was never reached: silence is not evidence of weakness.
    mastery: float | None
    confidence: str
    highest_level_correct: int | None
    lowest_level_wrong: int | None
    slow: bool


@dataclass(frozen=True)
class CheckupSummary:
    subject_id: str
    answered: int
    topics: tuple[TopicEstimate, ...] = ()
    #: Topics the blueprint wanted but the sitting never reached.
    unassessed_topics: tuple[str, ...] = ()
    #: Weakest first, and only where there is enough evidence to say so.
    priority_topics: tuple[str, ...] = field(default=())


def build_blueprint(
    topics: Sequence[TopicWeight],
    length: int = DEFAULT_LENGTH,
    start_level: int = DEFAULT_START_LEVEL,
) -> list[BlueprintSlot]:
    """Spread ``length`` questions across topics by exam weight.

    Every topic gets at least one question while there is room, because a topic nobody
    asked about is a hole in the plan, not a strength. Remaining slots go to the topics
    worth the most marks, largest remainder first.
    """
    if length < MIN_LENGTH:
        raise ValueError(f"a check-up needs at least {MIN_LENGTH} questions, got {length}")
    if not topics:
        raise ValueError("a check-up needs at least one topic")
    if any(topic.share < 0 for topic in topics):
        raise ValueError("topic shares cannot be negative")

    ranked = sorted(topics, key=lambda topic: (-topic.share, topic.topic_id))

    # More topics than questions: ask about the ones that carry the most marks, and report
    # the rest as unassessed rather than pretending one item covered them.
    if length <= len(ranked):
        chosen = ranked[:length]
        return [
            BlueprintSlot(position=index + 1, topic_id=topic.topic_id, start_level=start_level)
            for index, topic in enumerate(chosen)
        ]

    total_share = sum(topic.share for topic in ranked)
    if total_share <= 0:
        raise ValueError("topic shares must add up to something positive")

    remaining = length - len(ranked)
    exact = {topic.topic_id: (topic.share / total_share) * remaining for topic in ranked}
    counts = {topic.topic_id: 1 + int(exact[topic.topic_id]) for topic in ranked}

    allocated = sum(counts.values())
    leftovers = sorted(
        ranked,
        key=lambda topic: (-(exact[topic.topic_id] % 1), -topic.share, topic.topic_id),
    )
    for topic in leftovers:
        if allocated >= length:
            break
        counts[topic.topic_id] += 1
        allocated += 1

    # Interleave topics so an abandoned sitting still covers breadth: a student who stops
    # after six questions has six different topics looked at, not two.
    slots: list[BlueprintSlot] = []
    position = 1
    for round_index in range(max(counts.values())):
        for topic in ranked:
            if counts[topic.topic_id] > round_index:
                slots.append(
                    BlueprintSlot(
                        position=position, topic_id=topic.topic_id, start_level=start_level
                    )
                )
                position += 1
    return slots


def next_level(outcomes: Sequence[bool], start_level: int = DEFAULT_START_LEVEL) -> int:
    """How hard the next question in this topic should be.

    A check-up has two or three questions per topic, so it moves one step per answer: right
    means go harder, wrong means go easier. There is no "hold" — with this few questions,
    standing still learns nothing.
    """
    if not MIN_LEVEL <= start_level <= MAX_LEVEL:
        raise ValueError(f"start_level must be {MIN_LEVEL}..{MAX_LEVEL}, got {start_level}")
    level = start_level
    for correct in outcomes:
        level = min(MAX_LEVEL, level + 1) if correct else max(MIN_LEVEL, level - 1)
    return level


def confidence_for(answered: int) -> str:
    """How much weight the estimate can carry."""
    if answered == 0:
        return "none"
    if answered < CONFIDENT_ANSWERS:
        return "low"
    return "medium"


def summarise(
    subject_id: str,
    topics: Sequence[TopicWeight],
    answers: Sequence[TopicAnswers],
    planned_topic_ids: Sequence[str] = (),
) -> CheckupSummary:
    """Turn the sitting into per-topic estimates.

    Confidence never exceeds ``medium``: fifteen questions across a syllabus is a starting
    point, not a measurement. The estimate for each topic comes from the same mastery
    update the rest of the engine uses, so a check-up answer and a practice answer move a
    student the same way.
    """
    names = {topic.topic_id: topic.name or topic.topic_id for topic in topics}
    by_topic = {entry.topic_id: entry for entry in answers}

    estimates: list[TopicEstimate] = []
    answered_total = 0
    for topic in topics:
        entry = by_topic.get(topic.topic_id)
        attempts = entry.attempts if entry else ()
        answered_total += len(attempts)

        rating = SkillRating()
        correct = 0
        highest_correct: int | None = None
        lowest_wrong: int | None = None
        slow_answers = 0
        for attempt in attempts:
            rating = update(rating, attempt)
            if attempt.is_correct:
                correct += 1
                highest_correct = max(highest_correct or attempt.level, attempt.level)
            else:
                lowest_wrong = min(lowest_wrong or attempt.level, attempt.level)
            if attempt.response_ms > attempt.expected_seconds * 1000 * 1.5:
                slow_answers += 1

        estimates.append(
            TopicEstimate(
                topic_id=topic.topic_id,
                name=names[topic.topic_id],
                answered=len(attempts),
                correct=correct,
                mastery=displayed_mastery(rating) if attempts else None,
                confidence=confidence_for(len(attempts)),
                highest_level_correct=highest_correct,
                lowest_level_wrong=lowest_wrong,
                # Knowing the answer but taking far too long is a different problem from
                # not knowing it, and the plan should treat it differently.
                slow=bool(attempts) and slow_answers * 2 >= len(attempts),
            )
        )

    unassessed = tuple(
        estimate.topic_id for estimate in estimates if estimate.answered == 0
    )
    priority = tuple(
        estimate.topic_id
        for estimate in sorted(
            (e for e in estimates if e.mastery is not None),
            key=lambda e: (e.mastery or 0.0, e.topic_id),
        )
    )

    planned = set(planned_topic_ids)
    if planned:
        unassessed = tuple(topic_id for topic_id in unassessed if topic_id in planned)

    return CheckupSummary(
        subject_id=subject_id,
        answered=answered_total,
        topics=tuple(estimates),
        unassessed_topics=unassessed,
        priority_topics=priority,
    )
