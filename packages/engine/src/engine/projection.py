"""What the student would score today, and what study could make of it.

The check-up says how much of each part of the syllabus a student has. This turns that into
the number they actually care about — a mark out of 100 — and then answers the question that
decides everything else: given the time left before the exam, where should that time go?

THE SCORE MODEL. A paper is a sample of the syllabus, and the syllabus is not sampled evenly:
the exam's own structure says how many questions each part carries. So

    score = Σ over units of (share of the paper) * (mastery of that unit)

and that is all. No curve, no adjustment. The unit here is a *subtopic*, not a topic, because
"Lexis and Structure, 62%" tells a student nothing they can act on, while "Synonyms 80%,
Idiomatic usage 35%" tells them where Saturday morning goes.

THE ALLOCATION. Every hour of study is a bet, and the return on it is not the mastery it
buys — it is the *marks* that mastery is worth. A session spent on a subtopic worth one
question of sixty pays a sixtieth of what the same session pays on a subtopic worth ten.
So the plan is built by repeatedly spending the next session where

    marks gained = (share of the paper) * (mastery this session would add)

is largest, which is score optimisation stated plainly.

WHY THE CHEAP WIN IS OFTEN THE RIGHT ONE. The second factor is not constant. A student does
not learn at the same rate everywhere: progress is fastest just past what they can already
do, and slowest where nothing underneath is in place. So the mastery a session adds is

    gain = rate(mastery) * (ceiling - mastery)

where ``rate`` peaks in the middle of the range and falls away at both ends. The bracket
means there is less to win where a student is already strong; the rate means there is less to
win *per session* where they are still at the bottom, because those sessions are spent
building prerequisites rather than scoring marks. Between them they say: push hardest on what
is nearly there and worth a lot — which is the instinct this implements, made checkable.

WHAT THIS DELIBERATELY DOES NOT DO, so the numbers are not read as more than they are:

* It does not let a greedy plan starve a heavy topic. ``RESERVED_FOR_WEAK_AND_HEAVY`` of the
  sessions are spent on the highest-weighted weaknesses whatever the marginal return says,
  because those are what cap a score and the greedy rule reaches them last.
* It does not model prerequisites. Blocking structure lives in ``curriculum_prerequisites``
  and belongs in the gain function; until it is there, a subtopic that is cheap only after
  something else is learned will be mispriced.
* It does not model forgetting. A projection without decay is optimistic, and the spaced
  review state that would correct it is not wired in yet.
* It is not a promise. A projection from fifteen questions carries the uncertainty of fifteen
  questions, which is why every number it returns comes with a range and the range is wide.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

#: No amount of study takes a subtopic to certainty, and a plan that assumes it does will
#: always over-promise. Exam-day mastery of 0.9 is already an excellent student.
CEILING = 0.90

#: How much of the remaining gap one session closes, at the mastery where learning is
#: fastest. Deliberately modest: it is a planning figure, not a marketing one.
PEAK_RATE = 0.22

#: Where learning is fastest. Below this a session is mostly spent on what should have been
#: learned earlier; above it, on refinement that earns little.
PEAK_AT = 0.55

#: How quickly the rate falls away on either side of the peak. Narrow on purpose: a student
#: at 0.05 in a subtopic is not one session from 0.20, they are several weeks from the point
#: where sessions start paying, and a plan that pretends otherwise sells them a fiction.
SPREAD = 0.22

#: Sessions held back from the greedy rule for the heaviest weaknesses. Without this the plan
#: banks cheap wins and reaches the topics that actually cap a score last, or never.
RESERVED_FOR_WEAK_AND_HEAVY = 0.30

#: A subtopic is "weak" below this. Chosen to match the level ladder: below halfway a student
#: is failing more exam-level questions than they pass.
WEAK_BELOW = 0.50

#: An unassessed subtopic is not a zero. Until the check-up reaches it, it is assumed to sit
#: at its topic's average, and the projection says how much of the score rests on that guess.
DEFAULT_WHEN_UNKNOWN = 0.40


@dataclass(frozen=True)
class UnitStanding:
    """One subtopic: what it is worth, and how much of it the student has."""

    unit_id: str
    name: str
    topic_id: str
    topic_name: str
    #: Share of the paper's questions, 0 to 1 across all units of the subject.
    share: float
    #: None when the check-up never reached it.
    mastery: float | None
    answered: int


@dataclass(frozen=True)
class PlannedUnit:
    unit_id: str
    name: str
    topic_name: str
    share: float
    mastery_now: float
    mastery_projected: float
    sessions: int
    #: Marks out of 100 this unit's sessions are expected to add. The whole point.
    marks_gained: float
    #: Why the plan chose it, in the words a student would use.
    reason: str


@dataclass(frozen=True)
class Projection:
    score_now: float
    score_projected: float
    #: Width of the band around ``score_now``, from how little evidence stands behind it.
    range_now: tuple[float, float]
    sessions_available: int
    #: Ordered by the marks each is expected to add, most first.
    plan: tuple[PlannedUnit, ...]
    #: Share of the score resting on subtopics the check-up never reached.
    unmeasured_share: float
    caveat: str


def learning_rate(mastery: float) -> float:
    """How much of the remaining gap one session closes, at this mastery.

    A bell centred on :data:`PEAK_AT`. Near zero a session buys little because it is spent on
    groundwork; near the ceiling it buys little because there is little left.
    """
    distance = (mastery - PEAK_AT) / SPREAD
    return PEAK_RATE * 2.718281828459045 ** (-0.5 * distance * distance)


def session_gain(mastery: float) -> float:
    """Mastery added by one session at this standing."""
    return learning_rate(mastery) * max(0.0, CEILING - mastery)


def _standing(unit: UnitStanding, topic_means: dict[str, float]) -> float:
    if unit.mastery is not None:
        return unit.mastery
    return topic_means.get(unit.topic_id, DEFAULT_WHEN_UNKNOWN)


def score_now(units: Sequence[UnitStanding]) -> float:
    """The mark this student would get today, on this paper, out of 100."""
    topic_means = _topic_means(units)
    total_share = sum(unit.share for unit in units) or 1.0
    return 100.0 * sum(_standing(u, topic_means) * u.share for u in units) / total_share


def _topic_means(units: Sequence[UnitStanding]) -> dict[str, float]:
    """Each topic's measured average, used where a subtopic was never reached.

    A subtopic nobody asked about is not evidence of weakness, and scoring it zero would
    invent a gap. Its topic's average is the least-wrong thing we know about it.
    """
    sums: dict[str, list[float]] = {}
    for unit in units:
        if unit.mastery is not None:
            sums.setdefault(unit.topic_id, []).append(unit.mastery)
    return {key: sum(values) / len(values) for key, values in sums.items()}


def project(
    units: Sequence[UnitStanding],
    sessions_available: int,
) -> Projection:
    """Spend the available sessions where they earn the most marks, and say what that is worth.

    The allocation is greedy but not purely greedy: a reserved share goes to the heaviest
    weaknesses first, because the marginal rule reaches them late and they are what holds a
    score down. Everything after that is spent wherever the next session earns most.
    """
    topic_means = _topic_means(units)
    total_share = sum(unit.share for unit in units) or 1.0
    standing = {unit.unit_id: _standing(unit, topic_means) for unit in units}
    spent: dict[str, int] = {unit.unit_id: 0 for unit in units}
    reasons: dict[str, str] = {}

    reserved = int(sessions_available * RESERVED_FOR_WEAK_AND_HEAVY)
    heavy_weaknesses = sorted(
        (u for u in units if standing[u.unit_id] < WEAK_BELOW),
        key=lambda u: -u.share,
    )
    for index in range(reserved):
        if not heavy_weaknesses:
            break
        unit = heavy_weaknesses[index % len(heavy_weaknesses)]
        standing[unit.unit_id] += session_gain(standing[unit.unit_id])
        spent[unit.unit_id] += 1
        reasons.setdefault(
            unit.unit_id,
            "one of the heaviest parts of the paper, and one of the weakest — this is what "
            "holds the score down",
        )

    for _ in range(max(0, sessions_available - reserved)):
        best = max(units, key=lambda u: u.share * session_gain(standing[u.unit_id]))
        if u_gain := session_gain(standing[best.unit_id]):
            standing[best.unit_id] += u_gain
            spent[best.unit_id] += 1
            reasons.setdefault(
                best.unit_id,
                "close enough to move quickly, and it comes up often enough to be worth the "
                "time",
            )
        else:
            break

    before = {unit.unit_id: _standing(unit, topic_means) for unit in units}
    plan = tuple(
        sorted(
            (
                PlannedUnit(
                    unit_id=unit.unit_id,
                    name=unit.name,
                    topic_name=unit.topic_name,
                    share=unit.share,
                    mastery_now=before[unit.unit_id],
                    mastery_projected=standing[unit.unit_id],
                    sessions=spent[unit.unit_id],
                    marks_gained=100.0
                    * unit.share
                    * (standing[unit.unit_id] - before[unit.unit_id])
                    / total_share,
                    reason=reasons.get(unit.unit_id, "already strong enough to leave alone"),
                )
                for unit in units
            ),
            key=lambda p: -p.marks_gained,
        )
    )

    now = score_now(units)
    projected = 100.0 * sum(standing[u.unit_id] * u.share for u in units) / total_share
    answered = sum(unit.answered for unit in units)
    # Fifteen questions across a syllabus is a starting point. The band is wide on purpose,
    # and narrows only as real practice accumulates.
    width = 18.0 if answered < 10 else 12.0 if answered < 25 else 8.0
    unmeasured = sum(u.share for u in units if u.mastery is None) / total_share

    return Projection(
        score_now=round(now, 1),
        score_projected=round(projected, 1),
        range_now=(round(max(0.0, now - width), 1), round(min(100.0, now + width), 1)),
        sessions_available=sessions_available,
        plan=plan,
        unmeasured_share=round(unmeasured, 3),
        caveat=(
            f"Estimated from {answered} question{'' if answered == 1 else 's'}. "
            f"{round(unmeasured * 100)}% of the paper was not reached and is assumed to sit "
            "at the average for its topic. The projection assumes the study actually happens "
            "and does not allow for forgetting."
        ),
    )
