"""Publishing decisions, against the local database.

The fixture is a subject in the state a freshly imported one is really in: nothing licensed,
nothing approved, the catalogue still in draft. The tests walk it forward one decision at a
time, because the order is the interesting part — each endpoint is useless until the one
before it has been called, and that is the behaviour worth protecting.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import text

from app.db import database_is_reachable, get_engine
from app.main import app

pytestmark = pytest.mark.integration


@pytest.fixture
async def draft_subject() -> AsyncIterator[dict[str, str]]:
    """A subject exactly as an import leaves it: draft everywhere, licence pending."""
    if not await database_is_reachable():
        pytest.skip("database unreachable — run `make db-start && make migrate`")

    engine = get_engine()
    suffix = uuid.uuid4().hex[:8]
    ids: dict[str, str] = {}
    async with engine.begin() as conn:
        ids["reviewer"] = str(
            (
                await conn.execute(
                    text("INSERT INTO academic_reviewers (display_name) VALUES (:n) RETURNING id"),
                    {"n": f"Publishing test reviewer {suffix}"},
                )
            ).scalar_one()
        )
        ids["exam"] = str(
            (
                await conn.execute(
                    text(
                        """
                        INSERT INTO examinations (name, short_name, exam_body, country_code,
                          status)
                        VALUES (:n, :s, 'Test body', 'NG', 'draft') RETURNING id
                        """
                    ),
                    {"n": f"Publishing test exam {suffix}", "s": f"PB{suffix[:5]}"},
                )
            ).scalar_one()
        )
        ids["subject"] = str(
            (
                await conn.execute(
                    text(
                        """
                        INSERT INTO subjects (examination_id, code, name, status)
                        VALUES (CAST(:e AS uuid), 'PUB', 'Publishing test subject', 'draft')
                        RETURNING id
                        """
                    ),
                    {"e": ids["exam"]},
                )
            ).scalar_one()
        )
        ids["document"] = str(
            (
                await conn.execute(
                    text(
                        """
                        INSERT INTO source_documents (examination_id, subject_id, document_type,
                          title, file_uri, file_sha256, mime_type)
                        VALUES (CAST(:e AS uuid), CAST(:s AS uuid), 'syllabus', :t, :u, :h,
                          'application/pdf')
                        RETURNING id
                        """
                    ),
                    {
                        "e": ids["exam"],
                        "s": ids["subject"],
                        "t": f"Publishing test syllabus {suffix}",
                        "u": f"test://publishing/{suffix}",
                        "h": uuid.uuid4().hex + uuid.uuid4().hex,
                    },
                )
            ).scalar_one()
        )
        ids["version"] = str(
            (
                await conn.execute(
                    text(
                        """
                        INSERT INTO syllabus_versions (subject_id, version_label,
                          source_document_id, status, is_current)
                        VALUES (CAST(:s AS uuid), :label, CAST(:d AS uuid), 'draft', false)
                        RETURNING id
                        """
                    ),
                    {"s": ids["subject"], "label": f"pub-{suffix}", "d": ids["document"]},
                )
            ).scalar_one()
        )
        parent = None
        for key, item_type, code in (
            ("topic", "topic", "PUB.I"),
            ("subtopic", "subtopic", "PUB.I.1"),
            ("skill", "skill", "PUB.I.1.i"),
        ):
            ids[key] = str(
                (
                    await conn.execute(
                        text(
                            """
                            INSERT INTO curriculum_items (syllabus_version_id, subject_id,
                              parent_id, item_type, code, name)
                            VALUES (CAST(:v AS uuid), CAST(:s AS uuid), CAST(:p AS uuid),
                              :type, :c, :n)
                            RETURNING id
                            """
                        ),
                        {
                            "v": ids["version"],
                            "s": ids["subject"],
                            "p": parent,
                            "type": item_type,
                            "c": code,
                            "n": f"Publishing test {item_type}",
                        },
                    )
                ).scalar_one()
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO curriculum_evidence (curriculum_item_id, source_document_id,
                      evidence_kind, source_location, source_excerpt, review_status,
                      reviewed_by, reviewed_at)
                    VALUES (CAST(:i AS uuid), CAST(:d AS uuid), 'inclusion', 'page 1', :x,
                      'pending', NULL, NULL)
                    """
                ),
                {
                    "i": ids[key],
                    "d": ids["document"],
                    "x": f"Printed line for {code}",
                },
            )
            parent = ids[key]

    yield ids

    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL scorepilot.allow_erasure = 'on'"))
        for statement in (
            "DELETE FROM curriculum_evidence WHERE curriculum_item_id IN "
            "(SELECT id FROM curriculum_items WHERE subject_id = CAST(:s AS uuid))",
            "DELETE FROM curriculum_items WHERE subject_id = CAST(:s AS uuid) "
            "AND item_type = 'skill'",
            "DELETE FROM curriculum_items WHERE subject_id = CAST(:s AS uuid) "
            "AND item_type = 'subtopic'",
            "DELETE FROM curriculum_items WHERE subject_id = CAST(:s AS uuid)",
            "DELETE FROM syllabus_versions WHERE subject_id = CAST(:s AS uuid)",
            "DELETE FROM source_documents WHERE subject_id = CAST(:s AS uuid)",
            "DELETE FROM subjects WHERE id = CAST(:s AS uuid)",
            "DELETE FROM examinations WHERE id = CAST(:e AS uuid)",
        ):
            await conn.execute(text(statement), {"s": ids["subject"], "e": ids["exam"]})


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_the_document_list_says_what_rests_on_each_decision(
    client: httpx.AsyncClient, draft_subject: dict[str, str]
) -> None:
    response = await client.get(
        "/v1/publishing/documents", params={"subject_id": draft_subject["subject"]}
    )
    assert response.status_code == 200, response.text
    document = response.json()[0]
    assert document["licence_status"] == "pending"
    assert document["student_delivery_permission"] is False
    # Three curriculum items hang off this one licence decision, and the list says so before
    # the decision is made rather than after.
    assert document["curriculum_items"] == 3


