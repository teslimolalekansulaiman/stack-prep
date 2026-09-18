"""The student's own side: who they are, what they are sitting for, and what they are aiming at.

Three things a student side needs before a single question is asked, and none of them existed:

* the catalogue they choose from — which examinations we carry, which subjects under each,
  and, said honestly, whether that subject can actually run a check-up yet;
* a goal — the score they want and the date they want it by, which is what turns an estimate
  into a plan and is the one thing only the student can supply;
* somewhere to come back to, so a student who closes the tab finds their sitting where they
  left it rather than starting again.

Sign-in is still not built (ADR-0013). Until it is, the student is identified by the id the
client holds, which is exactly as weak as it sounds and is why nothing here reads or writes
anything a person outside this machine should not see. What it is not is a mock: the goal
rows, the sessions and the attempts are the real tables, so the day a login lands nothing
here needs rewriting.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import connection, fetch_all

router = APIRouter(prefix="/v1/student", tags=["student"])

#: A study session is three quarters of an hour. Used to turn minutes a day into the number
#: of sessions a plan has to spend.
SESSION_MINUTES = 45


class SubjectOffer(BaseModel):
    subject_id: UUID
    code: str
    name: str
    #: What a student can actually do with this subject today.
    deliverable_questions: int
    teachable_skills: int
    ready: bool
    #: Present when ready is false: the plain reason, for the student, not the operator.
    blocked_reason: str | None


class ExaminationOffer(BaseModel):
    examination_id: UUID
    short_name: str
    name: str
    exam_body: str
    subjects: list[SubjectOffer]


class Goal(BaseModel):
    subject_id: UUID
    subject_name: str
    target_score: float | None
    exam_date: date | None
    minutes_per_day: int | None
    study_days: list[int] | None
    #: Derived, not stored: what the goal amounts to in study sessions before the exam.
    sessions_before_exam: int | None


class GoalIn(BaseModel):
    target_score: float | None = Field(default=None, gt=0, le=100)
    exam_date: date | None = None
    minutes_per_day: int | None = Field(default=None, ge=5, le=600)
    study_days: list[int] | None = None


class SittingSummary(BaseModel):
    session_id: UUID
    subject_id: UUID
    subject_name: str
    answered: int
    finished: bool


def sessions_before(
    goal_date: date | None, minutes: int | None, days: list[int] | None
) -> int | None:
    """How many study sessions fit between today and the exam.

    Counts only the days the student said they would study, because a plan built on days they
    never sit down is a plan that does not happen.
    """
    if goal_date is None or minutes is None:
        return None
    remaining = (goal_date - date.today()).days
    if remaining <= 0:
        return 0
    study_days = days or [1, 2, 3, 4, 5, 6, 7]
    weeks = remaining / 7
    sittings_per_day = max(1, minutes // SESSION_MINUTES)
    return int(weeks * len(study_days) * sittings_per_day)


@router.get("/catalogue", response_model=list[ExaminationOffer], summary="What can be sat")
async def catalogue(
    conn: Annotated[AsyncConnection, Depends(connection)],
) -> list[ExaminationOffer]:
    """Every active examination and its subjects, each saying whether it is ready.

    "Ready" is not a flag somebody set — it is counted from `deliverable_questions`, the view
    that already decides what a student may be shown. A subject with an approved syllabus and
    no approved questions appears here, greyed out, with the reason: hiding it would make the
    catalogue look complete when it is not.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT e.id AS examination_id, e.short_name, e.name, e.exam_body,
               s.id AS subject_id, s.code, s.name AS subject_name,
               (SELECT count(*) FROM deliverable_questions d WHERE d.subject_id = s.id)
                 AS deliverable_questions,
               (SELECT count(*) FROM teachable_skills t WHERE t.subject_id = s.id)
                 AS teachable_skills
        FROM examinations e
        JOIN subjects s ON s.examination_id = e.id
        WHERE e.status = 'active' AND s.status = 'active'
        ORDER BY e.short_name, s.name
        """,
    )
    offers: dict[UUID, ExaminationOffer] = {}
    for row in rows:
        offer = offers.setdefault(
            row["examination_id"],
            ExaminationOffer(
                examination_id=row["examination_id"],
                short_name=row["short_name"],
                name=row["name"],
                exam_body=row["exam_body"],
                subjects=[],
            ),
        )
        deliverable = int(row["deliverable_questions"])
        teachable = int(row["teachable_skills"])
        # Four is the shortest check-up the engine will build; below that there is nothing
        # to spread across a syllabus.
        ready = deliverable >= 4
        if ready:
            reason = None
        elif teachable == 0:
            reason = "Its syllabus is still being approved."
        else:
            reason = (
                "Its syllabus is ready, but the questions are still being checked — every "
                "answer and difficulty is verified by a person before anyone sits it."
            )
        offer.subjects.append(
            SubjectOffer(
                subject_id=row["subject_id"],
                code=row["code"],
                name=row["subject_name"],
                deliverable_questions=deliverable,
                teachable_skills=teachable,
                ready=ready,
                blocked_reason=reason,
            )
        )
    return list(offers.values())


@router.get(
    "/{student_id}/goals", response_model=list[Goal], summary="What this student is aiming at"
)
async def goals(
    conn: Annotated[AsyncConnection, Depends(connection)], student_id: UUID
) -> list[Goal]:
    rows = await fetch_all(
        conn,
        """
        SELECT g.subject_id, s.name AS subject_name, g.target_score, g.exam_date,
               g.minutes_per_day, g.study_days
        FROM student_exam_goals g
        JOIN subjects s ON s.id = g.subject_id
        WHERE g.student_id = :student AND g.status = 'active'
        ORDER BY s.name
        """,
        student=student_id,
    )
    return [
        Goal(
            subject_id=row["subject_id"],
            subject_name=row["subject_name"],
            target_score=float(row["target_score"]) if row["target_score"] is not None else None,
            exam_date=row["exam_date"],
            minutes_per_day=row["minutes_per_day"],
            study_days=list(row["study_days"]) if row["study_days"] else None,
            sessions_before_exam=sessions_before(
                row["exam_date"], row["minutes_per_day"], list(row["study_days"] or [])
            ),
        )
        for row in rows
    ]


@router.put(
    "/{student_id}/goals/{subject_id}",
    response_model=Goal,
    summary="Set the target and the date",
)
async def set_goal(
    conn: Annotated[AsyncConnection, Depends(connection)],
    student_id: UUID,
    subject_id: UUID,
    goal: GoalIn,
) -> Goal:
    """Record what the student is aiming at, replacing any active goal for this subject.

    One active goal per subject is a database rule, not a convention here, so setting a new
    one updates the existing row rather than leaving two and hoping the reader picks the
    newer. The old values are overwritten: a goal is a current intention, and its history is
    not something anything downstream reads.
    """
    exists = (
        await conn.execute(text("SELECT 1 FROM students WHERE id = :id"), {"id": student_id})
    ).first()
    if exists is None:
        raise HTTPException(status_code=404, detail="unknown student")
    await conn.execute(
        text(
            """
            INSERT INTO student_exam_goals (student_id, subject_id, target_score, exam_date,
              minutes_per_day, study_days, status)
            VALUES (:student, :subject, :target, :exam_date, :minutes,
              CAST(:days AS smallint[]), 'active')
            ON CONFLICT (student_id, subject_id) WHERE status = 'active'
            DO UPDATE SET target_score = EXCLUDED.target_score,
                          exam_date = EXCLUDED.exam_date,
                          minutes_per_day = EXCLUDED.minutes_per_day,
                          study_days = EXCLUDED.study_days,
                          updated_at = now()
            """
        ),
        {
            "student": student_id,
            "subject": subject_id,
            "target": goal.target_score,
            "exam_date": goal.exam_date,
            "minutes": goal.minutes_per_day,
            "days": goal.study_days,
        },
    )
    await conn.commit()
    for row in await goals(conn, student_id):
        if row.subject_id == subject_id:
            return row
    raise HTTPException(status_code=500, detail="the goal was written but could not be read back")


@router.get(
    "/{student_id}/sittings", response_model=list[SittingSummary], summary="Check-ups so far"
)
async def sittings(
    conn: Annotated[AsyncConnection, Depends(connection)], student_id: UUID
) -> list[SittingSummary]:
    """Every check-up this student has started, finished or not.

    The unfinished one is the point: a student who closed the tab halfway should be offered
    the sitting they were in, not a fresh one that throws their answers away.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT ss.id AS session_id, ss.subject_id, s.name AS subject_name,
               ss.ended_at IS NOT NULL AS finished,
               (SELECT count(*) FROM attempts a WHERE a.session_id = ss.id) AS answered
        FROM study_sessions ss
        JOIN subjects s ON s.id = ss.subject_id
        WHERE ss.student_id = :student AND ss.session_type = 'checkup'
        ORDER BY ss.started_at DESC
        """,
        student=student_id,
    )
    return [SittingSummary(**dict(row)) for row in rows]
