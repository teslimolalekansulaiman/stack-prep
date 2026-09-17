"""The check-up: the first sitting, which establishes where a student stands.

Not an exam. No score, no deadline, no fixed paper — the questions adapt to the answers,
and the output is a picture of the student, not a mark. It is recorded as a study session
(`session_type = 'checkup'`), and its answers are ordinary attempts, so the same evidence
feeds mastery as everything else.

The sitting holds no server-side state of its own: the blueprint is a deterministic
function of the syllabus, so the nth question is derived from the n-1 answers already
recorded. Nothing to lose if the device drops off halfway.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import connection, fetch_all
from engine.checkup import (
    DEFAULT_LENGTH,
    BlueprintSlot,
    TopicAnswers,
    TopicWeight,
    build_blueprint,
    next_level,
    summarise,
)
from engine.mastery import Attempt
from engine.version import ENGINE_VERSION

router = APIRouter(prefix="/v1/checkup", tags=["checkup"])

#: Questions a check-up may draw on. Practice items are excluded on purpose: a baseline
#: measured on questions the student has drilled measures our bank, not the student.
CHECKUP_POOL = "diagnostic"


class StartCheckup(BaseModel):
    student_id: UUID
    subject_id: UUID


class AnswerIn(BaseModel):
    #: Client-generated, so a retried submission is stored once.
    attempt_id: UUID = Field(default_factory=uuid4)
    question_version_id: UUID
    selected_option_key: str = Field(pattern="^[A-F]$")
    response_ms: int = Field(ge=0, le=3_600_000)


class QuestionOut(BaseModel):
    position: int
    of: int
    topic_name: str
    question_version_id: UUID
    stem: str
    instructions: str | None
    passage_title: str | None
    passage_body: str | None
    options: list[dict[str, str]]


class CheckupState(BaseModel):
    session_id: UUID
    answered: int
    length: int
    finished: bool
    weights_source: str
    question: QuestionOut | None = None


class TopicReport(BaseModel):
    topic_id: UUID
    name: str
    answered: int
    correct: int
    mastery: float | None
    confidence: str
    highest_level_correct: int | None
    lowest_level_wrong: int | None
    slow: bool


class CheckupReport(BaseModel):
    session_id: UUID
    subject_id: UUID
    answered: int
    finished: bool
    topics: list[TopicReport]
    unassessed_topics: list[str]
    priority_topics: list[str]
    #: Said plainly, because a short sitting is a starting point and not a measurement.
    caveat: str


async def _current_syllabus(conn: AsyncConnection, subject_id: UUID) -> UUID:
    row = (
        await conn.execute(
            text(
                """
                SELECT id FROM syllabus_versions
                WHERE subject_id = :s AND status = 'approved' AND is_current
                """
            ),
            {"s": subject_id},
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=409,
            detail="this subject has no approved, current syllabus version yet",
        )
    version_id: UUID = row[0]
    return version_id


async def _topics(conn: AsyncConnection, subject_id: UUID) -> tuple[list[TopicWeight], str]:
    """Topics that actually have check-up questions, weighted by exam share.

    Where no reviewed weights exist yet, topics are treated as equally important and the
    response says so — a guessed weighting presented as fact would quietly distort every
    plan built on it.
    """
    version_id = await _current_syllabus(conn, subject_id)
    rows = await fetch_all(
        conn,
        """
        SELECT topic.id::text AS topic_id, topic.name,
               w.historical_share, w.expert_share, w.alpha,
               count(DISTINCT dq.question_id) AS available
        FROM curriculum_items topic
        JOIN curriculum_items sub ON sub.parent_id = topic.id
        JOIN curriculum_items skill ON skill.parent_id = sub.id AND skill.item_type = 'skill'
        JOIN question_classifications c
          ON c.curriculum_item_id = skill.id
         AND c.classification_role = 'primary' AND c.review_status = 'approved'
        JOIN deliverable_questions dq ON dq.question_id = c.question_id
        JOIN questions q ON q.id = dq.question_id AND q.usage_pool = :pool
        LEFT JOIN topic_weights w
          ON w.topic_id = topic.id AND w.syllabus_version_id = topic.syllabus_version_id
        WHERE topic.syllabus_version_id = :version AND topic.item_type = 'topic'
        GROUP BY topic.id, topic.name, w.historical_share, w.expert_share, w.alpha
        HAVING count(DISTINCT dq.question_id) > 0
        ORDER BY topic.display_order, topic.code
        """,
        version=version_id,
        pool=CHECKUP_POOL,
    )
    if not rows:
        raise HTTPException(
            status_code=409,
            detail=(
                "no approved check-up questions exist for this subject yet. Questions must "
                "be reviewed and placed in the 'diagnostic' pool before a check-up can run."
            ),
        )

    weighted = any(
        row["historical_share"] is not None or row["expert_share"] is not None for row in rows
    )
    topics: list[TopicWeight] = []
    for row in rows:
        if weighted:
            alpha = float(row["alpha"] or 0.5)
            historical = float(row["historical_share"] or 0)
            expert = float(row["expert_share"] or 0)
            share = alpha * historical + (1 - alpha) * expert
        else:
            share = 1.0
        topics.append(TopicWeight(topic_id=row["topic_id"], share=share, name=row["name"]))
    return topics, "topic_weights" if weighted else "equal (no reviewed weights yet)"


async def _answers_so_far(conn: AsyncConnection, session_id: UUID) -> list[dict[str, Any]]:
    return await fetch_all(
        conn,
        """
        SELECT a.id, a.question_version_id, a.is_correct, a.response_ms,
               v.mastery_level_number AS level, v.expected_seconds,
               topic.id::text AS topic_id
        FROM attempts a
        JOIN question_versions v ON v.id = a.question_version_id
        JOIN question_classifications c
          ON c.question_id = v.question_id AND c.classification_role = 'primary'
         AND c.review_status = 'approved'
        JOIN curriculum_items skill ON skill.id = c.curriculum_item_id
        JOIN curriculum_items sub ON sub.id = skill.parent_id
        JOIN curriculum_items topic ON topic.id = sub.parent_id
        WHERE a.session_id = :session
        ORDER BY a.answered_at_client
        """,
        session=session_id,
    )


async def _pick_question(
    conn: AsyncConnection,
    subject_id: UUID,
    slot: BlueprintSlot,
    target_level: int,
    session_id: UUID,
    seen: list[UUID],
) -> dict[str, Any] | None:
    """The closest question to the level we want, inside this topic, not already served."""
    rows = await fetch_all(
        conn,
        """
        SELECT dq.question_version_id, dq.mastery_level_number, p.stem, p.instructions,
               p.passage_title, p.passage_body, topic.name AS topic_name
        FROM deliverable_questions dq
        JOIN questions q ON q.id = dq.question_id AND q.usage_pool = :pool
        JOIN candidate_question_payload p ON p.question_version_id = dq.question_version_id
        JOIN curriculum_items skill ON skill.id = dq.primary_skill_id
        JOIN curriculum_items sub ON sub.id = skill.parent_id
        JOIN curriculum_items topic ON topic.id = sub.parent_id
        WHERE dq.subject_id = :subject
          AND topic.id = CAST(:topic AS uuid)
          AND (CARDINALITY(CAST(:seen AS uuid[])) = 0
               OR NOT (dq.question_version_id = ANY (CAST(:seen AS uuid[]))))
        ORDER BY abs(coalesce(dq.mastery_level_number, 3) - :level),
                 md5(:session || dq.question_version_id::text)
        LIMIT 1
        """,
        pool=CHECKUP_POOL,
        subject=subject_id,
        topic=slot.topic_id,
        level=target_level,
        seen=seen,
        session=str(session_id),
    )
    return rows[0] if rows else None


async def _options(conn: AsyncConnection, question_version_id: UUID) -> list[dict[str, str]]:
    rows = await fetch_all(
        conn,
        """
        SELECT option_key, body FROM candidate_question_options
        WHERE question_version_id = :v ORDER BY display_order, option_key
        """,
        v=question_version_id,
    )
    return [{"option_key": row["option_key"], "body": row["body"]} for row in rows]


async def _next_state(conn: AsyncConnection, session_id: UUID, subject_id: UUID) -> CheckupState:
    topics, weights_source = await _topics(conn, subject_id)
    blueprint = build_blueprint(topics, length=min(DEFAULT_LENGTH, _capacity(topics)))
    answers = await _answers_so_far(conn, session_id)
    position = len(answers)

    if position >= len(blueprint):
        return CheckupState(
            session_id=session_id,
            answered=position,
            length=len(blueprint),
            finished=True,
            weights_source=weights_source,
        )

    slot = blueprint[position]
    outcomes = [bool(row["is_correct"]) for row in answers if row["topic_id"] == slot.topic_id]
    target = next_level(outcomes, slot.start_level)
    seen = [row["question_version_id"] for row in answers]

    question = await _pick_question(conn, subject_id, slot, target, session_id, seen)
    if question is None:
        # The topic ran out of questions. Rather than repeat one, the sitting ends and the
        # report says which topics went unassessed.
        return CheckupState(
            session_id=session_id,
            answered=position,
            length=position,
            finished=True,
            weights_source=weights_source,
        )

    return CheckupState(
        session_id=session_id,
        answered=position,
        length=len(blueprint),
        finished=False,
        weights_source=weights_source,
        question=QuestionOut(
            position=position + 1,
            of=len(blueprint),
            topic_name=str(question["topic_name"]),
            question_version_id=question["question_version_id"],
            stem=str(question["stem"]),
            instructions=question["instructions"],
            passage_title=question["passage_title"],
            passage_body=question["passage_body"],
            options=await _options(conn, question["question_version_id"]),
        ),
    )


def _capacity(topics: list[TopicWeight]) -> int:
    """Never plan more questions than the shortest sensible sitting can hold."""
    return int(max(len(topics), DEFAULT_LENGTH))


@router.post("/start", response_model=CheckupState, summary="Begin a check-up")
async def start(
    conn: Annotated[AsyncConnection, Depends(connection)], request: StartCheckup
) -> CheckupState:
    student = (
        await conn.execute(
            text("SELECT status FROM students WHERE id = :id"), {"id": request.student_id}
        )
    ).first()
    if student is None:
        raise HTTPException(status_code=404, detail="unknown student")

    session_id = (
        await conn.execute(
            text(
                """
                INSERT INTO study_sessions (student_id, subject_id, session_type, engine_version)
                VALUES (:student, :subject, 'checkup', :engine)
                RETURNING id
                """
            ),
            {
                "student": request.student_id,
                "subject": request.subject_id,
                "engine": ENGINE_VERSION,
            },
        )
    ).scalar_one()
    await conn.commit()
    return await _next_state(conn, session_id, request.subject_id)


@router.post(
    "/{session_id}/answer",
    response_model=CheckupState,
    summary="Answer and get the next question",
)
async def answer(
    conn: Annotated[AsyncConnection, Depends(connection)],
    session_id: UUID,
    submission: AnswerIn,
) -> CheckupState:
    session = (
        (
            await conn.execute(
                text(
                    """
                SELECT student_id, subject_id, ended_at FROM study_sessions
                WHERE id = :id AND session_type = 'checkup'
                """
                ),
                {"id": session_id},
            )
        )
        .mappings()
        .first()
    )
    if session is None:
        raise HTTPException(status_code=404, detail="unknown check-up")
    if session["ended_at"] is not None:
        raise HTTPException(status_code=409, detail="this check-up is already finished")

    # Marking happens here, never on the device: the key never leaves the server.
    key = (
        await conn.execute(
            text(
                """
                SELECT option_key FROM question_options
                WHERE question_version_id = :v AND is_correct
                """
            ),
            {"v": submission.question_version_id},
        )
    ).first()
    if key is None:
        raise HTTPException(status_code=409, detail="this question has no verified answer")

    try:
        await conn.execute(
            text(
                """
                INSERT INTO attempts (id, student_id, question_version_id, session_id, context,
                  selected_option_key, is_correct, response_ms, answered_at_client, engine_version)
                VALUES (:id, :student, :version, :session, 'checkup', :choice, :correct,
                  :ms, now(), :engine)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": submission.attempt_id,
                "student": session["student_id"],
                "version": submission.question_version_id,
                "session": session_id,
                "choice": submission.selected_option_key,
                "correct": submission.selected_option_key == key[0],
                "ms": submission.response_ms,
                "engine": ENGINE_VERSION,
            },
        )
        await conn.commit()
    except DBAPIError as error:
        await conn.rollback()
        original = getattr(error, "orig", None)
        message = str(original.args[0]) if original and original.args else str(error)
        raise HTTPException(status_code=409, detail=message.split("\n")[0]) from error

    state = await _next_state(conn, session_id, session["subject_id"])
    if state.finished:
        await conn.execute(
            text("UPDATE study_sessions SET ended_at = now() WHERE id = :id AND ended_at IS NULL"),
            {"id": session_id},
        )
        await conn.commit()
    return state