async def test_a_permission_cannot_be_granted_without_a_verified_licence(
    client: httpx.AsyncClient, draft_subject: dict[str, str]
) -> None:
    response = await client.post(
        f"/v1/publishing/documents/{draft_subject['document']}/licence",
        json={
            "reviewer_id": draft_subject["reviewer"],
            "licence_status": "pending",
            "student_delivery_permission": True,
        },
    )
    assert response.status_code == 409, response.text
    assert "source_documents_check" in response.json()["detail"]


async def _ready_to_approve_items(
    client: httpx.AsyncClient, ids: dict[str, str]
) -> None:
    """Licence the document, approve its citations, publish the version — everything an item
    approval needs before its own rules are even reached."""
    reviewer = ids["reviewer"]
    await client.post(
        f"/v1/publishing/documents/{ids['document']}/licence",
        json={
            "reviewer_id": reviewer,
            "licence_status": "verified",
            # A syllabus version cannot be approved unless we may keep the document itself.
            "storage_permission": True,
            "student_delivery_permission": True,
        },
    )
    citations = (
        await client.get("/v1/publishing/evidence", params={"subject_id": ids["subject"]})
    ).json()
    for citation in citations:
        await client.post(
            f"/v1/publishing/evidence/{citation['evidence_id']}/approve",
            json={"reviewer_id": reviewer},
        )
    await client.post(
        f"/v1/publishing/syllabus-versions/{ids['version']}/publish",
        json={"reviewer_id": reviewer},
    )


async def test_an_item_cannot_be_supported_while_it_is_retired(
    client: httpx.AsyncClient, draft_subject: dict[str, str]
) -> None:
    """Status and support are set in one call because the database will not let them disagree.

    A retired item is off the syllabus, so saying we support teaching it is incoherent. The
    endpoint does not second-guess the pair; it lets the constraint speak.
    """
    await _ready_to_approve_items(client, draft_subject)
    response = await client.post(
        f"/v1/publishing/curriculum/{draft_subject['topic']}/approve",
        json={
            "reviewer_id": draft_subject["reviewer"],
            "syllabus_status": "retired",
            "pilot_support_status": "supported",
        },
    )
    assert response.status_code == 409, response.text
    assert "scope_support" in response.json()["detail"]


