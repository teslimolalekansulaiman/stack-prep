"""Deciding what may be published at all: documents, syllabus, catalogue.

The review router decides about *questions* — is this the right answer, the right skill, the
right level. This one decides the things that sit above every question and gate all of them
at once. A question cannot reach a student if the paper it came from is not licensed for
delivery, if the skill it teaches comes from an unapproved syllabus, or if the subject itself
is still a draft in the catalogue.

Those are few decisions with wide consequences, which is the opposite shape from question
review, and why they are not mixed in with it. Each endpoint here records who decided and
when; the database's own constraints decide whether the decision is allowed. The one rule
worth naming: a permission cannot be granted unless the licence is verified, so
`licence_status` and the three permissions are set in a single statement rather than in a
sequence that would be briefly illegal.

Like the review router this is an internal tool, with reviewer identity chosen from a list
rather than authenticated. It must stay on a trusted network until ADR-0013 lands.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import connection, fetch_all

router = APIRouter(prefix="/v1/publishing", tags=["publishing"])

#: What a syllabus item's status may become once a person has read it against the document.
#: 'uncertain' is the import default and is deliberately not offered here: approving an item
#: means saying where it stands, and "I am not sure" is not an approval.
SyllabusStatus = Literal["explicit", "implied", "prerequisite_only", "excluded", "retired"]
SupportStatus = Literal["supported", "planned", "unsupported", "undecided"]


class Decision(BaseModel):
    reviewer_id: UUID


class LicenceDecision(Decision):
    """What we may do with a document, and the permissions that follow from it."""

    licence_status: Literal["verified", "blocked", "pending"]
    #: Keeping a copy of the source file.
    storage_permission: bool = False
    #: Showing its content to a student. The permission the delivery gates read.
    student_delivery_permission: bool = False
    #: Sending its content to a model.
    model_context_permission: bool = False


class Document(BaseModel):
    document_id: UUID
    document_type: str
    title: str
    subject_code: str | None
    examination: str
    file_uri: str
    licence_status: str
    storage_permission: bool
    student_delivery_permission: bool
    model_context_permission: bool
    review_status: str
    #: What is waiting on this decision, so its weight is visible before it is made.
    questions: int
    curriculum_items: int


class CurriculumDecision(Decision):
    syllabus_status: SyllabusStatus
    pilot_support_status: SupportStatus = "supported"


class CurriculumItem(BaseModel):
    curriculum_item_id: UUID
    code: str
    name: str
    item_type: str
    parent_code: str | None
    syllabus_status: str
    pilot_support_status: str
    review_status: str
    #: An item cannot be approved without evidence, so the count is shown before the decision.
    evidence: int
    approved_evidence: int


class Catalogue(BaseModel):
    """Whether a subject is switched on, and what that depends on."""

    subject_id: UUID
    subject_code: str
    subject_name: str
    subject_status: str
    examination: str
    examination_status: str
    teachable_skills: int
    deliverable_questions: int


async def _reviewer(conn: AsyncConnection, reviewer_id: UUID) -> None:
    row = await conn.execute(
        text("SELECT 1 FROM academic_reviewers WHERE id = :id AND active"),
        {"id": reviewer_id},
    )
    if row.first() is None:
        raise HTTPException(status_code=400, detail="unknown or inactive reviewer")


def _message(error: DBAPIError) -> str:
    """The useful half of a database error: the message, not the statement."""
    original = getattr(error, "orig", None)
    if original is not None and getattr(original, "args", None):
        return str(original.args[0]).split("\n")[0].strip()
    return str(error).split("\n")[0].strip()


@router.get("/documents", response_model=list[Document], summary="Documents and their licences")
async def documents(
    conn: Annotated[AsyncConnection, Depends(connection)],
    subject_id: UUID | None = None,
) -> list[Document]:
    """Every source document, with what rests on it.

    The two counts are the point of this list. A licence decision on a syllabus PDF does not
    look important until you see that eighty-six skills cannot be taught without it.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT d.id AS document_id, d.document_type, d.title, s.code AS subject_code,
               e.short_name AS examination, d.file_uri, d.licence_status,
               d.storage_permission, d.student_delivery_permission, d.model_context_permission,
               d.review_status,
               (SELECT count(*) FROM questions q WHERE q.source_document_id = d.id) AS questions,
               (SELECT count(*) FROM curriculum_items ci
                  JOIN syllabus_versions v ON v.id = ci.syllabus_version_id
                 WHERE v.source_document_id = d.id) AS curriculum_items
        FROM source_documents d
        JOIN examinations e ON e.id = d.examination_id
        LEFT JOIN subjects s ON s.id = d.subject_id
        WHERE (CAST(:subject AS uuid) IS NULL OR d.subject_id = :subject)
        ORDER BY e.short_name, d.document_type, d.title
        """,
        subject=subject_id,
    )
    return [Document(**dict(row)) for row in rows]


@router.post(
    "/documents/{document_id}/licence",
    response_model=Document,
    summary="Record what may be done with a document",
)
async def decide_licence(
    conn: Annotated[AsyncConnection, Depends(connection)],
    document_id: UUID,
    decision: LicenceDecision,
) -> Document:
    """Set a document's licence and the permissions that follow from it.

    The permissions and the licence move together in one statement: the schema forbids a
    granted permission on an unverified licence, so setting them one after the other would
    fail on whichever half landed first.

    Approving a document is not a claim about copyright law. It records that a named person
    decided, on a date, that we may use this document this way — which is what an audit needs
    and what a later reviewer can revisit. Withdrawing is the same call with the permissions
    set false, and it takes effect immediately: every delivery gate reads the live row.
    """
    await _reviewer(conn, decision.reviewer_id)
    approved = decision.licence_status == "verified"
    try:
        updated = (
            await conn.execute(
                text(
                    """
                    UPDATE source_documents
                       SET licence_status = :licence,
                           storage_permission = :storage,
                           student_delivery_permission = :delivery,
                           model_context_permission = :model,
                           review_status = CASE WHEN :approved THEN 'approved'
                                               ELSE review_status END,
                           reviewed_by = :reviewer, reviewed_at = now()
                     WHERE id = :id
                    RETURNING id
                    """
                ),
                {
                    "id": document_id,
                    "licence": decision.licence_status,
                    "storage": decision.storage_permission,
                    "delivery": decision.student_delivery_permission,
                    "model": decision.model_context_permission,
                    "approved": approved,
                    "reviewer": decision.reviewer_id,
                },
            )
        ).first()
        if updated is None:
            raise HTTPException(status_code=404, detail="document not found")
        await conn.commit()
    except DBAPIError as error:
        await conn.rollback()
        raise HTTPException(status_code=409, detail=_message(error)) from error

    for document in await documents(conn, subject_id=None):
        if document.document_id == document_id:
            return document
    raise HTTPException(status_code=404, detail="document not found")


@router.get(
    "/curriculum", response_model=list[CurriculumItem], summary="Syllabus items and their state"
)
async def curriculum(
    conn: Annotated[AsyncConnection, Depends(connection)],
    subject_id: UUID,
    state: Literal["draft", "approved", "all"] = "draft",
) -> list[CurriculumItem]:
    """The syllabus as imported, in reading order, with its evidence counted."""
    rows = await fetch_all(
        conn,
        """
        SELECT ci.id AS curriculum_item_id, ci.code, ci.name, ci.item_type,
               parent.code AS parent_code, ci.syllabus_status, ci.pilot_support_status,
               ci.review_status,
               (SELECT count(*) FROM curriculum_evidence ev
                 WHERE ev.curriculum_item_id = ci.id) AS evidence,
               (SELECT count(*) FROM curriculum_evidence ev
                 WHERE ev.curriculum_item_id = ci.id
                   AND ev.review_status = 'approved') AS approved_evidence
        FROM curriculum_items ci
        JOIN syllabus_versions v ON v.id = ci.syllabus_version_id
        LEFT JOIN curriculum_items parent ON parent.id = ci.parent_id
        WHERE v.subject_id = :subject
          AND (:state = 'all' OR ci.review_status = :state)
        ORDER BY ci.code
        """,
        subject=subject_id,
        state=state,
    )
    return [CurriculumItem(**dict(row)) for row in rows]


@router.post(
    "/curriculum/{item_id}/approve",
    response_model=CurriculumItem,
    summary="Approve one syllabus item",
)
async def approve_item(
    conn: Annotated[AsyncConnection, Depends(connection)],
    item_id: UUID,
    decision: CurriculumDecision,
) -> CurriculumItem:
    """Approve a topic, subtopic or skill, saying where it stands and whether we support it.

    Two things are decided at once because the database will not let them disagree: an item
    that is excluded, retired or uncertain cannot also be supported for teaching. Items
    import as 'uncertain', which is why the status must be stated here rather than defaulted
    — the import knows what the document printed, not what it means.

    Order matters, and the database enforces it: a child cannot be approved before its
    parent. Approve topics, then subtopics, then skills.
    """
    await _reviewer(conn, decision.reviewer_id)
    try:
        updated = (
            await conn.execute(
                text(
                    """
                    UPDATE curriculum_items
                       SET syllabus_status = :syllabus_status,
                           pilot_support_status = :support,
                           review_status = 'approved',
                           approved_by = :reviewer, approved_at = now(), updated_at = now()
                     WHERE id = :id
                    RETURNING id
                    """
                ),
                {
                    "id": item_id,
                    "syllabus_status": decision.syllabus_status,
                    "support": decision.pilot_support_status,
                    "reviewer": decision.reviewer_id,
                },
            )
        ).first()
        if updated is None:
            raise HTTPException(status_code=404, detail="curriculum item not found")
        await conn.commit()
    except DBAPIError as error:
        await conn.rollback()
        raise HTTPException(status_code=409, detail=_message(error)) from error

    subject = (
        await conn.execute(
            text("SELECT subject_id FROM curriculum_items WHERE id = :id"), {"id": item_id}
        )
    ).scalar_one()
    for item in await curriculum(conn, subject_id=subject, state="all"):
        if item.curriculum_item_id == item_id:
            return item
    raise HTTPException(status_code=404, detail="curriculum item not found")


class Evidence(BaseModel):
    evidence_id: UUID
    curriculum_item_id: UUID
    item_code: str
    evidence_kind: str
    source_location: str | None
    source_excerpt: str | None
    decision_rationale: str | None
    review_status: str


@router.get("/evidence", response_model=list[Evidence], summary="Citations awaiting a decision")
async def evidence(
    conn: Annotated[AsyncConnection, Depends(connection)],
    subject_id: UUID,
    state: Literal["pending", "approved", "all"] = "pending",
) -> list[Evidence]:
    """The lines of the document each syllabus item was read from.

    An item cannot be approved without at least one approved citation, so this is the step
    before that one: the reviewer reads the excerpt against the page it names and says
    whether it is really there.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT ev.id AS evidence_id, ev.curriculum_item_id, ci.code AS item_code,
               ev.evidence_kind, ev.source_location, ev.source_excerpt,
               ev.decision_rationale, ev.review_status
        FROM curriculum_evidence ev
        JOIN curriculum_items ci ON ci.id = ev.curriculum_item_id
        WHERE ci.subject_id = :subject
          AND (:state = 'all' OR ev.review_status = :state)
        ORDER BY ci.code, ev.created_at
        """,
        subject=subject_id,
        state=state,
    )
    return [Evidence(**dict(row)) for row in rows]


@router.post(
    "/evidence/{evidence_id}/approve",
    response_model=Evidence,
    summary="Agree that a citation says what we recorded",
)
async def approve_evidence(
    conn: Annotated[AsyncConnection, Depends(connection)],
    evidence_id: UUID,
    decision: Decision,
) -> Evidence:
    """Approve one citation.

    This is refused while the document it cites is unlicensed, which is the right order:
    there is no point agreeing that a line appears on page 3 of something we have not
    decided we may use.
    """
    await _reviewer(conn, decision.reviewer_id)
    try:
        updated = (
            await conn.execute(
                text(
                    """
                    UPDATE curriculum_evidence
                       SET review_status = 'approved',
                           reviewed_by = :reviewer, reviewed_at = now()
                     WHERE id = :id
                    RETURNING curriculum_item_id
                    """
                ),
                {"id": evidence_id, "reviewer": decision.reviewer_id},
            )
        ).first()
        if updated is None:
            raise HTTPException(status_code=404, detail="evidence not found")
        await conn.commit()
    except DBAPIError as error:
        await conn.rollback()
        raise HTTPException(status_code=409, detail=_message(error)) from error

    subject = (
        await conn.execute(
            text("SELECT subject_id FROM curriculum_items WHERE id = :id"), {"id": updated[0]}
        )
    ).scalar_one()
    for row in await evidence(conn, subject_id=subject, state="all"):
        if row.evidence_id == evidence_id:
            return row
    raise HTTPException(status_code=404, detail="evidence not found")


@router.post(
    "/syllabus-versions/{version_id}/publish",
    response_model=Catalogue,
    summary="Make a syllabus version the current one",
)
async def publish_version(
    conn: Annotated[AsyncConnection, Depends(connection)],
    version_id: UUID,
    decision: Decision,
) -> Catalogue:
    """Approve a syllabus version and make it the subject's current one.

    A subject has exactly one current version, so publishing this one demotes whatever held
    the place before. That is the whole point of the flag: when next year's syllabus is
    loaded, questions classified against this year's stop being teachable the moment the new
    one is published, without anything being deleted.
    """
    await _reviewer(conn, decision.reviewer_id)
    subject_id = (
        await conn.execute(
            text("SELECT subject_id FROM syllabus_versions WHERE id = :id"), {"id": version_id}
        )
    ).scalar()
    if subject_id is None:
        raise HTTPException(status_code=404, detail="syllabus version not found")
    try:
        await conn.execute(
            text(
                """
                UPDATE syllabus_versions SET is_current = false
                 WHERE subject_id = :subject AND id <> :id AND is_current
                """
            ),
            {"subject": subject_id, "id": version_id},
        )
        await conn.execute(
            text(
                """
                UPDATE syllabus_versions
                   SET status = 'approved', is_current = true,
                       approved_by = :reviewer, approved_at = now()
                 WHERE id = :id
                """
            ),
            {"id": version_id, "reviewer": decision.reviewer_id},
        )
        await conn.commit()
    except DBAPIError as error:
        await conn.rollback()
        raise HTTPException(status_code=409, detail=_message(error)) from error
    return await catalogue(conn, subject_id=subject_id)


@router.get("/catalogue", response_model=Catalogue, summary="Is this subject switched on")
async def catalogue(
    conn: Annotated[AsyncConnection, Depends(connection)], subject_id: UUID
) -> Catalogue:
    """The subject's own status, and the two numbers that say whether it is really ready.

    A subject can be 'active' and still teach nothing: the counts are what matter, and they
    are read from the same views the student side reads, not from a summary of them.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT s.id AS subject_id, s.code AS subject_code, s.name AS subject_name,
               s.status AS subject_status, e.short_name AS examination,
               e.status AS examination_status,
               (SELECT count(*) FROM teachable_skills t WHERE t.subject_id = s.id)
                 AS teachable_skills,
               (SELECT count(*) FROM deliverable_questions d WHERE d.subject_id = s.id)
                 AS deliverable_questions
        FROM subjects s JOIN examinations e ON e.id = s.examination_id
        WHERE s.id = :subject
        """,
        subject=subject_id,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="subject not found")
    return Catalogue(**dict(rows[0]))


class Activation(Decision):
    #: An examination is shared by its subjects, so activating one is stated rather than
    #: implied. Leaving this false on a draft examination will simply not switch it on, and
    #: the subject will stay dark however active it is itself.
    activate_examination: bool = Field(default=False)


@router.post(
    "/subjects/{subject_id}/activate",
    response_model=Catalogue,
    summary="Switch a subject on",
)
async def activate_subject(
    conn: Annotated[AsyncConnection, Depends(connection)],
    subject_id: UUID,
    decision: Activation,
) -> Catalogue:
    """Move a subject out of draft, and optionally its examination with it.

    This is the catalogue's own switch and it grants nothing: a subject can be active while
    every one of its questions is still blocked. It is listed here because a draft subject
    silently empties `published_curriculum_scope`, which is a confusing way to find out that
    the catalogue is the thing standing in the way.
    """
    await _reviewer(conn, decision.reviewer_id)
    updated = (
        await conn.execute(
            text("UPDATE subjects SET status = 'active' WHERE id = :id RETURNING examination_id"),
            {"id": subject_id},
        )
    ).first()
    if updated is None:
        raise HTTPException(status_code=404, detail="subject not found")
    if decision.activate_examination:
        await conn.execute(
            text("UPDATE examinations SET status = 'active', updated_at = now() WHERE id = :id"),
            {"id": updated[0]},
        )
    await conn.commit()
    return await catalogue(conn, subject_id=subject_id)
