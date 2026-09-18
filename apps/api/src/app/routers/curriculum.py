"""Read access to the curriculum loaded from an approved syllabus.

Nothing here is student-facing yet: rows carry their review state so callers can
tell a draft import from approved content.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import connection, fetch_all

router = APIRouter(prefix="/v1/curriculum", tags=["curriculum"])

ItemType = Literal["topic", "subtopic", "skill"]


class Subject(BaseModel):
    id: UUID
    code: str
    name: str
    status: str
    examination: str
    exam_body: str
    country_code: str


class CurriculumItem(BaseModel):
    id: UUID
    syllabus_version_id: UUID
    parent_id: UUID | None
    item_type: ItemType
    code: str
    name: str
    syllabus_status: str
    pilot_support_status: str
    review_status: str
    display_order: int


class CurriculumItemPage(BaseModel):
    items: list[CurriculumItem]
    limit: int
    offset: int


@router.get("/subjects", response_model=list[Subject], summary="Subjects by examination")
async def list_subjects(
    conn: Annotated[AsyncConnection, Depends(connection)],
) -> list[Subject]:
    rows = await fetch_all(
        conn,
        """
        SELECT s.id,
               s.code,
               s.name,
               s.status,
               e.short_name AS examination,
               e.exam_body,
               e.country_code
        FROM subjects s
        JOIN examinations e ON e.id = s.examination_id
        ORDER BY e.short_name, s.name
        """,
    )
    return [Subject(**row) for row in rows]


@router.get("/items", response_model=CurriculumItemPage, summary="Curriculum items")
async def list_items(
    conn: Annotated[AsyncConnection, Depends(connection)],
    subject_id: UUID | None = None,
    syllabus_version_id: UUID | None = None,
    item_type: ItemType | None = None,
    parent_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CurriculumItemPage:
    filters = ["TRUE"]
    params: dict[str, object] = {"limit": limit, "offset": offset}

    # Subject codes repeat across examinations — "ENG" is UTME's Use of English and also
    # WAEC's English Language — so a caller filtering by subject really does mean this one
    # subject. Before this filter existed the parameter was accepted and ignored, and the
    # caller got whichever curriculum sorted first.
    if subject_id is not None:
        filters.append("subject_id = :subject_id")
        params["subject_id"] = subject_id
    if syllabus_version_id is not None:
        filters.append("syllabus_version_id = :syllabus_version_id")
        params["syllabus_version_id"] = syllabus_version_id
    if item_type is not None:
        filters.append("item_type = :item_type")
        params["item_type"] = item_type
    if parent_id is not None:
        filters.append("parent_id = :parent_id")
        params["parent_id"] = parent_id

    rows = await fetch_all(
        conn,
        f"""
        SELECT id,
               syllabus_version_id,
               parent_id,
               item_type,
               code,
               name,
               syllabus_status,
               pilot_support_status,
               review_status,
               display_order
        FROM curriculum_items
        WHERE {" AND ".join(filters)}
        ORDER BY display_order, code
        LIMIT :limit OFFSET :offset
        """,
        **params,
    )
    return CurriculumItemPage(
        items=[CurriculumItem(**row) for row in rows], limit=limit, offset=offset
    )
