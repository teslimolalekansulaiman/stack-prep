"""Guided practice: the teaching loop that runs after the check-up.

One question at a time. Answer it and the loop moves on. Miss it and you get a hint and the
same question again. Miss it again and the worked solution is shown a step at a time, and the
question is marked as taught rather than as known.

THE RULE THAT PROTECTS EVERY NUMBER DOWNSTREAM. An assisted attempt earns no mastery. A
question answered after a hint, or after the solution was shown, is recorded in full — that is
what `hint_count` and `solution_viewed_before_answer` are for — but it does not move the
estimate, and neither does a correct answer the student said was a guess. The rule lives in
the `scoring_attempts` view so no query here has to remember it. Without it, mastery climbs
with every hint, the projection built on mastery becomes a promise nobody can keep, and the
student is told they are ready when they are not.

WHAT IT TEACHES NEXT. The subtopic comes from the same plan the report shows: the one where
the next session earns the most marks, which is share of the paper times what a session can
move. Within it the question comes at the level the student is working at, and never one they
have answered before. So the loop and the projection cannot disagree about what matters — they
read the same engine.

WHAT THE COACH MAY GENERATE. The board still renders `solution_steps` and nothing else: the
working a student reads is the working a reviewer checked. What is generated is the answer
when they ask about it — `/ask`, once the question is already taught and its answer already
shown, explaining the reviewed steps rather than replacing them. If that tutor is unavailable
the steps are served in its place, so the lesson degrades and never breaks.

WHAT IS NOT HERE YET. There is no voice: the coach writes and the student types, and student
speech stays out until the legal review has ruled on recording a minor. And there is no
working pad, so `attempts.working` stays null; the column exists so that the day the pad
lands, the attempts already recorded have the shape it needs.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app import tutor
from app.config import Settings, get_settings
from app.db import connection, fetch_all
from app.routers.checkup import UnitWeight, _subtopics
from engine.projection import UnitStanding, project
from engine.version import ENGINE_VERSION

router = APIRouter(prefix="/v1/practice", tags=["practice"])

#: Questions this student has already met are never asked again, in any context.
EXCLUDED_POOL = "held_out"

#: How far a guided session goes before it suggests stopping. Long enough to be worth
#: sitting down for, short enough to finish.
DEFAULT_LENGTH = 10

Confidence = Literal["guessed", "unsure", "sure"]
Stage = Literal["asking", "hint", "explain", "finished"]


class StartPractice(BaseModel):
    student_id: UUID
    subject_id: UUID
    length: int = Field(default=DEFAULT_LENGTH, ge=1, le=40)


class AnswerIn(BaseModel):
    #: Client-generated, so a retried submission is stored once.
    attempt_id: UUID = Field(default_factory=uuid4)
    question_version_id: UUID
    selected_option_key: str = Field(pattern="^[A-F]$")
    response_ms: int = Field(ge=0, le=3_600_000)
    #: Asked after answering and before being told. None means they were not asked.
    confidence: Confidence | None = None


class AskIn(BaseModel):
    """A question typed at the board."""

    question_version_id: UUID
    #: Which step was showing. None means the board had finished writing.
    step_index: int | None = Field(default=None, ge=0, le=40)
    asked: str = Field(min_length=1, max_length=tutor.MAX_QUESTION_CHARS)

    @field_validator("asked")
    @classmethod
    def _not_only_spaces(cls, value: str) -> str:
        # Stored stripped, so a question of blank space is refused here rather than reaching
        # the tutor as an empty prompt or the table as a row that says nothing.
        stripped = value.strip()
        if not stripped:
            raise ValueError("ask the coach something")
        return stripped


class TutorReply(BaseModel):
    reply: str
    #: How the student got this answer: the tutor, or the reviewed steps standing in for it.
    source: tutor.Source
    #: Said out loud so the budget is a thing the student can see coming rather than a wall
    #: they hit without warning.
    asks_left: int


class Option(BaseModel):
    option_key: str
    body: str


class Misconception(BaseModel):
    name: str
    description: str
    remediation_note: str | None


class PracticeQuestion(BaseModel):
    question_version_id: UUID
    subtopic_name: str
    topic_name: str
    stem: str
    instructions: str | None
    passage_title: str | None
    passage_body: str | None
    options: list[Option]
    #: Hints already spent on this question, so a reload does not hand one back.
    hints_used: int


class PracticeState(BaseModel):
    session_id: UUID
    stage: Stage
    position: int
    length: int
    answered: int
    correct_unaided: int
    taught: int
    question: PracticeQuestion | None
    #: Set when the last answer was wrong and a hint is being offered.
    hint: str | None = None
    #: Set once the student has missed twice: the board's script.
    solution_steps: list[str] | None = None
    correct_option_key: str | None = None
    #: Why that wrong answer is a tempting one, when the option carries the explanation.
    misconception: Misconception | None = None
    #: Said plainly to the student when the sitting ends.
    closing_note: str | None = None


async def _session(conn: AsyncConnection, session_id: UUID) -> dict[str, Any]:
    row = (
        (
            await conn.execute(
                text(
                    """
                    SELECT id, student_id, subject_id, planned_items, ended_at
                    FROM study_sessions
                    WHERE id = :id AND session_type = 'guided'
                    """
                ),
                {"id": session_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="unknown practice session")
    return dict(row)


async def _plan(conn: AsyncConnection, student_id: UUID, subject_id: UUID) -> list[str]:
    """Subtopics in the order the projection says they earn the most marks.

    Read from the same engine the report reads, so what the student is taught and what they
    were told they would be taught cannot drift apart.
    """
    units, _ = await _subtopics(conn, subject_id)
    standings = await _standings_from_history(conn, student_id, units)
    result = project(standings, sessions_available=len(units))
    return [line.unit_id for line in result.plan]


async def _standings_from_history(
    conn: AsyncConnection, student_id: UUID, units: list[UnitWeight]
) -> list[UnitStanding]:
    """Where this student stands per subtopic, from every attempt that counts.

    Every sitting and every practice answer, not just the check-up: a student who has been
    taught a subtopic since their check-up should be planned for as they are now.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT sub.id::text AS unit_id,
               count(*) AS answered,
               count(*) FILTER (WHERE a.is_correct) AS correct
        FROM scoring_attempts a
        JOIN question_versions v ON v.id = a.question_version_id
        JOIN question_classifications c
          ON c.question_id = v.question_id AND c.classification_role = 'primary'
         AND c.review_status = 'approved'
        JOIN curriculum_items skill ON skill.id = c.curriculum_item_id
        JOIN curriculum_items sub ON sub.id = skill.parent_id
        WHERE a.student_id = :student
        GROUP BY sub.id
        """,
        student=student_id,
    )
    seen = {row["unit_id"]: row for row in rows}
    standings: list[UnitStanding] = []
    for unit in units:
        row = seen.get(unit.unit_id)
        standings.append(
            UnitStanding(
                unit_id=unit.unit_id,
                name=unit.name,
                topic_id=unit.topic_id,
                topic_name=unit.topic_name,
                share=unit.share,
                mastery=(int(row["correct"]) / int(row["answered"])) if row else None,
                answered=int(row["answered"]) if row else 0,
            )
        )
    return standings


async def _level_for(conn: AsyncConnection, student_id: UUID, subtopic_id: str) -> int:
    """The level this student is working at in one subtopic.

    Their last few unaided answers there, walked the way the check-up walks: up when right,
    down when wrong. A subtopic they have never met starts in the middle.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT a.is_correct, v.mastery_level_number AS level
        FROM scoring_attempts a
        JOIN question_versions v ON v.id = a.question_version_id
        JOIN question_classifications c
          ON c.question_id = v.question_id AND c.classification_role = 'primary'
        JOIN curriculum_items skill ON skill.id = c.curriculum_item_id
        WHERE a.student_id = :student AND skill.parent_id = CAST(:sub AS uuid)
        ORDER BY a.answered_at_client DESC
        LIMIT 5
        """,
        student=student_id,
        sub=subtopic_id,
    )
    if not rows:
        return 3
    last = rows[0]
    level = int(last["level"] or 3)
    return max(1, min(5, level + (1 if last["is_correct"] else -1)))


async def _pick(
    conn: AsyncConnection, subject_id: UUID, student_id: UUID, subtopic_id: str, level: int
) -> dict[str, Any] | None:
    rows = await fetch_all(
        conn,
        """
        WITH deliverable AS MATERIALIZED (
          SELECT dq.question_id, dq.question_version_id, dq.mastery_level_number,
                 dq.primary_skill_id
          FROM deliverable_questions dq
          JOIN questions q ON q.id = dq.question_id AND q.usage_pool <> :pool
          WHERE dq.subject_id = :subject
        )
        SELECT dq.question_version_id, v.stem, v.instructions,
               pg.title AS passage_title, pg.body AS passage_body,
               sub.name AS subtopic_name, topic.name AS topic_name
        FROM deliverable dq
        JOIN question_versions v ON v.id = dq.question_version_id
        LEFT JOIN passages pg ON pg.id = v.passage_id
        JOIN curriculum_items skill ON skill.id = dq.primary_skill_id
        JOIN curriculum_items sub ON sub.id = skill.parent_id
        JOIN curriculum_items topic ON topic.id = sub.parent_id
        WHERE sub.id = CAST(:sub AS uuid)
          AND NOT EXISTS (
              SELECT 1 FROM student_question_history h
              WHERE h.student_id = :student AND h.question_id = dq.question_id
          )
        ORDER BY abs(coalesce(dq.mastery_level_number, 3) - :level),
                 md5(:student || dq.question_version_id::text)
        LIMIT 1
        """,
        pool=EXCLUDED_POOL,
        subject=subject_id,
        sub=subtopic_id,
        student=str(student_id),
        level=level,
    )
    return rows[0] if rows else None


async def _options(conn: AsyncConnection, question_version_id: UUID) -> list[Option]:
    rows = await fetch_all(
        conn,
        """
        SELECT option_key, body FROM question_options
        WHERE question_version_id = :version ORDER BY display_order, option_key
        """,
        version=question_version_id,
    )
    return [Option(**dict(row)) for row in rows]


async def _hints_used(conn: AsyncConnection, session_id: UUID, version_id: UUID) -> int:
    """How much help this question has already had in this sitting.

    Held in the attempts rather than in memory, so a student who reloads mid-question is not
    handed a fresh hint, and a reviewer reading the table later can see what was given.
    """
    value = (
        await conn.execute(
            text(
                """
                SELECT count(*) FROM attempts
                WHERE session_id = :session AND question_version_id = :version
                """
            ),
            {"session": session_id, "version": version_id},
        )
    ).scalar()
    return int(value or 0)


async def _state(
    conn: AsyncConnection,
    session: dict[str, Any],
    *,
    stage: Stage = "asking",
    hint: str | None = None,
    solution_steps: list[str] | None = None,
    correct_option_key: str | None = None,
    misconception: Misconception | None = None,
    repeat_version_id: UUID | None = None,
) -> PracticeState:
    """The whole loop's state, rebuilt from what is stored rather than carried in memory."""
    counts = (
        (
            await conn.execute(
                text(
                    """
                    SELECT count(DISTINCT a.question_version_id) AS seen,
                           -- Taught, not answered: a question that was missed twice and then
                           -- explained. Counted from the attempts rather than from a flag,
                           -- because nothing is answered after the board and there is no
                           -- attempt to hang a flag on.
                           (SELECT count(*) FROM (
                              SELECT question_version_id
                              FROM attempts t
                              WHERE t.session_id = :session
                              GROUP BY question_version_id
                              HAVING count(*) >= 2 AND bool_and(coalesce(t.is_correct, false)
                                                                 IS FALSE)
                            ) AS explained) AS taught,
                           (SELECT count(*) FROM scoring_attempts s
                             WHERE s.session_id = :session AND s.is_correct) AS unaided
                    FROM attempts a WHERE a.session_id = :session
                    """
                ),
                {"session": session["id"]},
            )
        )
        .mappings()
        .first()
    )
    assert counts is not None
    seen = int(counts["seen"])
    length = int(session["planned_items"] or DEFAULT_LENGTH)

    question: PracticeQuestion | None = None
    if repeat_version_id is not None:
        found = (
            (
                await conn.execute(
                    text(
                        """
                        SELECT v.id AS question_version_id, v.stem, v.instructions,
                               pg.title AS passage_title, pg.body AS passage_body,
                               sub.name AS subtopic_name, topic.name AS topic_name
                        FROM question_versions v
                        LEFT JOIN passages pg ON pg.id = v.passage_id
                        JOIN question_classifications c
                          ON c.question_id = v.question_id AND c.classification_role = 'primary'
                        JOIN curriculum_items skill ON skill.id = c.curriculum_item_id
                        JOIN curriculum_items sub ON sub.id = skill.parent_id
                        JOIN curriculum_items topic ON topic.id = sub.parent_id
                        WHERE v.id = :version
                        """
                    ),
                    {"version": repeat_version_id},
                )
            )
            .mappings()
            .first()
        )
        if found is not None:
            question = PracticeQuestion(
                **dict(found),
                options=await _options(conn, repeat_version_id),
                hints_used=await _hints_used(conn, session["id"], repeat_version_id),
            )
    elif stage == "asking" and seen < length:
        for subtopic_id in await _plan(conn, session["student_id"], session["subject_id"]):
            level = await _level_for(conn, session["student_id"], subtopic_id)
            picked = await _pick(
                conn, session["subject_id"], session["student_id"], subtopic_id, level
            )
            if picked is not None:
                question = PracticeQuestion(
                    **dict(picked),
                    options=await _options(conn, picked["question_version_id"]),
                    hints_used=0,
                )
                break

    finished = question is None and stage == "asking"
    closing = None
    if finished:
        closing = (
            f"{counts['unaided']} of {seen} answered without help. "
            f"{counts['taught']} were taught rather than answered, and none of those counts "
            "as knowing it yet — the same ground comes back with fresh questions."
        )
    return PracticeState(
        session_id=session["id"],
        stage="finished" if finished else stage,
        position=min(seen + (0 if stage == "asking" else 1), length),
        length=length,
        answered=seen,
        correct_unaided=int(counts["unaided"]),
        taught=int(counts["taught"]),
        question=question,
        hint=hint,
        solution_steps=solution_steps,
        correct_option_key=correct_option_key,
        misconception=misconception,
        closing_note=closing,
    )