@router.get("/{session_id}/report", response_model=CheckupReport, summary="What the check-up found")
async def report(
    conn: Annotated[AsyncConnection, Depends(connection)], session_id: UUID
) -> CheckupReport:
    session = (
        (
            await conn.execute(
                text(
                    """
                SELECT student_id, subject_id, ended_at FROM study_sessions
                WHERE id = :id AND session_type = 'checkup'
                """
                ),
                {"id": session_id},
            )
        )
        .mappings()
        .first()
    )
    if session is None:
        raise HTTPException(status_code=404, detail="unknown check-up")

    topics, _ = await _topics(conn, session["subject_id"])
    answers = await _answers_so_far(conn, session_id)

    grouped: dict[str, list[Attempt]] = {}
    for row in answers:
        grouped.setdefault(str(row["topic_id"]), []).append(
            Attempt(
                is_correct=bool(row["is_correct"]),
                level=int(row["level"] or 3),
                response_ms=int(row["response_ms"] or 0),
                expected_seconds=float(row["expected_seconds"] or 45),
            )
        )

    summary = summarise(
        subject_id=str(session["subject_id"]),
        topics=topics,
        answers=[
            TopicAnswers(topic_id=key, attempts=tuple(value)) for key, value in grouped.items()
        ],
    )
    names = {topic.topic_id: topic.name for topic in topics}

    return CheckupReport(
        session_id=session_id,
        subject_id=session["subject_id"],
        answered=summary.answered,
        finished=session["ended_at"] is not None,
        topics=[
            TopicReport(
                topic_id=UUID(estimate.topic_id),
                name=estimate.name,
                answered=estimate.answered,
                correct=estimate.correct,
                mastery=estimate.mastery,
                confidence=estimate.confidence,
                highest_level_correct=estimate.highest_level_correct,
                lowest_level_wrong=estimate.lowest_level_wrong,
                slow=estimate.slow,
            )
            for estimate in summary.topics
        ],
        unassessed_topics=[names.get(topic_id, topic_id) for topic_id in summary.unassessed_topics],
        priority_topics=[names.get(topic_id, topic_id) for topic_id in summary.priority_topics],
        caveat=(
            f"Based on {summary.answered} question(s). This is a starting point for planning, "
            "not a measure of ability, and it says nothing about topics it did not reach."
        ),
    )
