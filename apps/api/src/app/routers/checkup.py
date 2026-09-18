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

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import connection, fetch_all
from app.routers.student import sessions_before
from engine.checkup import (
    DEFAULT_LENGTH,
    BlueprintSlot,
    TopicAnswers,
    TopicWeight,
    build_blueprint,
    confidence_for,
    next_level,
    summarise,
)
from engine.mastery import Attempt
from engine.projection import (
    Projection,
    UnitStanding,
    project,
)
from engine.version import ENGINE_VERSION

router = APIRouter(prefix="/v1/checkup", tags=["checkup"])

#: What a check-up must never draw on. Held-out items exist to measure the bank itself, and
#: spending them on a diagnosis would burn the only unpractised set we keep.
#:
#: Note what is NOT excluded: ordinary practice questions. A check-up used to require items
#: reserved in the diagnostic pool, which sounds careful and mostly is not. What makes a
#: baseline honest is that THIS student has not seen the question, and that is a fact about
#: the student's history, not a label on the question. A student sitting a first check-up has
#: no history at all, so every question is equally unseen to them, and a reserved pool buys
#: nothing while taking items out of practice for everybody else.
#:
#: The exclusion is therefore per-student, read from student_question_history — which the
#: schema describes as exactly that: "the selector reads this to avoid repeating an item". A
#: curated pool still counts, since reserved questions are preferred where they exist, but it
#: is a preference now rather than a gate, and a subject with no pool works fine.
EXCLUDED_POOL = "held_out"


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


@dataclass(frozen=True)
class UnitWeight:
    """One subtopic and its share of the paper."""

    unit_id: str
    name: str
    topic_id: str
    topic_name: str
    share: float


class SubtopicReport(BaseModel):
    subtopic_id: UUID
    name: str
    topic_name: str
    #: Share of the paper, 0 to 1.
    share: float
    answered: int
    correct: int
    #: None when the sitting never reached it. Not the same as zero.
    mastery: float | None
    confidence: str


class PlanLine(BaseModel):
    subtopic_id: UUID
    name: str
    topic_name: str
    share: float
    mastery_now: float
    mastery_projected: float
    sessions: int
    #: Marks out of 100 these sessions are expected to add.
    marks_gained: float
    reason: str


class ScoreProjection(BaseModel):
    score_now: float
    score_low: float
    score_high: float
    score_projected: float
    target_score: float | None
    sessions_available: int
    #: Set when the projection still falls short of the target, said plainly.
    shortfall_note: str | None
    unmeasured_share: float
    plan: list[PlanLine]
    caveat: str


class CheckupReport(BaseModel):
    session_id: UUID
    subject_id: UUID
    answered: int
    finished: bool
    topics: list[TopicReport]
    #: The finer reading a student can act on: "Idiomatic usage 35%", not "Lexis 62%".
    subtopics: list[SubtopicReport]
    weights_source: str
    #: Present once the student has a goal; the whole point of the sitting.
    projection: ScoreProjection | None
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
    """Topics that have questions a check-up could use, weighted by exam share.

    Where no reviewed weights exist yet, topics are treated as equally important and the
    response says so — a guessed weighting presented as fact would quietly distort every
    plan built on it.
    """
    version_id = await _current_syllabus(conn, subject_id)
    rows = await fetch_all(
        conn,
        """
        -- MATERIALIZED, and it is not decoration. deliverable_questions is six joins deep;
        -- left inline, the planner re-ran the whole thing once per candidate row and this
        -- query took 5.3 seconds against 754 questions. Pinned to one evaluation it takes 22
        -- milliseconds. The view also already carries primary_skill_id, so the classification
        -- join it used to do here was work done twice.
        WITH deliverable AS MATERIALIZED (
          SELECT dq.question_id, dq.primary_skill_id
          FROM deliverable_questions dq
          JOIN questions q ON q.id = dq.question_id AND q.usage_pool <> :pool
          WHERE dq.subject_id = :subject
        )
        SELECT topic.id::text AS topic_id, topic.name, w.share,
               count(DISTINCT d.question_id) AS available
        FROM curriculum_items topic
        JOIN curriculum_items sub ON sub.parent_id = topic.id
        JOIN curriculum_items skill ON skill.parent_id = sub.id AND skill.item_type = 'skill'
        JOIN deliverable d ON d.primary_skill_id = skill.id
        -- Weight comes from the exam's structure, never from how many questions we happen
        -- to hold: our bank's shape is our sampling, not the examination's.
        LEFT JOIN topic_exam_weight w
          ON w.topic_id = topic.id AND w.syllabus_version_id = topic.syllabus_version_id
        WHERE topic.syllabus_version_id = :version AND topic.item_type = 'topic'
        GROUP BY topic.id, topic.name, w.share, topic.display_order, topic.code
        HAVING count(DISTINCT d.question_id) > 0
        ORDER BY topic.display_order, topic.code
        """,
        version=version_id,
        subject=subject_id,
        pool=EXCLUDED_POOL,
    )
    if not rows:
        raise HTTPException(
            status_code=409,
            detail=(
                "no approved questions exist for this subject yet. Questions must be "
                "reviewed, licensed for delivery and mapped to a skill first."
            ),
        )

    weighted = any(row["share"] is not None for row in rows)
    topics = [
        TopicWeight(
            topic_id=row["topic_id"],
            share=float(row["share"]) if weighted and row["share"] is not None else 1.0,
            name=row["name"],
        )
        for row in rows
    ]
    source = "exam_structure" if weighted else "equal (no approved exam structure yet)"
    return topics, source


