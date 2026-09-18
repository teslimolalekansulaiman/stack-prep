"""Content review: verify imported questions before students ever see them.

Everything imported from a past paper arrives proposed, not decided — the answer, the
difficulty level and the skill it tests. This router is how a subject expert turns those
proposals into decisions. The database enforces the rules (an answer nobody verified
cannot be approved); these endpoints just record who decided what.

It is an internal tool. Reviewer identity is chosen from a list rather than authenticated,
so it must stay on a trusted network until ADR-0013 lands.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import connection, fetch_all

router = APIRouter(prefix="/v1/review", tags=["review"])

OptionKey = Literal["A", "B", "C", "D", "E", "F"]
QueueFilter = Literal["needs_review", "needs_answer", "needs_level", "flagged", "ready", "approved"]


class Reviewer(BaseModel):
    id: UUID
    display_name: str


class QueueItem(BaseModel):
    question_id: UUID
    question_version_id: UUID
    exam_year: int | None
    paper_code: str | None
    question_number: str | None
    stem: str
    review_status: str
    answer_checked: bool
    level_checked: bool
    has_approved_skill: bool
    has_solution: bool
    has_hint: bool
    open_reports: int


class Option(BaseModel):
    id: UUID
    option_key: str
    body: str
    is_correct: bool
    display_order: int


class Report(BaseModel):
    id: UUID
    reason: str
    detail: str | None
    status: str


class QuestionDetail(BaseModel):
    question_id: UUID
    question_version_id: UUID
    subject_id: UUID
    syllabus_version_id: UUID | None
    exam_year: int | None
    paper_code: str | None
    question_number: str | None
    instructions: str | None
    stem: str
    passage_title: str | None
    passage_body: str | None
    options: list[Option]
    marks: float | None
    expected_seconds: int | None
    mastery_level_number: int | None
    level_source: str
    level_confidence: str | None
    answer_source: str
    answer_confidence: str | None
    review_status: str
    solution_steps: list[str]
    hints: list[str]
    primary_skill_id: UUID | None
    primary_skill_code: str | None
    primary_skill_name: str | None
    classification_status: str | None
    classification_reason: str | None
    reports: list[Report]


class Progress(BaseModel):
    total: int
    answer_checked: int
    level_checked: int
    skill_approved: int
    ready: int
    approved: int
    flagged: int


class Skill(BaseModel):
    id: UUID
    code: str
    name: str
    topic: str | None


class AnswerDecision(BaseModel):
    reviewer_id: UUID
    option_key: OptionKey


class LevelDecision(BaseModel):
    reviewer_id: UUID
    level: int = Field(ge=1, le=5)


class SkillDecision(BaseModel):
    reviewer_id: UUID
    curriculum_item_id: UUID | None = None
    reason: str | None = None


class ContentEdit(BaseModel):
    reviewer_id: UUID
    solution_steps: list[str] | None = None
    hints: list[str] | None = None


class Approval(BaseModel):
    reviewer_id: UUID


class ReportDecision(BaseModel):
    reviewer_id: UUID
    note: str


class PaperSection(BaseModel):
    """One part of a paper: what it examines and how many questions it asks."""

    section_id: UUID
    paper_code: str
    section_code: str
    name: str
    question_count: int
    marks_total: float | None
    #: What the section examines — a topic when it spans several subtopics, a subtopic or a
    #: skill when the document names one.
    topic_name: str | None
    #: Where in the source this claim came from. A reviewer checks this, not our word.
    source_location: str
    review_status: str


async def _reviewer(conn: AsyncConnection, reviewer_id: UUID) -> None:
    row = await conn.execute(
        text("SELECT 1 FROM academic_reviewers WHERE id = :id AND active"),
        {"id": reviewer_id},
    )
    if row.first() is None:
        raise HTTPException(status_code=400, detail="unknown or inactive reviewer")


async def _draft_version(conn: AsyncConnection, question_id: UUID) -> UUID:
    row = (
        (
            await conn.execute(
                text(
                    """
                SELECT v.id, v.review_status
                FROM questions q JOIN question_versions v ON v.id = q.current_version_id
                WHERE q.id = :id
                """
                ),
                {"id": question_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="question not found")
    if row["review_status"] == "approved":
        raise HTTPException(
            status_code=409,
            detail="this question is approved and frozen; create a new version to change it",
        )
    version_id: UUID = row["id"]
    return version_id


@router.get("/reviewers", response_model=list[Reviewer], summary="Who can review")
async def reviewers(conn: Annotated[AsyncConnection, Depends(connection)]) -> list[Reviewer]:
    rows = await fetch_all(
        conn, "SELECT id, display_name FROM academic_reviewers WHERE active ORDER BY display_name"
    )
    return [Reviewer(**row) for row in rows]


@router.get("/queue", response_model=list[QueueItem], summary="Questions waiting on a decision")
async def queue(
    conn: Annotated[AsyncConnection, Depends(connection)],
    state: QueueFilter = "needs_review",
    exam_year: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[QueueItem]:
    conditions = {
        "needs_review": "(NOT r.answer_checked OR NOT r.level_checked OR NOT r.has_approved_skill)",
        "needs_answer": "NOT r.answer_checked",
        "needs_level": "NOT r.level_checked",
        "flagged": "reports.open_reports > 0",
        "ready": (
            "r.answer_checked AND r.level_checked AND r.has_approved_skill"
            " AND r.review_status = 'draft'"
        ),
        "approved": "r.review_status = 'approved'",
    }
    year_filter = "AND r.exam_year = :exam_year" if exam_year is not None else ""
    rows = await fetch_all(
        conn,
        f"""
        SELECT r.question_id, r.question_version_id, r.exam_year, r.paper_code,
               r.question_number, v.stem, r.review_status, r.answer_checked, r.level_checked,
               r.has_approved_skill, r.has_solution, r.has_hint,
               coalesce(reports.open_reports, 0) AS open_reports
        FROM question_readiness r
        JOIN question_versions v ON v.id = r.question_version_id
        LEFT JOIN LATERAL (
          SELECT count(*) AS open_reports FROM question_reports rep
          WHERE rep.question_version_id = r.question_version_id
            AND rep.status IN ('open', 'triaged')
        ) reports ON TRUE
        WHERE {conditions[state]} {year_filter}
        ORDER BY r.exam_year, length(r.question_number), r.question_number
        LIMIT :limit OFFSET :offset
        """,
        limit=limit,
        offset=offset,
        **({"exam_year": exam_year} if exam_year is not None else {}),
    )
    return [QueueItem(**row) for row in rows]


@router.get("/progress", response_model=Progress, summary="How much of the bank is decided")
async def progress(
    conn: Annotated[AsyncConnection, Depends(connection)],
    exam_year: int | None = None,
) -> Progress:
    rows = await fetch_all(
        conn,
        f"""
        SELECT count(*) AS total,
               count(*) FILTER (WHERE answer_checked) AS answer_checked,
               count(*) FILTER (WHERE level_checked) AS level_checked,
               count(*) FILTER (WHERE has_approved_skill) AS skill_approved,
               count(*) FILTER (WHERE answer_checked AND level_checked AND has_approved_skill
                                 AND review_status = 'draft') AS ready,
               count(*) FILTER (WHERE review_status = 'approved') AS approved,
               count(*) FILTER (WHERE EXISTS (
                 SELECT 1 FROM question_reports rep
                 WHERE rep.question_version_id = question_readiness.question_version_id
                   AND rep.status IN ('open', 'triaged'))) AS flagged
        FROM question_readiness
        {"WHERE exam_year = :exam_year" if exam_year is not None else ""}
        """,
        **({"exam_year": exam_year} if exam_year is not None else {}),
    )
    return Progress(**rows[0])


@router.get("/skills", response_model=list[Skill], summary="Skills available for classification")
async def skills(
    conn: Annotated[AsyncConnection, Depends(connection)],
    syllabus_version_id: UUID,
) -> list[Skill]:
    rows = await fetch_all(
        conn,
        """
        SELECT s.id, s.code, s.name, topic.name AS topic
        FROM curriculum_items s
        LEFT JOIN curriculum_items sub ON sub.id = s.parent_id
        LEFT JOIN curriculum_items topic ON topic.id = sub.parent_id
        WHERE s.syllabus_version_id = :version AND s.item_type = 'skill'
        ORDER BY s.display_order, s.code
        """,
        version=syllabus_version_id,
    )
    return [Skill(**row) for row in rows]


@router.get(
    "/questions/{question_id}", response_model=QuestionDetail, summary="One question in full"
)
async def question_detail(
    conn: Annotated[AsyncConnection, Depends(connection)], question_id: UUID
) -> QuestionDetail:
    rows = await fetch_all(
        conn,
        """
        SELECT q.id AS question_id, v.id AS question_version_id, q.subject_id,
               c.syllabus_version_id, q.exam_year, q.paper_code, q.question_number,
               v.instructions, v.stem, p.title AS passage_title, p.body AS passage_body,
               v.marks, v.expected_seconds, v.mastery_level_number, v.level_source,
               v.level_confidence, v.answer_source, v.answer_confidence, v.review_status,
               -- as text arrays, so the client gets lists rather than raw JSON
               ARRAY(SELECT jsonb_array_elements_text(v.solution_steps)) AS solution_steps,
               ARRAY(SELECT jsonb_array_elements_text(v.hints)) AS hints,
               c.curriculum_item_id AS primary_skill_id, ci.code AS primary_skill_code,
               ci.name AS primary_skill_name, c.review_status AS classification_status,
               c.classification_reason
        FROM questions q
        JOIN question_versions v ON v.id = q.current_version_id
        LEFT JOIN passages p ON p.id = v.passage_id
        LEFT JOIN question_classifications c
          ON c.question_id = q.id AND c.classification_role = 'primary'
        LEFT JOIN curriculum_items ci ON ci.id = c.curriculum_item_id
        WHERE q.id = :id
        """,
        id=question_id,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="question not found")
    detail = rows[0]

    options = await fetch_all(
        conn,
        """
        SELECT id, option_key, body, is_correct, display_order
        FROM question_options WHERE question_version_id = :version
        ORDER BY display_order, option_key
        """,
        version=detail["question_version_id"],
    )
    reports = await fetch_all(
        conn,
        """
        SELECT id, reason, detail, status FROM question_reports
        WHERE question_version_id = :version AND status IN ('open', 'triaged')
        ORDER BY created_at
        """,
        version=detail["question_version_id"],
    )
    return QuestionDetail(
        **detail,
        options=[Option(**row) for row in options],
        reports=[Report(**row) for row in reports],
    )


@router.post(
    "/questions/{question_id}/answer", response_model=QuestionDetail, summary="Verify the answer"
)
async def verify_answer(
    conn: Annotated[AsyncConnection, Depends(connection)],
    question_id: UUID,
    decision: AnswerDecision,
) -> QuestionDetail:
    await _reviewer(conn, decision.reviewer_id)
    version_id = await _draft_version(conn, question_id)

    exists = await conn.execute(
        text("SELECT 1 FROM question_options WHERE question_version_id = :v AND option_key = :k"),
        {"v": version_id, "k": decision.option_key},
    )
    if exists.first() is None:
        raise HTTPException(
            status_code=400, detail=f"this question has no option {decision.option_key}"
        )

    # Two statements, so the single-correct-answer index is never briefly violated.
    await conn.execute(
        text("UPDATE question_options SET is_correct = false WHERE question_version_id = :v"),
        {"v": version_id},
    )
    await conn.execute(
        text(
            """
            UPDATE question_options SET is_correct = true
            WHERE question_version_id = :v AND option_key = :k
            """
        ),
        {"v": version_id, "k": decision.option_key},
    )
    await conn.execute(
        text(
            """
            UPDATE question_versions
            SET answer_source = 'expert_verified', reviewed_by = :reviewer, reviewed_at = now()
            WHERE id = :v
            """
        ),
        {"v": version_id, "reviewer": decision.reviewer_id},
    )
    await conn.commit()
    return await question_detail(conn, question_id)


@router.post(
    "/questions/{question_id}/level",
    response_model=QuestionDetail,
    summary="Verify the difficulty level",
)
async def verify_level(
    conn: Annotated[AsyncConnection, Depends(connection)],
    question_id: UUID,
    decision: LevelDecision,
) -> QuestionDetail:
    await _reviewer(conn, decision.reviewer_id)
    version_id = await _draft_version(conn, question_id)
    await conn.execute(
        text(
            """
            UPDATE question_versions
            SET mastery_level_number = :level, level_source = 'expert_verified',
                reviewed_by = :reviewer, reviewed_at = now()
            WHERE id = :v
            """
        ),
        {"v": version_id, "level": decision.level, "reviewer": decision.reviewer_id},
    )
    await conn.commit()
    return await question_detail(conn, question_id)


@router.post(
    "/questions/{question_id}/skill",
    response_model=QuestionDetail,
    summary="Approve or change the skill",
)
async def decide_skill(
    conn: Annotated[AsyncConnection, Depends(connection)],
    question_id: UUID,
    decision: SkillDecision,
) -> QuestionDetail:
    await _reviewer(conn, decision.reviewer_id)
    await _draft_version(conn, question_id)

    existing = (
        (
            await conn.execute(
                text(
                    """
                SELECT id, curriculum_item_id FROM question_classifications
                WHERE question_id = :q AND classification_role = 'primary'
                """
                ),
                {"q": question_id},
            )
        )
        .mappings()
        .first()
    )
    if existing is None:
        raise HTTPException(status_code=404, detail="this question has no primary classification")

    changed = (
        decision.curriculum_item_id is not None
        and decision.curriculum_item_id != existing["curriculum_item_id"]
    )
    try:
        if changed:
            await conn.execute(
                text(
                    """
                    UPDATE question_classifications
                    SET curriculum_item_id = :skill, proposed_by = 'human', confidence = NULL,
                        classification_reason = :reason
                    WHERE id = :id
                    """
                ),
                {
                    "id": existing["id"],
                    "skill": decision.curriculum_item_id,
                    "reason": decision.reason or "Reassigned during review.",
                },
            )
        await conn.execute(
            text(
                """
                UPDATE question_classifications
                SET review_status = 'approved', reviewed_by = :reviewer, reviewed_at = now()
                WHERE id = :id
                """
            ),
            {"id": existing["id"], "reviewer": decision.reviewer_id},
        )
        await conn.commit()
    except DBAPIError as error:  # a skill from the wrong version or a non-skill item
        await conn.rollback()
        raise HTTPException(status_code=400, detail=_message(error)) from error
    return await question_detail(conn, question_id)


@router.post(
    "/questions/{question_id}/content",
    response_model=QuestionDetail,
    summary="Add a solution and hints",
)
async def edit_content(
    conn: Annotated[AsyncConnection, Depends(connection)],
    question_id: UUID,
    edit: ContentEdit,
) -> QuestionDetail:
    await _reviewer(conn, edit.reviewer_id)
    version_id = await _draft_version(conn, question_id)
    if edit.solution_steps is not None:
        await conn.execute(
            text(
                "UPDATE question_versions SET solution_steps = CAST(:steps AS jsonb) WHERE id = :v"
            ),
            {"v": version_id, "steps": _json(edit.solution_steps)},
        )
    if edit.hints is not None:
        await conn.execute(
            text("UPDATE question_versions SET hints = CAST(:hints AS jsonb) WHERE id = :v"),
            {"v": version_id, "hints": _json(edit.hints)},
        )
    await conn.commit()
    return await question_detail(conn, question_id)


@router.post(
    "/questions/{question_id}/approve",
    response_model=QuestionDetail,
    summary="Approve the question",
)
async def approve(
    conn: Annotated[AsyncConnection, Depends(connection)],
    question_id: UUID,
    approval: Approval,
) -> QuestionDetail:
    await _reviewer(conn, approval.reviewer_id)
    version_id = await _draft_version(conn, question_id)
    try:
        await conn.execute(
            text(
                """
                UPDATE question_versions
                SET review_status = 'approved', reviewed_by = :reviewer, reviewed_at = now()
                WHERE id = :v
                """
            ),
            {"v": version_id, "reviewer": approval.reviewer_id},
        )
        await conn.commit()
    except DBAPIError as error:
        # The database states exactly what is still missing; pass that through unchanged.
        await conn.rollback()
        raise HTTPException(status_code=409, detail=_message(error)) from error
    return await question_detail(conn, question_id)


@router.post("/reports/{report_id}/resolve", summary="Close a problem report")
async def resolve_report(
    conn: Annotated[AsyncConnection, Depends(connection)],
    report_id: UUID,
    decision: ReportDecision,
) -> dict[str, str]:
    await _reviewer(conn, decision.reviewer_id)
    result = await conn.execute(
        text(
            """
            UPDATE question_reports
            SET status = 'fixed', resolved_by = :reviewer, resolved_at = now(),
                resolution_note = :note
            WHERE id = :id AND status IN ('open', 'triaged')
            """
        ),
        {"id": report_id, "reviewer": decision.reviewer_id, "note": decision.note},
    )
    await conn.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="no open report with that id")
    return {"status": "resolved"}


def _json(values: list[str]) -> str:
    return json.dumps([value for value in values if value.strip()])


def _message(error: DBAPIError) -> str:
    """The useful half of a database error: the message, not the statement."""
    original = getattr(error, "orig", None)
    # asyncpg errors carry the server's message in args[0]; str() prefixes the class name.
    if original is not None and getattr(original, "args", None):
        return str(original.args[0]).split("\n")[0].strip()
    return str(error).split("\n")[0].strip()


@router.get(
    "/sections", response_model=list[PaperSection], summary="Paper sections awaiting a decision"
)
async def sections(
    conn: Annotated[AsyncConnection, Depends(connection)],
    subject_id: UUID | None = None,
    state: Literal["pending", "approved", "all"] = "pending",
) -> list[PaperSection]:
    """What each paper examines, as read from the syllabus and waiting to be confirmed.

    These rows decide how much every topic is worth, so nothing downstream uses them until a
    person agrees with the reading: `topic_exam_weight` counts approved sections only. Each
    row carries the line of the document it came from, because that is what makes the
    decision checkable rather than a matter of trust.
    """
    conditions = ["1 = 1"]
    params: dict[str, object] = {}
    if state != "all":
        conditions.append("s.review_status = :state")
        params["state"] = state
    if subject_id is not None:
        conditions.append("s.subject_id = :subject")
        params["subject"] = subject_id

    rows = await fetch_all(
        conn,
        f"""
        SELECT s.id AS section_id, p.paper_code, s.section_code, s.name, s.question_count,
               s.marks_total, topic.name AS topic_name, s.source_location, s.review_status
        FROM exam_paper_sections s
        JOIN exam_papers p ON p.id = s.exam_paper_id
        LEFT JOIN curriculum_items topic ON topic.id = s.curriculum_item_id
        WHERE {" AND ".join(conditions)}
        ORDER BY p.paper_code, s.section_code
        """,
        **params,
    )
    return [
        PaperSection(
            section_id=row["section_id"],
            paper_code=row["paper_code"],
            section_code=row["section_code"],
            name=row["name"],
            question_count=row["question_count"],
            marks_total=float(row["marks_total"]) if row["marks_total"] is not None else None,
            topic_name=row["topic_name"],
            source_location=row["source_location"],
            review_status=row["review_status"],
        )
        for row in rows
    ]


@router.post(
    "/sections/{section_id}/approve",
    response_model=PaperSection,
    summary="Agree that a section reads as recorded",
)
async def approve_section(
    conn: Annotated[AsyncConnection, Depends(connection)],
    section_id: UUID,
    decision: Approval,
) -> PaperSection:
    """Approve one section, which lets it count towards its topic's weight.

    Approving every section of a paper at once is deliberately not offered: each carries its
    own citation, and the point of the citation is that someone read it.
    """
    await _reviewer(conn, decision.reviewer_id)
    updated = (
        await conn.execute(
            text(
                """
                UPDATE exam_paper_sections
                   SET review_status = 'approved', reviewed_by = :reviewer, reviewed_at = now()
                 WHERE id = :id AND review_status <> 'approved'
                RETURNING id
                """
            ),
            {"id": section_id, "reviewer": decision.reviewer_id},
        )
    ).first()
    if updated is None:
        existing = (
            await conn.execute(
                text("SELECT review_status FROM exam_paper_sections WHERE id = :id"),
                {"id": section_id},
            )
        ).first()
        if existing is None:
            raise HTTPException(status_code=404, detail="section not found")
        raise HTTPException(status_code=409, detail="this section is already approved")
    await conn.commit()

    found = await sections(conn, subject_id=None, state="all")
    for section in found:
        if section.section_id == section_id:
            return section
    raise HTTPException(status_code=404, detail="section not found")
