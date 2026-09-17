"""Help ladder (product spec §9.6).

Decides the smallest useful response to a wrong answer. Runs offline on the
device, so it is mirrored in packages/engine-ts/src/help.ts.
"""

from __future__ import annotations

from typing import Literal

HelpAction = Literal["check_again", "hint", "worked_solution", "micro_lesson"]

#: Above this mastery, one wrong answer reads as a slip rather than a gap.
SLIP_MASTERY = 0.80

#: Below this mastery, practice alone will not fix the gap.
TEACHING_MASTERY = 0.40

#: Wrong answers on one skill in a session before teaching is warranted.
TEACHING_WRONG_COUNT = 3


def help_action(*, mastery: float, wrong_in_session: int, hint_shown: bool) -> HelpAction:
    """Pick the response to a wrong answer.

    ``mastery`` is the decayed fraction for the item's skill, ``wrong_in_session``
    counts wrong answers on that skill this session including this one, and
    ``hint_shown`` says whether the student already saw a hint for this item.
    """
    if wrong_in_session < 1:
        raise ValueError("help_action is only called after a wrong answer")

    if mastery < TEACHING_MASTERY or wrong_in_session >= TEACHING_WRONG_COUNT:
        return "micro_lesson"
    if mastery >= SLIP_MASTERY and wrong_in_session == 1 and not hint_shown:
        return "check_again"
    if hint_shown or wrong_in_session >= 2:
        return "worked_solution"
    return "hint"