@router.post("/start", response_model=PracticeState, summary="Begin a guided session")
async def start(
    conn: Annotated[AsyncConnection, Depends(connection)], request: StartPractice
) -> PracticeState:
    student = (
        await conn.execute(
            text("SELECT 1 FROM students WHERE id = :id"), {"id": request.student_id}
        )
    ).first()
    if student is None:
        raise HTTPException(status_code=404, detail="unknown student")
    session_id = (
        await conn.execute(
            text(
                """
                INSERT INTO study_sessions (student_id, subject_id, session_type,
                  planned_items, engine_version)
                VALUES (:student, :subject, 'guided', :length, :engine)
                RETURNING id
                """
            ),
            {
                "student": request.student_id,
                "subject": request.subject_id,
                "length": request.length,
                "engine": ENGINE_VERSION,
            },
        )
    ).scalar_one()
    await conn.commit()
    return await _state(conn, await _session(conn, session_id))


@router.get("/{session_id}", response_model=PracticeState, summary="Where this session is")
async def current(
    conn: Annotated[AsyncConnection, Depends(connection)], session_id: UUID
) -> PracticeState:
    """The next question, for a client that has just reloaded."""
    return await _state(conn, await _session(conn, session_id))


@router.post(
    "/{session_id}/answer",
    response_model=PracticeState,
    summary="Answer, and find out what happens next",
)
async def answer(
    conn: Annotated[AsyncConnection, Depends(connection)],
    session_id: UUID,
    submission: AnswerIn,
) -> PracticeState:
    """Record the answer and decide the next move: on, a hint, or the board.

    The ladder is read from what is stored, not from anything the client says, so a client
    that replays or reorders its calls cannot talk its way past a hint or skip the board.
    """
    session = await _session(conn, session_id)
    already = await _hints_used(conn, session_id, submission.question_version_id)

    key = (
        await conn.execute(
            text(
                """
                SELECT option_key FROM question_options
                WHERE question_version_id = :version AND is_correct
                """
            ),
            {"version": submission.question_version_id},
        )
    ).scalar()
    if key is None:
        raise HTTPException(status_code=409, detail="this question has no key")
    correct = submission.selected_option_key == key

    await conn.execute(
        text(
            """
            INSERT INTO attempts (id, student_id, question_version_id, session_id, context,
              selected_option_key, is_correct, response_ms, hint_count,
              solution_viewed_before_answer, answered_at_client, confidence, engine_version)
            VALUES (:id, :student, :version, :session, 'guided', :choice, :correct, :ms,
              :hints, :shown, now(), :confidence, :engine)
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {
            "id": submission.attempt_id,
            "student": session["student_id"],
            "version": submission.question_version_id,
            "session": session_id,
            "choice": submission.selected_option_key,
            "correct": correct,
            "ms": submission.response_ms,
            "hints": already,
            "shown": already >= 2,
            "confidence": submission.confidence,
            "engine": ENGINE_VERSION,
        },
    )
    await conn.commit()

    if correct:
        return await _state(conn, session)

    # First miss: a hint, and the same question again.
    if already == 0:
        hints = (
            await conn.execute(
                text("SELECT hints FROM question_versions WHERE id = :v"),
                {"v": submission.question_version_id},
            )
        ).scalar()
        chosen = (
            (
                await conn.execute(
                    text(
                        """
                        SELECT m.name, m.description, m.remediation_note
                        FROM question_options o
                        JOIN misconceptions m ON m.id = o.misconception_id
                        WHERE o.question_version_id = :v AND o.option_key = :k
                        """
                    ),
                    {"v": submission.question_version_id, "k": submission.selected_option_key},
                )
            )
            .mappings()
            .first()
        )
        return await _state(
            conn,
            session,
            stage="hint",
            # A hint written for the mistake the student actually made beats the general one,
            # and is used whenever the option they chose carries an explanation.
            hint=(
                str(chosen["remediation_note"])
                if chosen is not None and chosen["remediation_note"]
                else (next(iter(hints or [""]), "") or "Read the question again, slowly.")
            ),
            misconception=Misconception(**dict(chosen)) if chosen is not None else None,
            repeat_version_id=submission.question_version_id,
        )

    # Missed with the hint in hand: show the working.
    steps = (
        await conn.execute(
            text("SELECT solution_steps FROM question_versions WHERE id = :v"),
            {"v": submission.question_version_id},
        )
    ).scalar()
    return await _state(
        conn,
        session,
        stage="explain",
        solution_steps=[str(step) for step in (steps or [])],
        correct_option_key=str(key),
        repeat_version_id=submission.question_version_id,
    )


@router.post(
    "/{session_id}/taught",
    response_model=PracticeState,
    summary="Move on once the board has been read",
)
async def taught(
    conn: Annotated[AsyncConnection, Depends(connection)], session_id: UUID
) -> PracticeState:
    """Close the taught question and ask for the next one.

    Nothing is scored here: the question was explained, not answered. What comes back later is
    the SKILL, not this item — the subtopic is still weak, so the plan keeps choosing it, and
    the next question in it is one the student has not seen. Re-asking the same item would
    test whether they remember being told, which is not the same as knowing.
    """
    return await _state(conn, await _session(conn, session_id))


async def _asks_used_today(conn: AsyncConnection, student_id: UUID) -> int:
    """How many questions this student has already asked today, in their own timezone.

    Counted from the stored turns rather than from anything the client reports, for the same
    reason the hint ladder is: a budget a browser keeps is not a budget.
    """
    return int(
        (
            await conn.execute(
                text(
                    """
                    SELECT count(*)
                    FROM tutor_turns t
                    JOIN students s ON s.id = t.student_id
                    WHERE t.student_id = :student
                      AND t.asked_at >= date_trunc(
                            'day', now() AT TIME ZONE coalesce(s.timezone, 'UTC')
                          ) AT TIME ZONE coalesce(s.timezone, 'UTC')
                    """
                ),
                {"student": student_id},
            )
        ).scalar()
        or 0
    )


async def _lesson_on_the_board(
    conn: AsyncConnection, session_id: UUID, version_id: UUID, step_index: int | None
) -> tutor.Lesson:
    """Assemble what the tutor may see, from reviewed content and this session's attempts.

    Everything here is read on the server. The client sends the student's words and which step
    they were looking at; it does not get to say what the question was, what the working says
    or what the answer is, so a client cannot widen the tutor's context by asking it to.
    """
    found = (
        (
            await conn.execute(
                text(
                    """
                    SELECT v.stem, v.solution_steps, sub.name AS subtopic_name
                    FROM question_versions v
                    JOIN question_classifications c
                      ON c.question_id = v.question_id AND c.classification_role = 'primary'
                    JOIN curriculum_items skill ON skill.id = c.curriculum_item_id
                    JOIN curriculum_items sub ON sub.id = skill.parent_id
                    WHERE v.id = :version
                    """
                ),
                {"version": version_id},
            )
        )
        .mappings()
        .first()
    )
    if found is None:
        raise HTTPException(status_code=404, detail="unknown question")

    steps = [str(step) for step in (found["solution_steps"] or [])]
    key = (
        await conn.execute(
            text(
                """
                SELECT option_key FROM question_options
                WHERE question_version_id = :version AND is_correct
                """
            ),
            {"version": version_id},
        )
    ).scalar()
    if key is None:
        raise HTTPException(status_code=409, detail="this question has no key")

    # The wrong answer they gave last, and what that particular wrong answer usually means.
    # Without it the coach can only explain the solution; with it, it can explain their
    # mistake, which is the thing they actually came to the board with.
    mistake = (
        (
            await conn.execute(
                text(
                    """
                    SELECT a.selected_option_key, m.description
                    FROM attempts a
                    LEFT JOIN question_options o
                      ON o.question_version_id = a.question_version_id
                     AND o.option_key = a.selected_option_key
                    LEFT JOIN misconceptions m ON m.id = o.misconception_id
                    WHERE a.session_id = :session AND a.question_version_id = :version
                      AND coalesce(a.is_correct, false) IS FALSE
                    ORDER BY a.answered_at_client DESC
                    LIMIT 1
                    """
                ),
                {"session": session_id, "version": version_id},
            )
        )
        .mappings()
        .first()
    )

    return tutor.Lesson(
        subtopic_name=str(found["subtopic_name"]),
        stem=str(found["stem"]),
        options=[(option.option_key, option.body) for option in await _options(conn, version_id)],
        correct_option_key=str(key),
        steps=steps,
        step_index=step_index,
        chose=mistake["selected_option_key"] if mistake is not None else None,
        misconception=mistake["description"] if mistake is not None else None,
    )


@router.post(
    "/{session_id}/ask",
    response_model=TutorReply,
    summary="Ask the coach about the working on the board",
)
async def ask(
    conn: Annotated[AsyncConnection, Depends(connection)],
    settings: Annotated[Settings, Depends(get_settings)],
    session_id: UUID,
    question: AskIn,
) -> TutorReply:
    """Answer a question about the solution the student is being shown.

    ONLY AT THE BOARD. The session's own attempts have to say this question was missed twice
    and never got right — the same test `_state` uses to decide something was taught rather
    than answered. So a client cannot point this at a question the student is still answering,
    at one from another sitting, or at anything outside the practice pool it was served from.
    That is what keeps protected assessment content out of tutor retrieval (S5-AC6), and it
    means the answer is already written on the board before anything can be asked about it.

    NOTHING HERE IS SCORED. The item was taught, not answered; no attempt is written and no
    estimate moves. The turn is recorded because assistance is recorded (REQ-05) and because a
    reviewer reading a complaint needs the lesson that happened, not the one in the bank.
    """
    session = await _session(conn, session_id)

    standing = (
        (
            await conn.execute(
                text(
                    """
                    SELECT count(*) AS tries,
                           bool_and(coalesce(is_correct, false) IS FALSE) AS never_right
                    FROM attempts
                    WHERE session_id = :session AND question_version_id = :version
                    """
                ),
                {"session": session_id, "version": question.question_version_id},
            )
        )
        .mappings()
        .first()
    )
    assert standing is not None
    if int(standing["tries"]) < 2 or not standing["never_right"]:
        raise HTTPException(
            status_code=409, detail="the coach answers at the board, once a question is taught"
        )

    lesson = await _lesson_on_the_board(
        conn, session_id, question.question_version_id, question.step_index
    )

    used = await _asks_used_today(conn, session["student_id"])
    allowance = settings.ai_daily_calls_per_student
    if used >= allowance:
        # Spent for today. They still get the reviewed step rather than a locked box, and the
        # turn is still stored — a budget nobody can see being hit is a budget nobody can size.
        reply = tutor.Reply(text=tutor.fallback_text(lesson), source="budget")
    else:
        reply = await tutor.answer(lesson, question.asked, settings)

    await conn.execute(
        text(
            """
            INSERT INTO tutor_turns (student_id, session_id, question_version_id, step_index,
              asked, reply, source, model, input_tokens, output_tokens, latency_ms)
            VALUES (:student, :session, :version, :step, :asked, :reply, :source, :model,
              :input_tokens, :output_tokens, :latency_ms)
            """
        ),
        {
            "student": session["student_id"],
            "session": session_id,
            "version": question.question_version_id,
            "step": question.step_index,
            "asked": question.asked,
            "reply": reply.text,
            "source": reply.source,
            "model": reply.model,
            "input_tokens": reply.input_tokens,
            "output_tokens": reply.output_tokens,
            "latency_ms": reply.latency_ms,
        },
    )
    await conn.commit()

    return TutorReply(
        reply=reply.text,
        source=reply.source,
        asks_left=max(0, allowance - (used + 1)),
    )