async def test_the_whole_chain_makes_one_skill_teachable(
    client: httpx.AsyncClient, draft_subject: dict[str, str]
) -> None:
    """Every step is needed, and the order is the database's, not ours.

    The two orderings that are easy to get wrong, and that this test pins down: a citation
    cannot be approved before the document it cites is licensed, and an item cannot be
    approved before its syllabus version is. Both are enforced by triggers, so getting the
    order wrong fails loudly rather than quietly leaving a skill unteachable.
    """
    reviewer = draft_subject["reviewer"]

    before = await client.get(
        "/v1/publishing/catalogue", params={"subject_id": draft_subject["subject"]}
    )
    assert before.json()["teachable_skills"] == 0

    citations = (
        await client.get(
            "/v1/publishing/evidence", params={"subject_id": draft_subject["subject"]}
        )
    ).json()
    assert len(citations) == 3

    # Too early: the document is not licensed yet.
    premature = await client.post(
        f"/v1/publishing/evidence/{citations[0]['evidence_id']}/approve",
        json={"reviewer_id": reviewer},
    )
    assert premature.status_code == 409, premature.text
    assert "rights-verified source document" in premature.json()["detail"]

    licence = await client.post(
        f"/v1/publishing/documents/{draft_subject['document']}/licence",
        json={
            "reviewer_id": reviewer,
            "licence_status": "verified",
            "storage_permission": True,
            "student_delivery_permission": True,
        },
    )
    assert licence.status_code == 200, licence.text
    assert licence.json()["review_status"] == "approved"

    for citation in citations:
        approved = await client.post(
            f"/v1/publishing/evidence/{citation['evidence_id']}/approve",
            json={"reviewer_id": reviewer},
        )
        assert approved.status_code == 200, approved.text

    # Also too early: an item cannot be approved against a draft syllabus version.
    early_item = await client.post(
        f"/v1/publishing/curriculum/{draft_subject['topic']}/approve",
        json={"reviewer_id": reviewer, "syllabus_status": "explicit"},
    )
    assert early_item.status_code == 409, early_item.text
    assert "approved syllabus version" in early_item.json()["detail"]

    published = await client.post(
        f"/v1/publishing/syllabus-versions/{draft_subject['version']}/publish",
        json={"reviewer_id": reviewer},
    )
    assert published.status_code == 200, published.text
    assert published.json()["teachable_skills"] == 0

    for key in ("topic", "subtopic", "skill"):
        approved = await client.post(
            f"/v1/publishing/curriculum/{draft_subject[key]}/approve",
            json={
                "reviewer_id": reviewer,
                "syllabus_status": "explicit",
                "pilot_support_status": "supported",
            },
        )
        assert approved.status_code == 200, approved.text

    # Everything approved, and still nothing: the catalogue itself is the last gate.
    midway = await client.get(
        "/v1/publishing/catalogue", params={"subject_id": draft_subject["subject"]}
    )
    assert midway.json()["teachable_skills"] == 0

    switched = await client.post(
        f"/v1/publishing/subjects/{draft_subject['subject']}/activate",
        json={"reviewer_id": reviewer, "activate_examination": True},
    )
    assert switched.status_code == 200, switched.text
    body = switched.json()
    assert body["subject_status"] == "active"
    assert body["examination_status"] == "active"
    assert body["teachable_skills"] == 1
    # Teachable is not the same as deliverable: there are no questions here at all.
    assert body["deliverable_questions"] == 0


async def test_an_unknown_reviewer_decides_nothing(
    client: httpx.AsyncClient, draft_subject: dict[str, str]
) -> None:
    response = await client.post(
        f"/v1/publishing/documents/{draft_subject['document']}/licence",
        json={
            "reviewer_id": str(uuid.uuid4()),
            "licence_status": "verified",
            "student_delivery_permission": True,
        },
    )
    assert response.status_code == 400, response.text
