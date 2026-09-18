"""Adaptive practice: the loop a student actually sits in.

Ask for a question, answer it, and the engine decides what the answer was worth
and what to show next. Every decision here comes from packages/engine — this
router chooses nothing itself, it only fetches state, calls the rules and records
what they returned (ADR-0005).

Two things are deliberate:

* **The answer key never leaves the server.** Questions are read through
  `candidate_question_payload` and `candidate_question_options`, the views that
  cannot see `is_correct`. Marking happens here, against the stored key.
* **Mastery is changed by recording why.** The rating is derived from
  `mastery_events`; this router inserts an event and the database applies it.

Like the review router, there is no authentication yet: the student is named in
the path rather than proven. It must stay on a trusted network until ADR-0013
lands.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import connection, fetch_all
from engine import (
    ENGINE_VERSION,
    Attempt,
    SkillRating,
    band,
    confidence,
    displayed_mastery,
    help_action,
    next_level,
    starting_level,
    update,
)

router = APIRouter(prefix="/v1/practice", tags=["practice"])

#: Answers at the current level the ladder looks back over (engine.ladder).
RECENT_WINDOW = 2


class Option(BaseModel):
    option_id: UUID
    option_key: str
    body: str
    display_order: int


class NextQuestion(BaseModel):
    attempt_id: UUID
    assessment_question_id: UUID
    question_id: UUID
    stem: str
    instructions: str | None
    passage_title: str | None
    passage_body: str | None
    options: list[Option]
    level: int
    expected_seconds: int | None
    marks: float | None
    #: Why this level, so the choice can be explained rather than trusted.
    chosen_because: str


class Answer(BaseModel):
    assessment_question_id: UUID
    selected_option_id: UUID
    response_ms: int
    hint_used: bool = False
    solution_viewed_before_answer: bool = False


class Marked(BaseModel):
    is_correct: bool
    correct_option_key: str
    awarded_marks: float
    #: What the help ladder says to do next. None when the answer was right.
    help: Literal["check_again", "hint", "worked_solution", "micro_lesson"] | None
    hint: str | None
    solution_steps: list[str]
    band: str
    mastery: float
    confidence: str
    scored: bool
    engine_version: str


async def _one(conn: AsyncConnection, sql: str, **params: Any) -> dict[str, Any] | None:
    rows = await fetch_all(conn, sql, **params)
    return rows[0] if rows else None


async def _rating(conn: AsyncConnection, student_id: UUID, skill_id: UUID) -> SkillRating:
    """The student's current rating for this skill, or a cold start."""
    row = await _one(
        conn,
        """
        SELECT theta, scored_attempts, levels_seen
        FROM student_skill_mastery
        WHERE student_id = :student AND curriculum_item_id = :skill
        """,
        student=student_id,
        skill=skill_id,
    )
    if row is None:
        return SkillRating()
    return SkillRating(
        theta=float(row["theta"]),
        scored_attempts=int(row["scored_attempts"]),
        levels_seen=tuple(row["levels_seen"] or ()),
    )


async def _session(conn: AsyncConnection, student_id: UUID, subject_id: UUID) -> UUID:
    """The student's open adaptive session for this subject, opened if needed.

    Published with no questions on purpose: an adaptive session's first question
    is chosen after the student arrives (migration 009).
    """
    row = await _one(
        conn,
        """
        SELECT id FROM assessments
        WHERE created_for_student_id = :student AND subject_id = :subject
          AND delivery_mode = 'adaptive' AND status = 'published'
        ORDER BY created_at DESC LIMIT 1
        """,
        student=student_id,
        subject=subject_id,
    )
    if row is not None:
        return UUID(str(row["id"]))

    created = await conn.execute(
        text(
            """
            INSERT INTO assessments (examination_id, subject_id, title, assessment_type,
              delivery_mode, created_for_student_id, status, published_at)
            SELECT s.examination_id, s.id, 'Adaptive practice', 'practice', 'adaptive',
                   :student, 'published', now()
            FROM subjects s WHERE s.id = :subject
            RETURNING id
            """
        ),
        {"student": student_id, "subject": subject_id},
    )
    new_id = created.scalar_one()
    return UUID(str(new_id))


