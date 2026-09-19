"""Endpoints that exist only so the student side can be built and tried.

There is no sign-in yet (ADR-0013 is still proposed), but the check-up cannot run without a
student: an attempt hangs off a student_id, and the database refuses to store one for a
student whose consent is missing. So this creates a real student with a real consent row
rather than faking either. Nothing here bypasses a rule; it fills in the person that a login
screen will eventually supply.

Two things make this safe to keep in the tree:

* It refuses to run unless the settings say this is a development environment, so deploying
  it by accident cannot mint students in production.
* Every student it creates is marked in `external_ref` with a `sandbox:` prefix, so they can
  be told apart from real ones at a glance and cleaned up by that prefix alone.

The fresh-student-per-run habit is deliberate. A first check-up is, by definition, a student
with no history for that subject, and the cheapest honest way back to that state is a new
student — not deleting someone's attempts, which is what the erasure escape hatch is for and
which should stay reserved for a student exercising their rights.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.config import Settings, get_settings
from app.db import connection

router = APIRouter(prefix="/v1/dev", tags=["dev"])

#: Marks every student this router creates, so they are obvious in any query and removable
#: by prefix alone.
SANDBOX_PREFIX = "sandbox:"


class NewStudent(BaseModel):
    display_name: str | None = Field(
        default=None, description="Optional; a readable name is generated when omitted."
    )


class StudentCreated(BaseModel):
    student_id: UUID
    display_name: str
    external_ref: str
    consent_recorded: bool


class SandboxSubject(BaseModel):
    subject_id: UUID
    subject_name: str
    examination: str
    deliverable_questions: int


def _require_dev(settings: Settings) -> None:
    if settings.app_env not in {"local", "ci"}:
        raise HTTPException(
            status_code=404,
            detail="developer endpoints are not available in this environment",
        )


@router.post("/students", response_model=StudentCreated, summary="Create a throwaway student")
async def create_student(
    conn: Annotated[AsyncConnection, Depends(connection)],
    settings: Annotated[Settings, Depends(get_settings)],
    request: NewStudent,
) -> StudentCreated:
    """A student who can sit a check-up, with consent recorded the way the schema expects."""
    _require_dev(settings)

    token = secrets.token_hex(4)
    external_ref = f"{SANDBOX_PREFIX}{token}"
    display_name = request.display_name or f"Sandbox student {token}"

    student_id = (
        await conn.execute(
            text(
                """
                INSERT INTO students (display_name, external_ref, requires_guardian_consent,
                  country_code, timezone, status)
                VALUES (:name, :ref, false, 'NG', 'Africa/Lagos', 'active')
                RETURNING id
                """
            ),
            {"name": display_name, "ref": external_ref},
        )
    ).scalar_one()

    # A real consent row, not an assumption. `in_app` is the honest source: this student
    # agreed to nothing on paper, and the note says exactly what they are.
    await conn.execute(
        text(
            """
            INSERT INTO consents (student_id, consent_type, granted, source, evidence_note)
            VALUES (:student, 'data_processing', true, 'in_app',
                    'Sandbox student created by the developer endpoint; not a real person.')
            """
        ),
        {"student": student_id},
    )
    await conn.commit()

    return StudentCreated(
        student_id=student_id,
        display_name=display_name,
        external_ref=external_ref,
        consent_recorded=True,
    )


@router.get("/subjects", response_model=list[SandboxSubject], summary="Subjects a check-up can use")
async def subjects(
    conn: Annotated[AsyncConnection, Depends(connection)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[SandboxSubject]:
    """Subjects that actually have questions a student may be shown.

    A subject missing from this list is not broken: it means nothing in it has passed review
    and licensing yet, which is the normal state of a new subject.
    """
    _require_dev(settings)
    rows = (
        await conn.execute(
            text(
                """
                SELECT s.id, s.name, e.name AS examination, count(dq.question_id) AS available
                FROM subjects s
                JOIN examinations e ON e.id = s.examination_id
                JOIN deliverable_questions dq ON dq.subject_id = s.id
                JOIN questions q ON q.id = dq.question_id AND q.usage_pool = 'diagnostic'
                GROUP BY s.id, s.name, e.name
                HAVING count(dq.question_id) > 0
                ORDER BY e.name, s.name
                """
            )
        )
    ).mappings()
    return [
        SandboxSubject(
            subject_id=row["id"],
            subject_name=row["name"],
            examination=row["examination"],
            deliverable_questions=row["available"],
        )
        for row in rows
    ]


@router.delete("/students", summary="Remove the students this router created")
async def clear_students(
    conn: Annotated[AsyncConnection, Depends(connection)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, int | str]:
    """Clear away sandbox students once they pile up.

    This is the one place that opens the erasure escape hatch, and only for students whose
    external_ref carries the sandbox prefix. Real students are unreachable from here: the
    WHERE clause cannot match them.
    """
    _require_dev(settings)
    await conn.execute(text("SET LOCAL scorepilot.allow_erasure = 'on'"))
    removed = (
        await conn.execute(
            text(
                """
                WITH doomed AS (
                    SELECT id FROM students WHERE external_ref LIKE :prefix || '%'
                ),
                cleared_turns AS (
                    DELETE FROM tutor_turns WHERE student_id IN (SELECT id FROM doomed)
                ),
                cleared_attempts AS (
                    DELETE FROM attempts WHERE student_id IN (SELECT id FROM doomed)
                ),
                cleared_sessions AS (
                    DELETE FROM study_sessions WHERE student_id IN (SELECT id FROM doomed)
                ),
                cleared_consents AS (
                    DELETE FROM consents WHERE student_id IN (SELECT id FROM doomed)
                )
                DELETE FROM students WHERE id IN (SELECT id FROM doomed)
                RETURNING 1
                """
            ),
            {"prefix": SANDBOX_PREFIX},
        )
    ).rowcount
    await conn.commit()
    return {"removed": removed, "at": datetime.now(UTC).isoformat()}
