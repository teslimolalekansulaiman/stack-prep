"""Reserving questions for the check-up, and reporting honestly on what is still missing.

A question's *pool* is a different thing from its *review state*, and conflating them is the
mistake this router exists to prevent. Reserving a question into the diagnostic pool says
"this one is set aside for first sittings, not for practice". It says nothing about whether a
student may see it — that is decided by the six gates behind `deliverable_questions`, and a
reserved question that has not passed them is simply a reservation with work still to do.

Why reserve at all. A check-up is the only sitting where the student has no history, so its
questions have to be ones they have never practised. If the same items appear in practice,
every later check-up measures memory instead of understanding. The pool is the separation.

How the choice is made:

* Topics are weighted the way the check-up itself weights them — by the exam's own structure,
  through the same `build_blueprint` the engine uses. One weighting rule, one place.
* Within a topic the reservation spreads across difficulty levels, because a ladder that can
  only go down is not a ladder. A topic held entirely at level 3 cannot tell a strong student
  from an average one.
* Within a level, questions closest to being deliverable go first, so review effort lands on
  the items that will actually reach a student.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import connection, fetch_all
from engine.checkup import DEFAULT_LENGTH, TopicWeight, build_blueprint

router = APIRouter(prefix="/v1/pool", tags=["pool"])

DIAGNOSTIC = "diagnostic"
PRACTICE = "practice"

#: A check-up asks about fifteen questions, and a student may sit one more than once. Three
#: sittings' worth is the default reservation: enough that a second check-up need not repeat
#: itself, small enough that it does not strip the practice bank.
DEFAULT_RESERVE = DEFAULT_LENGTH * 3


class TopicPlan(BaseModel):
    topic_id: UUID
    topic_name: str
    #: Share of the exam this topic carries, from its approved sections.
    share: float | None
    wanted: int
    already_reserved: int
    available_in_practice: int
    #: What would actually be moved: the smaller of what is wanted and what exists.
    would_reserve: int
    #: Levels a further reservation would add. Empty once the topic's quota is filled.
    levels_covered: list[int]
    #: Levels the pool already holds for this topic — what the ladder can actually use
    #: today. A single entry means a check-up that cannot adapt.
    levels_in_pool: list[int]


class ReservePlan(BaseModel):
    subject_id: UUID
    size: int
    weights_source: str
    topics: list[TopicPlan]
    total_would_reserve: int
    #: Said plainly rather than left for the caller to infer from the numbers.
    shortfall_note: str | None
    #: A check-up adapts by difficulty. Without levels it cannot, and that is worth saying
    #: before anyone spends review time on the wrong thing.
    level_spread_note: str | None = None


class ReserveRequest(BaseModel):
    subject_id: UUID
    size: int = Field(default=DEFAULT_RESERVE, ge=4, le=500)


class ReserveResult(BaseModel):
    subject_id: UUID
    reserved: int
    total_in_pool: int
    deliverable_now: int
    topics: list[TopicPlan]


class BlockedCount(BaseModel):
    reason: str
    questions: int


class Readiness(BaseModel):
    subject_id: UUID
    in_pool: int
    deliverable: int
    #: Why the rest cannot reach a student yet, most common first.
    blocked_by: list[BlockedCount]
    ready_for_checkup: bool


async def _current_version(conn: AsyncConnection, subject_id: UUID) -> UUID:
    row = (
        await conn.execute(
            text(
                """
                SELECT id FROM syllabus_versions
                WHERE subject_id = :subject
                ORDER BY is_current DESC, created_at DESC
                LIMIT 1
                """
            ),
            {"subject": subject_id},
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="no syllabus for this subject")
    version_id: UUID = row[0]
    return version_id


async def _topic_weights(
    conn: AsyncConnection, subject_id: UUID
) -> tuple[list[dict[str, object]], str]:
    """Every topic in the syllabus, with its exam share when one has been approved.

    Unlike the check-up's own helper this keeps topics that have no questions yet: a topic
    with nothing in it is exactly what a reservation plan needs to show.
    """
    version_id = await _current_version(conn, subject_id)
    rows = await fetch_all(
        conn,
        """
        SELECT topic.id::text AS topic_id, topic.name, w.share
        FROM curriculum_items topic
        LEFT JOIN topic_exam_weight w
          ON w.topic_id = topic.id AND w.syllabus_version_id = topic.syllabus_version_id
        WHERE topic.syllabus_version_id = :version AND topic.item_type = 'topic'
        ORDER BY topic.display_order, topic.code
        """,
        version=version_id,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="this syllabus has no topics")
    weighted = any(row["share"] is not None for row in rows)
    source = (
        "exam_structure"
        if weighted
        else "equal (no approved exam sections yet, so every topic is treated alike)"
    )
    return rows, source


def _wanted_per_topic(rows: list[dict[str, object]], size: int, weighted: bool) -> dict[str, int]:
    """How many questions each topic should contribute, by the engine's own blueprint."""
    weights = [
        TopicWeight(
            topic_id=str(row["topic_id"]),
            share=float(row["share"]) if weighted and row["share"] is not None else 1.0,
            name=str(row["name"]),
        )
        for row in rows
    ]
    counts: dict[str, int] = {weight.topic_id: 0 for weight in weights}
    for slot in build_blueprint(weights, length=max(size, len(weights))):
        counts[slot.topic_id] += 1
    return counts