async def _subtopics(conn: AsyncConnection, subject_id: UUID) -> tuple[list[UnitWeight], str]:
    """Every examinable subtopic, with the share of the paper it carries.

    Read from `subtopic_exam_weight`, which is built from the printed sections of the paper.
    Where the document attributes a section to a subtopic the share is that section's; where
    it names only a topic, the view shares those questions out. Either way the number comes
    from the examination, never from how many questions our own bank happens to hold — that
    would make our sampling the examiner's, and every plan built on it circular.

    A subject whose paper structure has not been approved has no shares at all, and then the
    subtopics are weighted equally and the caller is told so rather than being handed a guess
    dressed as a fact.
    """
    version_id = await _current_syllabus(conn, subject_id)
    rows = await fetch_all(
        conn,
        """
        SELECT sub.id::text AS unit_id, sub.name, topic.id::text AS topic_id,
               topic.name AS topic_name, w.share,
               w.expected_questions,
               count(*) OVER (PARTITION BY topic.id) AS siblings
        FROM curriculum_items sub
        JOIN curriculum_items topic ON topic.id = sub.parent_id
        LEFT JOIN subtopic_exam_weight w
          ON w.subtopic_id = sub.id AND w.syllabus_version_id = sub.syllabus_version_id
        WHERE sub.syllabus_version_id = :version AND sub.item_type = 'subtopic'
          AND sub.review_status = 'approved' AND sub.pilot_support_status = 'supported'
        ORDER BY topic.display_order, sub.display_order, sub.code
        """,
        version=version_id,
    )
    weighted = any(row["share"] is not None for row in rows)
    units = [
        UnitWeight(
            unit_id=row["unit_id"],
            name=row["name"],
            topic_id=row["topic_id"],
            topic_name=row["topic_name"],
            share=(
                float(row["share"])
                if weighted and row["share"] is not None
                # A subtopic with no printed share sits inside a paper that has one for its
                # siblings. Zero would delete it from every plan, so it keeps an equal share
                # of nothing rather than being silently dropped.
                else 1.0 / int(row["siblings"])
            ),
        )
        for row in rows
    ]
    source = (
        "the exam's printed section structure"
        if weighted
        else "equal (no approved exam structure yet)"
    )
    return units, source