async def _attempt(conn: AsyncConnection, assessment_id: UUID, student_id: UUID) -> UUID:
    row = await _one(
        conn,
        """
        SELECT id FROM assessment_attempts
        WHERE assessment_id = :a AND student_id = :s
          AND status IN ('not_started', 'in_progress')
        ORDER BY created_at DESC LIMIT 1
        """,
        a=assessment_id,
        s=student_id,
    )
    if row is not None:
        return UUID(str(row["id"]))

    created = await conn.execute(
        text(
            """
            INSERT INTO assessment_attempts (assessment_id, student_id, attempt_number,
              status, started_at, engine_version)
            VALUES (:a, :s,
              coalesce((SELECT max(attempt_number) + 1 FROM assessment_attempts
                        WHERE assessment_id = :a AND student_id = :s), 1),
              'in_progress', now(), :engine)
            RETURNING id
            """
        ),
        {"a": assessment_id, "s": student_id, "engine": ENGINE_VERSION},
    )
    return UUID(str(created.scalar_one()))


async def _recent_outcomes(
    conn: AsyncConnection, attempt_id: UUID, skill_id: UUID
) -> list[tuple[int, bool]]:
    """Answers on this skill in this sitting, oldest first, as (level, correct)."""
    rows = await fetch_all(
        conn,
        """
        SELECT v.mastery_level_number AS level, r.is_correct
        FROM student_responses r
        JOIN assessment_questions aq ON aq.id = r.assessment_question_id
        JOIN question_versions v ON v.id = aq.question_version_id
        JOIN question_classifications c
          ON c.question_id = aq.question_id AND c.classification_role = 'primary'
        WHERE r.attempt_id = :attempt AND c.curriculum_item_id = :skill
          AND r.is_correct IS NOT NULL
        ORDER BY r.submitted_at, r.created_at
        """,
        attempt=attempt_id,
        skill=skill_id,
    )
    return [(int(r["level"]), bool(r["is_correct"])) for r in rows]


def _choose_level(rating: SkillRating, history: list[tuple[int, bool]]) -> tuple[int, str]:
    """Which level to serve, and the sentence explaining it."""
    if not history:
        level = starting_level(rating)
        return level, (
            f"Opening at level {level}: closest to a 70% chance for this rating."
        )

    current = history[-1][0]
    run = [correct for level, correct in history if level == current][-RECENT_WINDOW:]
    level = next_level(current, run)
    if level > current:
        return level, f"Up from level {current}: {RECENT_WINDOW} correct in a row."
    if level < current:
        return level, f"Down from level {current}: {RECENT_WINDOW} wrong in a row."
    return level, f"Holding at level {current}."