async def _candidates(conn: AsyncConnection, subject_id: UUID) -> list[dict[str, object]]:
    """Questions that could be reserved, best first within each topic and level.

    Only drafts are offered. Moving an approved question between pools would change what
    students are being served today, which is a different decision from planning a check-up.
    """
    return await fetch_all(
        conn,
        """
        SELECT q.id::text AS question_id, topic.id::text AS topic_id, topic.name AS topic_name,
               coalesce(v.mastery_level_number, 3) AS level,
               row_number() OVER (
                   PARTITION BY topic.id, coalesce(v.mastery_level_number, 3)
                   ORDER BY
                     -- Closest to deliverable first: an answer someone can check, then a
                     -- proposed level, then a worked solution.
                     (v.answer_source <> 'unverified') DESC,
                     (v.mastery_level_number IS NOT NULL) DESC,
                     (jsonb_array_length(v.solution_steps) > 0) DESC,
                     q.exam_year DESC NULLS LAST,
                     q.id
               ) AS rank_in_level
        FROM questions q
        JOIN question_versions v ON v.id = q.current_version_id
        JOIN question_classifications c
          ON c.question_id = q.id AND c.classification_role = 'primary'
        JOIN curriculum_items skill ON skill.id = c.curriculum_item_id
        JOIN curriculum_items sub ON sub.id = skill.parent_id
        JOIN curriculum_items topic ON topic.id = sub.parent_id
        WHERE q.subject_id = :subject
          AND q.usage_pool = :practice
          AND q.retired_at IS NULL
          AND v.review_status = 'draft'
        ORDER BY topic.id, rank_in_level, abs(coalesce(v.mastery_level_number, 3) - 3)
        """,
        subject=subject_id,
        practice=PRACTICE,
    )


def _choose(
    candidates: list[dict[str, object]], wanted: dict[str, int]
) -> dict[str, list[dict[str, object]]]:
    """Fill each topic's quota, taking one level at a time so the ladder has range."""
    by_topic_level: dict[str, dict[int, list[dict[str, object]]]] = {}
    for row in candidates:
        topic = str(row["topic_id"])
        level = int(row["level"])
        by_topic_level.setdefault(topic, {}).setdefault(level, []).append(row)

    chosen: dict[str, list[dict[str, object]]] = {}
    for topic, quota in wanted.items():
        levels = by_topic_level.get(topic, {})
        picked: list[dict[str, object]] = []
        # Round-robin across levels, starting from the middle and working outwards, so a
        # small reservation still spans easy to hard rather than clustering on whatever the
        # bank happens to hold most of.
        order = sorted(levels, key=lambda level: (abs(level - 3), level))
        cursor = {level: 0 for level in order}
        while len(picked) < quota and any(cursor[level] < len(levels[level]) for level in order):
            for level in order:
                if len(picked) >= quota:
                    break
                index = cursor[level]
                if index < len(levels[level]):
                    picked.append(levels[level][index])
                    cursor[level] = index + 1
        chosen[topic] = picked
    return chosen


async def _already_reserved(
    conn: AsyncConnection, subject_id: UUID
) -> dict[str, tuple[int, list[int]]]:
    """What the pool holds per topic: how many, and at which levels.

    The levels matter as much as the count. A topic holding twenty questions that are all
    the same difficulty gives the check-up nothing to climb or descend.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT topic.id::text AS topic_id, count(*) AS reserved,
               array_agg(DISTINCT v.mastery_level_number)
                 FILTER (WHERE v.mastery_level_number IS NOT NULL) AS levels
        FROM questions q
        JOIN question_versions v ON v.id = q.current_version_id
        JOIN question_classifications c
          ON c.question_id = q.id AND c.classification_role = 'primary'
        JOIN curriculum_items skill ON skill.id = c.curriculum_item_id
        JOIN curriculum_items sub ON sub.id = skill.parent_id
        JOIN curriculum_items topic ON topic.id = sub.parent_id
        WHERE q.subject_id = :subject AND q.usage_pool = :pool AND q.retired_at IS NULL
        GROUP BY topic.id
        """,
        subject=subject_id,
        pool=DIAGNOSTIC,
    )
    return {
        str(row["topic_id"]): (int(row["reserved"]), sorted(row["levels"] or []))
        for row in rows
    }