async def _answers_so_far(conn: AsyncConnection, session_id: UUID) -> list[dict[str, Any]]:
    return await fetch_all(
        conn,
        """
        SELECT a.id, a.question_version_id, a.is_correct, a.response_ms,
               v.mastery_level_number AS level, v.expected_seconds,
               topic.id::text AS topic_id, sub.id::text AS subtopic_id
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
    student_id: UUID,
) -> dict[str, Any] | None:
    """The nearest question to the level we want, in this topic, that this student has never
    been asked.

    "Never been asked" spans every earlier sitting and every practice answer, not just this
    session: a question drilled last week would measure memory of it. Where a curated
    diagnostic pool exists its questions come first; a subject without one still works.
    """
    rows = await fetch_all(
        conn,
        """
        WITH deliverable AS MATERIALIZED (
          SELECT dq.question_id, dq.question_version_id, dq.mastery_level_number,
                 dq.primary_skill_id, q.usage_pool
          FROM deliverable_questions dq
          JOIN questions q ON q.id = dq.question_id AND q.usage_pool <> :pool
          WHERE dq.subject_id = :subject
        )
        SELECT dq.question_version_id, dq.mastery_level_number, v.stem, v.instructions,
               pg.title AS passage_title, pg.body AS passage_body, topic.name AS topic_name
        FROM deliverable dq
        -- The stem and its passage are read from the tables rather than through
        -- candidate_question_payload, which is itself built on deliverable_questions: joining
        -- it here made the planner evaluate that whole view twice, and the six gates behind it
        -- are not cheap. One evaluation took a seven-second question down to a tenth of that.
        JOIN question_versions v ON v.id = dq.question_version_id
        LEFT JOIN passages pg ON pg.id = v.passage_id
        JOIN curriculum_items skill ON skill.id = dq.primary_skill_id
        JOIN curriculum_items sub ON sub.id = skill.parent_id
        JOIN curriculum_items topic ON topic.id = sub.parent_id
        WHERE topic.id = CAST(:topic AS uuid)
          AND (CARDINALITY(CAST(:seen AS uuid[])) = 0
               OR NOT (dq.question_version_id = ANY (CAST(:seen AS uuid[]))))
          -- Anything this student has answered before, in any sitting or in practice.
          AND NOT EXISTS (
              SELECT 1 FROM student_question_history h
              WHERE h.student_id = :student AND h.question_id = dq.question_id
          )
        ORDER BY (dq.usage_pool = 'diagnostic') DESC,
                 abs(coalesce(dq.mastery_level_number, 3) - :level),
                 md5(:session || dq.question_version_id::text)
        LIMIT 1
        """,
        pool=EXCLUDED_POOL,
        subject=subject_id,
        topic=slot.topic_id,
        level=target_level,
        seen=seen,
        session=str(session_id),
        student=student_id,
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


async def _next_state(
    conn: AsyncConnection, session_id: UUID, subject_id: UUID, student_id: UUID
) -> CheckupState:
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

    question = await _pick_question(
        conn, subject_id, slot, target, session_id, seen, student_id
    )
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
    return await _next_state(
        conn, session_id, request.subject_id, request.student_id
    )


@router.get("/{session_id}", response_model=CheckupState, summary="Where this sitting is")
async def current(
    conn: Annotated[AsyncConnection, Depends(connection)], session_id: UUID
) -> CheckupState:
    """The next question of a sitting already in progress.

    Answers hand back the following question, which is all a client needs while it stays open
    — and nothing at all after a reload. Without this, resuming meant either starting a second
    sitting or sending an answer the student never gave to get a question back. Both were
    worse than an endpoint.
    """
    session = (
        (
            await conn.execute(
                text(
                    """
                    SELECT student_id, subject_id FROM study_sessions
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
    return await _next_state(
        conn, session_id, session["subject_id"], session["student_id"]
    )


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

    state = await _next_state(
        conn, session_id, session["subject_id"], session["student_id"]
    )
    if state.finished:
        await conn.execute(
            text("UPDATE study_sessions SET ended_at = now() WHERE id = :id AND ended_at IS NULL"),
            {"id": session_id},
        )
        await conn.commit()
    return state


def _standings(
    units: Sequence[UnitWeight], answers: Sequence[dict[str, Any]]
) -> list[UnitStanding]:
    """Turn the sitting into one reading per subtopic.

    The same ``summarise`` the topic report uses, run at a finer grain — it has never been
    topic-specific, it just groups attempts by whatever unit it is given. One rule for both
    readings means a topic's number and its subtopics' numbers cannot disagree.
    """
    grouped: dict[str, list[Attempt]] = {}
    for row in answers:
        grouped.setdefault(str(row["subtopic_id"]), []).append(
            Attempt(
                is_correct=bool(row["is_correct"]),
                level=int(row["level"] or 3),
                response_ms=int(row["response_ms"] or 0),
                expected_seconds=float(row["expected_seconds"] or 45),
            )
        )
    summary = summarise(
        subject_id="subtopics",
        topics=[
            TopicWeight(topic_id=unit.unit_id, share=unit.share, name=unit.name)
            for unit in units
        ],
        answers=[
            TopicAnswers(topic_id=key, attempts=tuple(value)) for key, value in grouped.items()
        ],
    )
    by_id = {estimate.topic_id: estimate for estimate in summary.topics}
    return [
        UnitStanding(
            unit_id=unit.unit_id,
            name=unit.name,
            topic_id=unit.topic_id,
            topic_name=unit.topic_name,
            share=unit.share,
            mastery=by_id[unit.unit_id].mastery if unit.unit_id in by_id else None,
            answered=by_id[unit.unit_id].answered if unit.unit_id in by_id else 0,
        )
        for unit in units
    ]


async def _forecast(
    conn: AsyncConnection,
    student_id: UUID,
    subject_id: UUID,
    standings: Sequence[UnitStanding],
) -> ScoreProjection | None:
    """What this stands to become, given the time the student says they have.

    Returns nothing without a goal. A projection needs a date to count sessions towards and a
    target to be measured against, and inventing either would turn a plan into a guess with a
    number on it.
    """
    goal = (
        (
            await conn.execute(
                text(
                    """
                    SELECT target_score, exam_date, minutes_per_day, study_days
                    FROM student_exam_goals
                    WHERE student_id = :student AND subject_id = :subject
                      AND status = 'active'
                    """
                ),
                {"student": student_id, "subject": subject_id},
            )
        )
        .mappings()
        .first()
    )
    if goal is None:
        return None

    sessions = sessions_before(
        goal["exam_date"], goal["minutes_per_day"], list(goal["study_days"] or [])
    )
    result: Projection = project(standings, sessions_available=sessions or 0)
    target = float(goal["target_score"]) if goal["target_score"] is not None else None
    shortfall = None
    if target is not None and result.score_projected < target:
        gap = round(target - result.score_projected, 1)
        shortfall = (
            f"This plan gets to {result.score_projected} of the {target} you are aiming for — "
            f"{gap} marks short. More study days, or a longer run-up, is what closes that; "
            "a different plan on the same hours will not."
        )

    return ScoreProjection(
        score_now=result.score_now,
        score_low=result.range_now[0],
        score_high=result.range_now[1],
        score_projected=result.score_projected,
        target_score=target,
        sessions_available=result.sessions_available,
        shortfall_note=shortfall,
        unmeasured_share=result.unmeasured_share,
        plan=[
            PlanLine(
                subtopic_id=UUID(line.unit_id),
                name=line.name,
                topic_name=line.topic_name,
                share=round(line.share, 4),
                mastery_now=round(line.mastery_now, 3),
                mastery_projected=round(line.mastery_projected, 3),
                sessions=line.sessions,
                marks_gained=round(line.marks_gained, 2),
                reason=line.reason,
            )
            for line in result.plan
        ],
        caveat=result.caveat,
    )


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

    units, weights_source = await _subtopics(conn, session["subject_id"])
    standings = _standings(units, answers)
    correct_by_unit: dict[str, int] = {}
    for row in answers:
        if row["is_correct"]:
            key = str(row["subtopic_id"])
            correct_by_unit[key] = correct_by_unit.get(key, 0) + 1
    forecast = await _forecast(conn, session["student_id"], session["subject_id"], standings)

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
        subtopics=[
            SubtopicReport(
                subtopic_id=UUID(standing.unit_id),
                name=standing.name,
                topic_name=standing.topic_name,
                share=round(standing.share, 4),
                answered=standing.answered,
                correct=correct_by_unit.get(standing.unit_id, 0),
                mastery=standing.mastery,
                confidence=confidence_for(standing.answered),
            )
            for standing in standings
        ],
        weights_source=weights_source,
        projection=forecast,
        unassessed_topics=[names.get(topic_id, topic_id) for topic_id in summary.unassessed_topics],
        priority_topics=[names.get(topic_id, topic_id) for topic_id in summary.priority_topics],
        caveat=(
            # A student reads this sentence, so it is written as a sentence: no "(s)".
            f"Based on {summary.answered} question{'' if summary.answered == 1 else 's'}. "
            "This is a starting point for planning, "
            "not a measure of ability, and it says nothing about topics it did not reach."
        ),
    )
