"""Review endpoints against the local database.

Each test builds its own throwaway exam, subject, syllabus and question, so it never
touches imported content, and deletes them afterwards.
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
async def fixture_question() -> AsyncIterator[dict[str, str]]:
    if not await database_is_reachable():
        pytest.skip("database unreachable — run `make db-start && make migrate`")

    engine = get_engine()
    suffix = uuid.uuid4().hex[:8]
    ids: dict[str, str] = {}
    async with engine.begin() as conn:
        ids["reviewer"] = str(
            (
                await conn.execute(
                    text(
                        "INSERT INTO academic_reviewers (display_name) VALUES (:n) RETURNING id"
                    ),
                    {"n": f"Review test reviewer {suffix}"},
                )
            ).scalar_one()
        )
        ids["author"] = str(
            (
                await conn.execute(
                    text(
                        "INSERT INTO academic_reviewers (display_name) VALUES (:n) RETURNING id"
                    ),
                    {"n": f"Review test author {suffix}"},
                )
            ).scalar_one()
        )
        ids["exam"] = str(
            (
                await conn.execute(
                    text(
                        """
                        INSERT INTO examinations (name, short_name, exam_body, country_code, status)
                        VALUES (:n, :s, 'Test body', 'NG', 'active') RETURNING id
                        """
                    ),
                    {"n": f"Review test exam {suffix}", "s": f"RT{suffix[:4]}"},
                )
            ).scalar_one()
        )
        ids["subject"] = str(
            (
                await conn.execute(
                    text(
                        """
                        INSERT INTO subjects (examination_id, code, name, status)
                        VALUES (:e, 'ENG', 'English Language', 'active') RETURNING id
                        """
                    ),
                    {"e": ids["exam"]},
                )
            ).scalar_one()
        )
        document = str(
            (
                await conn.execute(
                    text(
                        """
                        INSERT INTO source_documents (examination_id, subject_id, document_type,
                          title, file_uri, file_sha256, mime_type, licence_status,
                          storage_permission, student_delivery_permission, review_status,
                          reviewed_by, reviewed_at)
                        VALUES (:e, :s, 'syllabus', 'Review test syllabus', :uri, :sha,
                          'application/pdf', 'verified', true, true, 'approved', :r, now())
                        RETURNING id
                        """
                    ),
                    {
                        "e": ids["exam"],
                        "s": ids["subject"],
                        "uri": f"test://review/{suffix}",
                        "sha": uuid.uuid4().hex + uuid.uuid4().hex,
                        "r": ids["reviewer"],
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
                          source_document_id, status, is_current, approved_by, approved_at)
                        VALUES (:s, :label, :d, 'approved', true, :r, now()) RETURNING id
                        """
                    ),
                    {
                        "s": ids["subject"],
                        "label": f"review-test-{suffix}",
                        "d": document,
                        "r": ids["reviewer"],
                    },
                )
            ).scalar_one()
        )

        parents = {}
        for item_type, code, parent in (
            ("topic", "LEX", None),
            ("subtopic", "LEX.V", "LEX"),
            ("skill", "LEX.V.1", "LEX.V"),
            ("skill", "LEX.V.2", "LEX.V"),
        ):
            parents[code] = str(
                (
                    await conn.execute(
                        text(
                            """
                            INSERT INTO curriculum_items (syllabus_version_id, subject_id,
                              parent_id, item_type, code, name, syllabus_status,
                              pilot_support_status)
                            VALUES (:v, :s, :p, :t, :c, :c, 'explicit', 'supported')
                            RETURNING id
                            """
                        ),
                        {
                            "v": ids["version"],
                            "s": ids["subject"],
                            "p": parents.get(parent),
                            "t": item_type,
                            "c": code,
                        },
                    )
                ).scalar_one()
            )
        ids["skill"] = parents["LEX.V.1"]
        ids["other_skill"] = parents["LEX.V.2"]

        ids["question"] = str(
            (
                await conn.execute(
                    text(
                        """
                        INSERT INTO questions (subject_id, origin, usage_pool, created_by)
                        VALUES (:s, 'authored', 'practice', :a) RETURNING id
                        """
                    ),
                    {"s": ids["subject"], "a": ids["author"]},
                )
            ).scalar_one()
        )
        question_version = str(
            (
                await conn.execute(
                    text(
                        """
                        INSERT INTO question_versions (question_id, subject_id, version, stem,
                          response_format, marking_method, marks, expected_seconds, option_count,
                          content_hash, authored_by, answer_source, answer_confidence)
                        VALUES (:q, :s, 1, 'The car crashed into a ______ vehicle.', 'mcq_single',
                          'auto_key', 1, 45, 4, :hash, :a, 'model_proposed', 'high')
                        RETURNING id
                        """
                    ),
                    {
                        "q": ids["question"],
                        "s": ids["subject"],
                        "hash": uuid.uuid4().hex + uuid.uuid4().hex,
                        "a": ids["author"],
                    },
                )
            ).scalar_one()
        )
        for position, (key, body, correct) in enumerate(
            [("A", "stationary", True), ("B", "stagnant", False),
             ("C", "stationed", False), ("D", "stationery", False)],
            start=1,
        ):
            await conn.execute(
                text(
                    """
                    INSERT INTO question_options (question_version_id, subject_id, option_key,
                      body, is_correct, display_order)
                    VALUES (:v, :s, :k, :b, :c, :o)
                    """
                ),
                {
                    "v": question_version,
                    "s": ids["subject"],
                    "k": key,
                    "b": body,
                    "c": correct,
                    "o": position,
                },
            )
        await conn.execute(
            text("UPDATE questions SET current_version_id = :v WHERE id = :q"),
            {"v": question_version, "q": ids["question"]},
        )
        await conn.execute(
            text(
                """
                INSERT INTO question_classifications (question_id, subject_id,
                  curriculum_item_id, syllabus_version_id, classification_role, proposed_by,
                  confidence, classification_reason)
                VALUES (:q, :s, :skill, :v, 'primary', 'model', 0.5, 'Proposed during import.')
                """
            ),
            {
                "q": ids["question"],
                "s": ids["subject"],
                "skill": ids["skill"],
                "v": ids["version"],
            },
        )

    yield ids

    async with engine.begin() as conn:
        # Approved content is deliberately immutable, so a test question has to be
        # withdrawn before its rows can be removed.
        await conn.execute(
            text(
                """
                UPDATE question_versions SET review_status = 'withdrawn'
                WHERE question_id = :q AND review_status = 'approved'
                """
            ),
            {"q": ids["question"]},
        )
        await conn.execute(
            text("DELETE FROM question_classifications WHERE question_id = :q"),
            {"q": ids["question"]},
        )
        await conn.execute(
            text("DELETE FROM question_options WHERE question_version_id IN "
                 "(SELECT id FROM question_versions WHERE question_id = :q)"),
            {"q": ids["question"]},
        )
        await conn.execute(
            text("UPDATE questions SET current_version_id = NULL WHERE id = :q"),
            {"q": ids["question"]},
        )
        await conn.execute(
            text("DELETE FROM question_versions WHERE question_id = :q"), {"q": ids["question"]}
        )
        await conn.execute(text("DELETE FROM questions WHERE id = :q"), {"q": ids["question"]})
        await conn.execute(
            text(
                "DELETE FROM curriculum_items "
                "WHERE syllabus_version_id = :v AND item_type = 'skill'"
            ),
            {"v": ids["version"]},
        )
        await conn.execute(
            text(
                "DELETE FROM curriculum_items "
                "WHERE syllabus_version_id = :v AND item_type = 'subtopic'"
            ),
            {"v": ids["version"]},
        )
        await conn.execute(
            text("DELETE FROM curriculum_items WHERE syllabus_version_id = :v"),
            {"v": ids["version"]},
        )
        await conn.execute(
            text("DELETE FROM syllabus_versions WHERE id = :v"), {"v": ids["version"]}
        )
        await conn.execute(text("DELETE FROM source_documents WHERE id = :d"), {"d": document})
        await conn.execute(text("DELETE FROM subjects WHERE id = :s"), {"s": ids["subject"]})
        await conn.execute(text("DELETE FROM examinations WHERE id = :e"), {"e": ids["exam"]})
        await conn.execute(
            text("DELETE FROM academic_reviewers WHERE id IN (:r, :a)"),
            {"r": ids["reviewer"], "a": ids["author"]},
        )


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_verifying_an_answer_records_the_decision(
    client: httpx.AsyncClient, fixture_question: dict[str, str]
) -> None:
    response = await client.post(
        f"/v1/review/questions/{fixture_question['question']}/answer",
        json={"reviewer_id": fixture_question["reviewer"], "option_key": "C"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer_source"] == "expert_verified"
    correct = [option for option in body["options"] if option["is_correct"]]
    assert [option["option_key"] for option in correct] == ["C"]


async def test_approval_is_refused_until_everything_is_checked(
    client: httpx.AsyncClient, fixture_question: dict[str, str]
) -> None:
    question = fixture_question["question"]
    reviewer = fixture_question["reviewer"]

    refused = await client.post(
        f"/v1/review/questions/{question}/approve", json={"reviewer_id": reviewer}
    )
    assert refused.status_code == 409
    assert "mastery level" in refused.json()["detail"].lower()

    await client.post(
        f"/v1/review/questions/{question}/answer",
        json={"reviewer_id": reviewer, "option_key": "A"},
    )
    await client.post(
        f"/v1/review/questions/{question}/level", json={"reviewer_id": reviewer, "level": 3}
    )
    await client.post(f"/v1/review/questions/{question}/skill", json={"reviewer_id": reviewer})

    # Still missing the worked solution and the hint.
    without_content = await client.post(
        f"/v1/review/questions/{question}/approve", json={"reviewer_id": reviewer}
    )
    assert without_content.status_code == 409
    assert "solution" in without_content.json()["detail"].lower()

    await client.post(
        f"/v1/review/questions/{question}/content",
        json={
            "reviewer_id": reviewer,
            "solution_steps": ["'Stationary' means not moving."],
            "hints": ["Which word means not moving?"],
        },
    )
    approved = await client.post(
        f"/v1/review/questions/{question}/approve", json={"reviewer_id": reviewer}
    )
    assert approved.status_code == 200
    assert approved.json()["review_status"] == "approved"


async def test_an_approved_question_is_frozen(
    client: httpx.AsyncClient, fixture_question: dict[str, str]
) -> None:
    question = fixture_question["question"]
    reviewer = fixture_question["reviewer"]
    for path, payload in (
        ("answer", {"reviewer_id": reviewer, "option_key": "A"}),
        ("level", {"reviewer_id": reviewer, "level": 2}),
        ("skill", {"reviewer_id": reviewer}),
        (
            "content",
            {
                "reviewer_id": reviewer,
                "solution_steps": ["step"],
                "hints": ["hint"],
            },
        ),
        ("approve", {"reviewer_id": reviewer}),
    ):
        await client.post(f"/v1/review/questions/{question}/{path}", json=payload)

    response = await client.post(
        f"/v1/review/questions/{question}/answer",
        json={"reviewer_id": reviewer, "option_key": "B"},
    )

    assert response.status_code == 409
    assert "frozen" in response.json()["detail"]


async def test_changing_the_skill_records_a_human_decision(
    client: httpx.AsyncClient, fixture_question: dict[str, str]
) -> None:
    response = await client.post(
        f"/v1/review/questions/{fixture_question['question']}/skill",
        json={
            "reviewer_id": fixture_question["reviewer"],
            "curriculum_item_id": fixture_question["other_skill"],
            "reason": "Tests confusables, not vocabulary of a field.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["primary_skill_id"] == fixture_question["other_skill"]
    assert body["classification_status"] == "approved"


async def test_an_unknown_reviewer_is_rejected(
    client: httpx.AsyncClient, fixture_question: dict[str, str]
) -> None:
    response = await client.post(
        f"/v1/review/questions/{fixture_question['question']}/level",
        json={"reviewer_id": str(uuid.uuid4()), "level": 3},
    )

    assert response.status_code == 400