async def _plan(conn: AsyncConnection, subject_id: UUID, size: int) -> ReservePlan:
    rows, source = await _topic_weights(conn, subject_id)
    weighted = source == "exam_structure"
    wanted = _wanted_per_topic(rows, size, weighted)
    candidates = await _candidates(conn, subject_id)
    reserved = await _already_reserved(conn, subject_id)

    available: dict[str, int] = {}
    for row in candidates:
        topic = str(row["topic_id"])
        available[topic] = available.get(topic, 0) + 1

    chosen = _choose(candidates, wanted)
    topics: list[TopicPlan] = []
    for row in rows:
        topic_id = str(row["topic_id"])
        picks = chosen.get(topic_id, [])
        topics.append(
            TopicPlan(
                topic_id=UUID(topic_id),
                topic_name=str(row["name"]),
                share=float(row["share"]) if row["share"] is not None else None,
                wanted=wanted.get(topic_id, 0),
                already_reserved=reserved.get(topic_id, (0, []))[0],
                available_in_practice=available.get(topic_id, 0),
                would_reserve=len(picks),
                levels_covered=sorted({int(pick["level"]) for pick in picks}),
                levels_in_pool=reserved.get(topic_id, (0, []))[1],
            )
        )

    total = sum(topic.would_reserve for topic in topics)
    short = [topic for topic in topics if topic.would_reserve < topic.wanted]
    note = None
    if short:
        names = ", ".join(
            f"{topic.topic_name} ({topic.would_reserve}/{topic.wanted})" for topic in short
        )
        note = (
            "Not enough draft questions to fill every topic: " + names + ". A check-up will "
            "still run, but it will report those topics as unassessed rather than guess at them."
        )
    flat = [
        topic
        for topic in topics
        if (topic.would_reserve > 0 or topic.already_reserved > 0)
        and len(set(topic.levels_covered) | set(topic.levels_in_pool)) < 2
    ]
    level_note = None
    if flat:
        names = ", ".join(topic.topic_name for topic in flat)
        level_note = (
            "Every question reserved for " + names + " sits at one difficulty level, because "
            "these questions carry no verified level yet. A check-up can still run, but it "
            "cannot adapt: it will ask the same difficulty whatever the student answers. "
            "Proposing and checking levels is the work that makes the ladder mean something."
        )
    return ReservePlan(
        subject_id=subject_id,
        size=size,
        weights_source=source,
        topics=topics,
        total_would_reserve=total,
        shortfall_note=note,
        level_spread_note=level_note,
    )


@router.get(
    "/diagnostic/plan",
    response_model=ReservePlan,
    summary="What a reservation would do, without doing it",
)
async def plan(
    conn: Annotated[AsyncConnection, Depends(connection)],
    subject_id: UUID,
    size: Annotated[int, Query(ge=4, le=500)] = DEFAULT_RESERVE,
) -> ReservePlan:
    return await _plan(conn, subject_id, size)


@router.post(
    "/diagnostic/reserve",
    response_model=ReserveResult,
    summary="Set questions aside for check-ups",
)
async def reserve(
    conn: Annotated[AsyncConnection, Depends(connection)], request: ReserveRequest
) -> ReserveResult:
    """Move the planned questions from practice into the diagnostic pool.

    Re-running tops the pool up rather than starting again: questions already reserved stay
    where they are, and only the gap is filled.
    """
    rows, source = await _topic_weights(conn, request.subject_id)
    wanted = _wanted_per_topic(rows, request.size, source == "exam_structure")
    reserved_already = await _already_reserved(conn, request.subject_id)
    # Only the shortfall is taken: a topic already holding its quota is left alone.
    gap = {
        topic: max(0, count - reserved_already.get(topic, (0, []))[0])
        for topic, count in wanted.items()
    }
    chosen = _choose(await _candidates(conn, request.subject_id), gap)

    ids = [str(pick["question_id"]) for picks in chosen.values() for pick in picks]
    moved = 0
    if ids:
        moved = (
            await conn.execute(
                text(
                    """
                    UPDATE questions SET usage_pool = :pool, updated_at = now()
                     WHERE id = ANY(CAST(:ids AS uuid[])) AND usage_pool = :practice
                    """
                ),
                {"pool": DIAGNOSTIC, "practice": PRACTICE, "ids": ids},
            )
        ).rowcount
        await conn.commit()

    after = await _plan(conn, request.subject_id, request.size)
    totals = await fetch_all(
        conn,
        """
        SELECT count(*) AS in_pool,
               count(*) FILTER (WHERE dq.question_id IS NOT NULL) AS deliverable
        FROM questions q
        LEFT JOIN deliverable_questions dq ON dq.question_id = q.id
        WHERE q.subject_id = :subject AND q.usage_pool = :pool AND q.retired_at IS NULL
        """,
        subject=request.subject_id,
        pool=DIAGNOSTIC,
    )
    return ReserveResult(
        subject_id=request.subject_id,
        reserved=moved,
        total_in_pool=int(totals[0]["in_pool"]),
        deliverable_now=int(totals[0]["deliverable"]),
        topics=after.topics,
    )


