"""Score Pilot learning engine.

Pure decision rules with no I/O and no wall-clock reads, so every result is
reproducible from its inputs and the engine version. See docs/product-spec.md §9
and ADR-0005.

The offline subset of these rules is mirrored in packages/engine-ts. Any change
to mastery, ladder or help must regenerate packages/fixtures/vectors.json in the
same pull request (`make fixtures`).
"""

from engine.help import HelpAction, help_action
from engine.ladder import needs_prerequisite_probe, next_level, starting_level
from engine.mastery import (
    Attempt,
    Band,
    Confidence,
    SkillRating,
    band,
    chance_level_for_options,
    confidence,
    displayed_mastery,
    is_suspected_guess,
    learning_rate,
    predicted_probability,
    probability_correct,
    retained_mastery,
    update,
)
from engine.version import ENGINE_VERSION

__all__ = [
    "ENGINE_VERSION",
    "Attempt",
    "Band",
    "Confidence",
    "HelpAction",
    "SkillRating",
    "band",
    "chance_level_for_options",
    "confidence",
    "displayed_mastery",
    "help_action",
    "is_suspected_guess",
    "learning_rate",
    "needs_prerequisite_probe",
    "next_level",
    "predicted_probability",
    "probability_correct",
    "retained_mastery",
    "starting_level",
    "update",
]
