"""Reserving questions for the check-up, against the local database.

Each test builds its own throwaway subject with its own questions, so it never touches
imported content and can assert exact counts.
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
async def fixture_subject() -> AsyncIterator[dict[str, str]]:
    """A subject with two topics, one weighted twice the other, and questions at three levels.

    Weights come from approved exam sections — 20 questions against 10 — so a reservation
    should split two to one, and the levels let the spread be checked.
    """
    if not await database_is_reachable():
        pytest.skip("database unreachable — run `make db-start && make migrate`")

    engine = get_engine()
    suffix = uuid.uuid4().hex[:8]
    ids: dict[str, str] = {}
    async with engine.begin() as conn:
        ids["author"] = str(
            (
                await conn.execute(
                    text("INSERT INTO academic_reviewers (display_name) VALUES (:n) RETURNING id"),
                    {"n": f"Pool test author {suffix}"},
                )
            ).scalar_one()
        )
        ids["reviewer"] = str(
            (
                await conn.execute(
                    text("INSERT INTO academic_reviewers (display_name) VALUES (:n) RETURNING id"),
                    {"n": f"Pool test reviewer {suffix}"},
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
                    {"n": f"Pool test exam {suffix}", "s": f"PT{suffix[:5]}"},
                )
            ).scalar_one()
        )
        ids["subject"] = str(
            (
                await conn.execute(
                    text(
                        """
                        INSERT INTO subjects (examination_id, code, name, status)
                        VALUES (CAST(:e AS uuid), 'POOL', 'Pool test subject', 'active')
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
                          title, file_uri, file_sha256, mime_type, licence_status,
                          storage_permission, student_delivery_permission, review_status,
                          reviewed_by, reviewed_at)
                        VALUES (CAST(:e AS uuid), CAST(:s AS uuid), 'syllabus', :t, :u, :h,
                          'application/pdf', 'verified', true, true, 'approved',
                          CAST(:r AS uuid), now())
                        RETURNING id
                        """
                    ),
                    {
                        "e": ids["exam"],
                        "s": ids["subject"],
                        "t": f"Pool test syllabus {suffix}",
                        "u": f"test://pool/{suffix}",
                        "h": uuid.uuid4().hex + uuid.uuid4().hex,
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
                        VALUES (CAST(:s AS uuid), :label, CAST(:d AS uuid), 'approved', true,
                          CAST(:r AS uuid), now())
                        RETURNING id
                        """
                    ),
                    {
                        "s": ids["subject"],
                        "label": f"pool-{suffix}",
                        "d": ids["document"],
                        "r": ids["reviewer"],
                    },
                )
            ).scalar_one()
        )

        for key, code, name in (("big", "BIG", "Big topic"), ("small", "SML", "Small topic")):
            ids[key] = str(
                (
                    await conn.execute(
                        text(
                            """
                            INSERT INTO curriculum_items (syllabus_version_id, subject_id,
                              item_type, code, name, syllabus_status, pilot_support_status)
                            VALUES (CAST(:v AS uuid), CAST(:s AS uuid), 'topic', :c, :n,
                              'explicit', 'supported')
                            RETURNING id
                            """
                        ),
                        {"v": ids["version"], "s": ids["subject"], "c": code, "n": name},
                    )
                ).scalar_one()
            )
            ids[f"{key}_sub"] = str(
                (
                    await conn.execute(
                        text(
                            """
                            INSERT INTO curriculum_items (syllabus_version_id, subject_id,
                              parent_id, item_type, code, name, syllabus_status,
                              pilot_support_status)
                            VALUES (CAST(:v AS uuid), CAST(:s AS uuid), CAST(:p AS uuid),
                              'subtopic', :c, :n, 'explicit', 'supported')
                            RETURNING id
                            """
                        ),
                        {
                            "v": ids["version"],
                            "s": ids["subject"],
                            "p": ids[key],
                            "c": f"{code}.1",
                            "n": f"{name} subtopic",
                        },
                    )
                ).scalar_one()
            )
            ids[f"{key}_skill"] = str(
                (
                    await conn.execute(
                        text(
                            """
                            INSERT INTO curriculum_items (syllabus_version_id, subject_id,
                              parent_id, item_type, code, name, syllabus_status,
                              pilot_support_status)
                            VALUES (CAST(:v AS uuid), CAST(:s AS uuid), CAST(:p AS uuid),
                              'skill', :c, :n, 'explicit', 'supported')
                            RETURNING id
                            """
                        ),
                        {
                            "v": ids["version"],
                            "s": ids["subject"],
                            "p": ids[f"{key}_sub"],
                            "c": f"{code}.1.i",
                            "n": f"{name} skill",
                        },
                    )
                ).scalar_one()
            )

        paper = str(
            (
                await conn.execute(
                    text(
                        """
                        INSERT INTO exam_papers (subject_id, paper_code, name, response_mode,
                          question_count, duration_minutes, options_per_question, score_out_of,
                          status)
                        VALUES (CAST(:s AS uuid), 'PT-1', 'Paper 1', 'objective', 30, 30, 4, 30,
                          'active')
                        RETURNING id
                        """
                    ),
                    {"s": ids["subject"]},
                )
            ).scalar_one()
        )
        # Twenty questions against ten: the big topic should take twice the reservation.
        for key, count in (("big", 20), ("small", 10)):
            await conn.execute(
                text(
                    """
                    INSERT INTO exam_paper_sections (exam_paper_id, subject_id, section_code,
                      name, question_count, marks_total, curriculum_item_id, syllabus_version_id,
                      source_location, review_status, reviewed_by, reviewed_at)
                    -- Two names for the same number: one parameter feeding an integer
                    -- column and a numeric one leaves asyncpg unable to deduce a type.
                    VALUES (CAST(:p AS uuid), CAST(:s AS uuid), :code, :name, :count, :marks,
                      CAST(:t AS uuid), CAST(:v AS uuid), 'fixture', 'approved',
                      CAST(:r AS uuid), now())
                    """
                ),
                {
                    "p": paper,
                    "s": ids["subject"],
                    "code": key.upper(),
                    "name": f"{key} section",
                    "count": count,
                    "marks": float(count),
                    "t": ids[key],
                    "v": ids["version"],
                    "r": ids["reviewer"],
                },
            )

        # Six questions per topic, two at each of levels 2, 3 and 4.
        for key in ("big", "small"):
            for index in range(6):
                question = str(
                    (
                        await conn.execute(
                            text(
                                """
                                INSERT INTO questions (subject_id, origin, usage_pool, created_by)
                                VALUES (CAST(:s AS uuid), 'authored', 'practice',
                                  CAST(:a AS uuid))
                                RETURNING id
                                """
                            ),
                            {"s": ids["subject"], "a": ids["author"]},
                        )
                    ).scalar_one()
                )
                version = str(
                    (
                        await conn.execute(
                            text(
                                """
                                INSERT INTO question_versions (question_id, subject_id, version,
                                  stem, response_format, marking_method, marks, expected_seconds,
                                  option_count, mastery_level_number, content_hash, authored_by)
                                VALUES (CAST(:q AS uuid), CAST(:s AS uuid), 1, :stem, 'mcq_single',
                                  'auto_key', 1, 45, 4, :level, :hash, CAST(:a AS uuid))
                                RETURNING id
                                """
                            ),
                            {
                                "q": question,
                                "s": ids["subject"],
                                "stem": f"{key} question {index}",
                                "level": 2 + (index % 3),
                                "hash": uuid.uuid4().hex + uuid.uuid4().hex,
                                "a": ids["author"],
                            },
                        )
                    ).scalar_one()
                )
                await conn.execute(
                    text(
                        "UPDATE questions SET current_version_id = CAST(:v AS uuid) "
                        "WHERE id = CAST(:q AS uuid)"
                    ),
                    {"v": version, "q": question},
                )
                await conn.execute(
                    text(
                        """
                        INSERT INTO question_classifications (question_id, subject_id,
                          curriculum_item_id, syllabus_version_id, classification_role,
                          classification_reason, review_status)
                        VALUES (CAST(:q AS uuid), CAST(:s AS uuid), CAST(:skill AS uuid),
                          CAST(:v AS uuid), 'primary', 'fixture', 'draft')
                        """
                    ),
                    {
                        "q": question,
                        "s": ids["subject"],
                        "skill": ids[f"{key}_skill"],
                        "v": ids["version"],
                    },
                )

    yield ids

    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL scorepilot.allow_erasure = 'on'"))
        for statement in (
            "DELETE FROM question_classifications WHERE subject_id = CAST(:s AS uuid)",
            "DELETE FROM question_options WHERE subject_id = CAST(:s AS uuid)",
            "UPDATE questions SET current_version_id = NULL WHERE subject_id = CAST(:s AS uuid)",
            "DELETE FROM question_versions WHERE subject_id = CAST(:s AS uuid)",
            "DELETE FROM questions WHERE subject_id = CAST(:s AS uuid)",
            "DELETE FROM exam_paper_sections WHERE subject_id = CAST(:s AS uuid)",
            "DELETE FROM exam_papers WHERE subject_id = CAST(:s AS uuid)",
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


async def test_the_plan_follows_the_exam_weights(
    client: httpx.AsyncClient, fixture_subject: dict[str, str]
) -> None:
    response = await client.get(
        "/v1/pool/diagnostic/plan",
        params={"subject_id": fixture_subject["subject"], "size": 9},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["weights_source"] == "exam_structure"
    by_name = {topic["topic_name"]: topic for topic in body["topics"]}
    # Twenty marks against ten: two questions for the big topic to every one for the small.
    assert by_name["Big topic"]["wanted"] == 6
    assert by_name["Small topic"]["wanted"] == 3


async def test_a_reservation_spreads_across_levels(
    client: httpx.AsyncClient, fixture_subject: dict[str, str]
) -> None:
    response = await client.post(
        "/v1/pool/diagnostic/reserve",
        json={"subject_id": fixture_subject["subject"], "size": 9},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reserved"] == 9
    by_name = {topic["topic_name"]: topic for topic in body["topics"]}
    # Three levels exist in the fixture, and a reservation of this size must touch all of
    # them: a check-up whose questions are all one difficulty cannot adapt.
    assert by_name["Big topic"]["levels_in_pool"] == [2, 3, 4]
    assert body["deliverable_now"] == 0, "nothing is approved, so nothing may reach a student"


async def test_reserving_again_tops_up_rather_than_duplicating(
    client: httpx.AsyncClient, fixture_subject: dict[str, str]
) -> None:
    first = await client.post(
        "/v1/pool/diagnostic/reserve",
        json={"subject_id": fixture_subject["subject"], "size": 9},
    )
    again = await client.post(
        "/v1/pool/diagnostic/reserve",
        json={"subject_id": fixture_subject["subject"], "size": 9},
    )
    assert first.json()["reserved"] == 9
    assert again.json()["reserved"] == 0
    assert again.json()["total_in_pool"] == 9


async def test_readiness_names_what_is_blocking_delivery(
    client: httpx.AsyncClient, fixture_subject: dict[str, str]
) -> None:
    await client.post(
        "/v1/pool/diagnostic/reserve",
        json={"subject_id": fixture_subject["subject"], "size": 9},
    )
    response = await client.get(
        "/v1/pool/diagnostic/readiness", params={"subject_id": fixture_subject["subject"]}
    )
    body = response.json()
    assert body["in_pool"] == 9
    assert body["deliverable"] == 0
    assert body["ready_for_checkup"] is False
    reasons = {item["reason"] for item in body["blocked_by"]}
    assert "an answer no person has verified" in reasons
    assert "a skill mapping still unapproved" in reasons


async def test_releasing_puts_drafts_back_into_practice(
    client: httpx.AsyncClient, fixture_subject: dict[str, str]
) -> None:
    await client.post(
        "/v1/pool/diagnostic/reserve",
        json={"subject_id": fixture_subject["subject"], "size": 9},
    )
    response = await client.request(
        "DELETE",
        "/v1/pool/diagnostic/reserve",
        params={"subject_id": fixture_subject["subject"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["reserved"] == -9
    readiness = await client.get(
        "/v1/pool/diagnostic/readiness", params={"subject_id": fixture_subject["subject"]}
    )
    assert readiness.json()["in_pool"] == 0
