"""Help ladder rules (product spec §9.6)."""

from __future__ import annotations

import pytest

from engine.help import help_action


def test_a_strong_student_slipping_once_is_asked_to_check_again() -> None:
    assert help_action(mastery=0.86, wrong_in_session=1, hint_shown=False) == "check_again"


def test_a_strong_student_who_already_saw_a_hint_gets_the_solution() -> None:
    assert help_action(mastery=0.86, wrong_in_session=1, hint_shown=True) == "worked_solution"


def test_a_developing_student_gets_a_hint_first() -> None:
    assert help_action(mastery=0.55, wrong_in_session=1, hint_shown=False) == "hint"


def test_a_second_miss_shows_the_worked_solution() -> None:
    assert help_action(mastery=0.55, wrong_in_session=2, hint_shown=False) == "worked_solution"


def test_a_weak_skill_goes_straight_to_teaching() -> None:
    assert help_action(mastery=0.31, wrong_in_session=1, hint_shown=False) == "micro_lesson"


def test_three_misses_in_a_session_trigger_teaching() -> None:
    assert help_action(mastery=0.72, wrong_in_session=3, hint_shown=False) == "micro_lesson"


def test_help_is_only_for_wrong_answers() -> None:
    with pytest.raises(ValueError, match="only called after a wrong answer"):
        help_action(mastery=0.5, wrong_in_session=0, hint_shown=False)
