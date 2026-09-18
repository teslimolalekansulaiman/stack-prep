"""The score model and the study plan it produces.

These tests are about behaviour a product decision rests on, not about the constants. If a
constant changes the numbers move; if one of these assertions breaks, the plan has started
recommending something a teacher would argue with.
"""

from __future__ import annotations

from engine.projection import (
    CEILING,
    PlannedUnit,
    Projection,
    UnitStanding,
    project,
    score_now,
    session_gain,
)


def unit(
    unit_id: str,
    share: float,
    mastery: float | None,
    *,
    topic: str = "T",
    answered: int = 3,
) -> UnitStanding:
    return UnitStanding(
        unit_id=unit_id,
        name=unit_id,
        topic_id=topic,
        topic_name=topic,
        share=share,
        mastery=mastery,
        answered=answered if mastery is not None else 0,
    )


def test_the_score_is_the_weighted_mastery() -> None:
    """Half the paper known perfectly and half not at all is fifty."""
    units = [unit("a", 0.5, 1.0), unit("b", 0.5, 0.0)]
    assert score_now(units) == 50.0


def test_a_subtopic_nobody_asked_about_is_not_a_zero() -> None:
    """Silence is not evidence of weakness; it inherits its topic's average."""
    units = [unit("a", 0.5, 0.8), unit("b", 0.5, None)]
    # 0.8 measured, 0.8 assumed — not 0.4, which is what scoring the unknown zero would give.
    assert score_now(units) == 80.0


def test_a_session_earns_least_at_both_ends() -> None:
    """Nothing underneath, or nothing left: either way the hour buys little."""
    assert session_gain(0.02) < session_gain(0.45)
    assert session_gain(0.88) < session_gain(0.45)


def test_no_amount_of_study_reaches_certainty() -> None:
    mastery = 0.3
    for _ in range(500):
        mastery += session_gain(mastery)
    assert mastery < CEILING + 1e-9


def test_the_plan_prefers_the_heavier_of_two_equal_gaps() -> None:
    """Same standing, same effort to move — so the marks decide, which is the whole idea."""
    units = [unit("heavy", 0.7, 0.45), unit("light", 0.3, 0.45)]
    plan = {p.unit_id: p for p in project(units, sessions_available=10).plan}
    assert plan["heavy"].sessions > plan["light"].sessions


def test_the_marginal_rule_prefers_the_nearly_there_over_the_hopeless() -> None:
    """The instinct this engine exists to implement, stated as a test.

    Both are worth the same, but one is a push away and the other needs its foundations
    rebuilt. With few enough sessions that nothing is reserved, every one goes to the push.
    """
    units = [unit("nearly", 0.5, 0.5), unit("hopeless", 0.5, 0.05)]
    plan = {p.unit_id: p for p in project(units, sessions_available=3).plan}
    assert plan["nearly"].sessions == 3
    assert plan["hopeless"].sessions == 0


def test_the_weak_subtopic_gets_time_but_no_miracle() -> None:
    """What the two rules together actually produce, and why it is honest.

    The reserved share guarantees the near-empty subtopic real attention — it is not
    abandoned for cheap wins. But sessions there move it slowly, because that is true: a
    student at 0.05 is weeks from the point where study starts paying in marks, and a plan
    that projected them to competence in twenty sessions would be selling a fiction.
    """
    units = [unit("nearly", 0.5, 0.5), unit("hopeless", 0.5, 0.05)]
    plan = {p.unit_id: p for p in project(units, sessions_available=20).plan}
    assert plan["hopeless"].sessions >= 6
    assert plan["hopeless"].mastery_projected > plan["hopeless"].mastery_now
    # The first sessions there buy very little: six of them move it less than one session
    # moves the subtopic that was already half-way.
    assert session_gain(0.05) * 6 < session_gain(0.5) * 2


def test_a_heavy_weakness_is_never_starved() -> None:
    """Pure greed would spend everything on the cheap win and leave the cap in place."""
    units = [
        unit("cheap", 0.2, 0.5),
        unit("heavy_and_weak", 0.8, 0.1),
    ]
    plan = {p.unit_id: p for p in project(units, sessions_available=20).plan}
    assert plan["heavy_and_weak"].sessions >= 6


def test_no_sessions_means_no_movement() -> None:
    units = [unit("a", 1.0, 0.4)]
    result = project(units, sessions_available=0)
    assert result.score_projected == result.score_now


def test_the_projection_says_how_much_of_it_is_guessed() -> None:
    units = [unit("measured", 0.4, 0.6), unit("never_reached", 0.6, None)]
    result = project(units, sessions_available=5)
    assert result.unmeasured_share == 0.6
    assert "was not reached" in result.caveat


def test_the_band_is_wider_when_less_was_asked() -> None:
    thin = project([unit("a", 1.0, 0.5, answered=2)], sessions_available=1)
    thick = project([unit("a", 1.0, 0.5, answered=40)], sessions_available=1)
    assert thin.range_now[1] - thin.range_now[0] > thick.range_now[1] - thick.range_now[0]


def test_the_plan_is_ordered_by_marks_not_by_mastery() -> None:
    units = [unit("a", 0.1, 0.45), unit("b", 0.6, 0.45), unit("c", 0.3, 0.45)]
    result: Projection = project(units, sessions_available=12)
    first: PlannedUnit = result.plan[0]
    assert first.unit_id == "b"
    assert result.plan[0].marks_gained >= result.plan[-1].marks_gained