@router.delete(
    "/diagnostic/reserve",
    response_model=ReserveResult,
    summary="Release reserved questions back to practice",
)
async def release(
    conn: Annotated[AsyncConnection, Depends(connection)],
    subject_id: UUID,
    only_drafts: bool = True,
) -> ReserveResult:
    """Undo a reservation.

    Approved questions are left alone unless explicitly included: moving one out of the pool
    changes what a student sitting a check-up right now would be served.
    """
    condition = "AND v.review_status = 'draft'" if only_drafts else ""
    released = (
        await conn.execute(
            text(
                f"""
                UPDATE questions q SET usage_pool = :practice, updated_at = now()
                FROM question_versions v
                WHERE v.id = q.current_version_id
                  AND q.subject_id = :subject AND q.usage_pool = :pool {condition}
                """
            ),
            {"subject": subject_id, "pool": DIAGNOSTIC, "practice": PRACTICE},
        )
    ).rowcount
    await conn.commit()
    after = await _plan(conn, subject_id, DEFAULT_RESERVE)
    return ReserveResult(
        subject_id=subject_id,
        reserved=-released,
        total_in_pool=sum(topic.already_reserved for topic in after.topics),
        deliverable_now=0,
        topics=after.topics,
    )


@router.get(
    "/diagnostic/readiness",
    response_model=Readiness,
    summary="Whether the pool can actually run a check-up",
)
async def readiness(
    conn: Annotated[AsyncConnection, Depends(connection)], subject_id: UUID
) -> Readiness:
    """What stands between the reserved questions and a student seeing them.

    Each reason is counted separately so the next piece of work is obvious: a hundred
    questions waiting on one licence decision is a different problem from a hundred waiting
    on a hundred answer checks.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT
          count(*) AS in_pool,
          count(*) FILTER (WHERE dq.question_id IS NOT NULL) AS deliverable,
          count(*) FILTER (WHERE v.answer_source NOT IN ('expert_verified', 'official_key'))
            AS unverified_answer,
          count(*) FILTER (WHERE v.level_source NOT IN ('expert_verified', 'calibrated'))
            AS unverified_level,
          count(*) FILTER (WHERE jsonb_array_length(v.solution_steps) = 0) AS no_solution,
          count(*) FILTER (WHERE jsonb_array_length(v.hints) = 0) AS no_hint,
          count(*) FILTER (WHERE c.review_status <> 'approved') AS unapproved_skill,
          count(*) FILTER (WHERE q.origin = 'past_paper'
                             AND (d.licence_status <> 'verified'
                                  OR NOT d.student_delivery_permission)) AS licence_not_cleared,
          count(*) FILTER (WHERE EXISTS (
              SELECT 1 FROM question_assets a
              WHERE a.question_version_id = v.id
                AND (a.licence_status <> 'verified'
                     OR btrim(coalesce(a.alt_text, '')) = ''
                     OR a.alt_text_source <> 'expert_verified'))) AS figure_not_cleared
        FROM questions q
        JOIN question_versions v ON v.id = q.current_version_id
        LEFT JOIN question_classifications c
          ON c.question_id = q.id AND c.classification_role = 'primary'
        LEFT JOIN source_documents d ON d.id = q.source_document_id
        LEFT JOIN deliverable_questions dq ON dq.question_id = q.id
        WHERE q.subject_id = :subject AND q.usage_pool = :pool AND q.retired_at IS NULL
        """,
        subject=subject_id,
        pool=DIAGNOSTIC,
    )
    row = rows[0]
    reasons = [
        ("an answer no person has verified", int(row["unverified_answer"])),
        ("a difficulty level no person has verified", int(row["unverified_level"])),
        ("no worked solution", int(row["no_solution"])),
        ("no hint", int(row["no_hint"])),
        ("a skill mapping still unapproved", int(row["unapproved_skill"])),
        ("a source whose licence is not cleared for delivery", int(row["licence_not_cleared"])),
        ("a figure without a checked description or licence", int(row["figure_not_cleared"])),
    ]
    blocked = [
        BlockedCount(reason=reason, questions=count) for reason, count in reasons if count > 0
    ]
    blocked.sort(key=lambda item: -item.questions)
    return Readiness(
        subject_id=subject_id,
        in_pool=int(row["in_pool"]),
        deliverable=int(row["deliverable"]),
        blocked_by=blocked,
        ready_for_checkup=int(row["deliverable"]) >= 4,
    )