@router.get(
    "/{student_id}/next", response_model=NextQuestion, summary="The next question to ask"
)
async def next_question(
    conn: Annotated[AsyncConnection, Depends(connection)],
    student_id: UUID,
    skill_id: Annotated[UUID, Query(description="The curriculum skill to practise")],
) -> NextQuestion:
    skill = await _one(
        conn,
        """
        SELECT curriculum_item_id, subject_id
        FROM teachable_skills WHERE curriculum_item_id = :skill
        """,
        skill=skill_id,
    )
    if skill is None:
        raise HTTPException(
            status_code=404, detail="no approved, supported skill with that id"
        )
    subject_id = UUID(str(skill["subject_id"]))

    assessment_id = await _session(conn, student_id, subject_id)
    attempt_id = await _attempt(conn, assessment_id, student_id)

    rating = await _rating(conn, student_id, skill_id)
    history = await _recent_outcomes(conn, attempt_id, skill_id)
    level, because = _choose_level(rating, history)

    # Nearest level first, so a skill with a thin bank still serves something
    # rather than refusing. The chosen level is reported either way.
    candidate = await _one(
        conn,
        """
        SELECT question_id, question_version_id, mastery_level_number, expected_seconds, marks
        FROM adaptive_practice_questions
        WHERE primary_skill_id = :skill
          AND question_version_id NOT IN (
            SELECT aq.question_version_id FROM assessment_questions aq
            WHERE aq.assessment_id = :assessment
          )
        ORDER BY abs(mastery_level_number - :level), random()
        LIMIT 1
        """,
        skill=skill_id,
        assessment=assessment_id,
        level=level,
    )
    if candidate is None:
        raise HTTPException(
            status_code=409,
            detail="no approved practice questions left for this skill in this session",
        )

    served = int(candidate["mastery_level_number"])
    if served != level:
        because += f" Nearest available was level {served}."

    placement = await conn.execute(
        text(
            """
            INSERT INTO assessment_questions (assessment_id, question_id,
              question_version_id, position, marks)
            VALUES (:assessment, :question, :version,
              coalesce((SELECT max(position) + 1 FROM assessment_questions
                        WHERE assessment_id = :assessment), 1),
              :marks)
            RETURNING id
            """
        ),
        {
            "assessment": assessment_id,
            "question": candidate["question_id"],
            "version": candidate["question_version_id"],
            "marks": candidate["marks"] or 1,
        },
    )
    placement_id = UUID(str(placement.scalar_one()))

    payload = await _one(
        conn,
        """
        SELECT stem, instructions, passage_title, passage_body, marks, expected_seconds
        FROM candidate_question_payload WHERE question_version_id = :version
        """,
        version=candidate["question_version_id"],
    )
    if payload is None:  # pragma: no cover - the view and the pool agree by construction
        raise HTTPException(status_code=500, detail="that question is not servable")

    options = await fetch_all(
        conn,
        """
        SELECT option_id, option_key, body, display_order
        FROM candidate_question_options WHERE question_version_id = :version
        ORDER BY display_order, option_key
        """,
        version=candidate["question_version_id"],
    )
    await conn.commit()

    return NextQuestion(
        attempt_id=attempt_id,
        assessment_question_id=placement_id,
        question_id=UUID(str(candidate["question_id"])),
        stem=str(payload["stem"]),
        instructions=payload["instructions"],
        passage_title=payload["passage_title"],
        passage_body=payload["passage_body"],
        options=[Option(**row) for row in options],
        level=served,
        expected_seconds=payload["expected_seconds"],
        marks=payload["marks"],
        chosen_because=because,
    )


@router.post("/{student_id}/answer", response_model=Marked, summary="Submit an answer")
async def submit_answer(
    conn: Annotated[AsyncConnection, Depends(connection)],
    student_id: UUID,
    answer: Answer,
) -> Marked:
    placement = await _one(
        conn,
        """
        SELECT aq.id, aq.assessment_id, aq.question_id, aq.question_version_id, aq.marks,
               v.mastery_level_number AS level, v.expected_seconds, v.solution_steps,
               v.hints, c.curriculum_item_id AS skill_id
        FROM assessment_questions aq
        JOIN question_versions v ON v.id = aq.question_version_id
        JOIN question_classifications c
          ON c.question_id = aq.question_id AND c.classification_role = 'primary'
        WHERE aq.id = :placement
        """,
        placement=answer.assessment_question_id,
    )
    if placement is None:
        raise HTTPException(status_code=404, detail="no such question in a session")

    attempt = await _one(
        conn,
        """
        SELECT id FROM assessment_attempts
        WHERE assessment_id = :a AND student_id = :s AND status = 'in_progress'
        ORDER BY created_at DESC LIMIT 1
        """,
        a=placement["assessment_id"],
        s=student_id,
    )
    if attempt is None:
        raise HTTPException(status_code=409, detail="this student has no sitting open")
    attempt_id = UUID(str(attempt["id"]))

    # Marked here, against the stored key. The client was never sent it.
    key = await _one(
        conn,
        """
        SELECT id, option_key FROM question_options
        WHERE question_version_id = :version AND is_correct
        """,
        version=placement["question_version_id"],
    )
    if key is None:  # pragma: no cover - approval requires exactly one correct option
        raise HTTPException(status_code=500, detail="that question has no verified answer")

    is_correct = str(key["id"]) == str(answer.selected_option_id)
    marks = float(placement["marks"] or 1)
    awarded = marks if is_correct else 0.0

    await conn.execute(
        text(
            """
            INSERT INTO student_responses (attempt_id, assessment_id,
              assessment_question_id, selected_option_id, maximum_marks, awarded_marks,
              is_correct, marking_status, response_ms, hint_used,
              solution_viewed_before_answer, submitted_at, marked_at)
            VALUES (:attempt, :assessment, :placement, :option, :maximum, :awarded,
              :correct, 'auto_marked', :ms, :hint, :solution, now(), now())
            """
        ),
        {
            "attempt": attempt_id,
            "assessment": placement["assessment_id"],
            "placement": placement["id"],
            "option": answer.selected_option_id,
            "maximum": marks,
            "awarded": awarded,
            "correct": is_correct,
            "ms": answer.response_ms,
            "hint": answer.hint_used,
            "solution": answer.solution_viewed_before_answer,
        },
    )

    # ------------------------------------------------- what the answer was worth
    skill_id = UUID(str(placement["skill_id"]))
    before = await _rating(conn, student_id, skill_id)
    attempt_evidence = Attempt(
        is_correct=is_correct,
        level=int(placement["level"]),
        response_ms=answer.response_ms,
        expected_seconds=float(placement["expected_seconds"] or 60),
        hint_used=answer.hint_used,
        solution_viewed_before_answer=answer.solution_viewed_before_answer,
    )
    after = update(before, attempt_evidence)
    scored = after != before

    if scored:
        existing = await _one(
            conn,
            """
            SELECT band FROM student_skill_mastery
            WHERE student_id = :s AND curriculum_item_id = :skill
            """,
            s=student_id,
            skill=skill_id,
        )
        await conn.execute(
            text(
                """
                INSERT INTO mastery_events (student_id, curriculum_item_id, previous_band,
                  previous_theta, new_band, new_theta, scored_attempts, levels_seen,
                  mastery_score, confidence, trigger_response_id, decision_reason,
                  engine_version)
                SELECT :student, :skill, :prev_band, :prev_theta, :new_band, :new_theta,
                       :attempts, :levels, :score, :confidence, r.id, :reason, :engine
                FROM student_responses r
                WHERE r.attempt_id = :attempt AND r.assessment_question_id = :placement
                """
            ),
            {
                "student": student_id,
                "skill": skill_id,
                "prev_band": existing["band"] if existing else None,
                "prev_theta": before.theta if existing else None,
                "new_band": band(after),
                "new_theta": after.theta,
                "attempts": after.scored_attempts,
                "levels": list(after.levels_seen),
                "score": round(displayed_mastery(after), 4),
                "confidence": confidence(after),
                "attempt": attempt_id,
                "placement": placement["id"],
                "reason": (
                    f"{'Correct' if is_correct else 'Wrong'} at level "
                    f"{placement['level']}{' with a hint' if answer.hint_used else ''}."
                ),
                "engine": ENGINE_VERSION,
            },
        )

    await conn.commit()

    # ------------------------------------------------------- the smallest help
    action = None
    hint = None
    solution: list[str] = []
    if not is_correct:
        wrong_so_far = await _one(
            conn,
            """
            SELECT count(*) AS wrong
            FROM student_responses r
            JOIN assessment_questions aq ON aq.id = r.assessment_question_id
            JOIN question_classifications c
              ON c.question_id = aq.question_id AND c.classification_role = 'primary'
            WHERE r.attempt_id = :attempt AND c.curriculum_item_id = :skill
              AND r.is_correct IS false
            """,
            attempt=attempt_id,
            skill=skill_id,
        )
        action = help_action(
            mastery=displayed_mastery(after),
            wrong_in_session=int(wrong_so_far["wrong"]) if wrong_so_far else 1,
            hint_shown=answer.hint_used,
        )
        hints = list(placement["hints"] or [])
        if action == "hint" and hints:
            hint = str(hints[0])
        elif action in ("worked_solution", "micro_lesson"):
            solution = [str(step) for step in (placement["solution_steps"] or [])]

    return Marked(
        is_correct=is_correct,
        correct_option_key=str(key["option_key"]),
        awarded_marks=awarded,
        help=action,
        hint=hint,
        solution_steps=solution,
        band=band(after),
        mastery=round(displayed_mastery(after), 4),
        confidence=confidence(after),
        scored=scored,
        engine_version=ENGINE_VERSION,
    )
