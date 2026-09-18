"""The adaptive practice loop, against the local database.

Needs the cluster from `make db-start` with migrations applied; skipped otherwise.

What these assert is the whole claim of the feature: a student is served a question
they have not seen, the answer key never reaches them, the server marks it, and
what they know afterwards is written as history rather than set.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import text

from app.db import database_is_reachable, get_engine
from app.main import app
from engine import ENGINE_VERSION

pytestmark = pytest.mark.integration


@pytest.fixture
async def practice_fixture() -> AsyncIterator[dict[str, str]]:
    """One student and two approved questions on one skill, at levels 3 and 4."""
    if not await database_is_reachable():
        pytest.skip("database unreachable — run `make db-start && make migrate`")

    engine = get_engine()
    suffix = uuid.uuid4().hex[:8]
    ids: dict[str, str] = {}

    async def scalar(conn, sql: str, **params: object) -> str:
        return str((await conn.execute(text(sql), params)).scalar_one())

    async with engine.begin() as conn:
        ids["reviewer"] = await scalar(
            conn,
            "INSERT INTO academic_reviewers (display_name) VALUES (:n) RETURNING id",
            n=f"Practice reviewer {suffix}",
        )
        # Separate person: the schema refuses to let an author approve their own
        # question, which is the point of the review step.
        ids["author"] = await scalar(
            conn,
            "INSERT INTO academic_reviewers (display_name) VALUES (:n) RETURNING id",
            n=f"Practice author {suffix}",
        )
        ids["exam"] = await scalar(
            conn,
            """
            INSERT INTO examinations (name, short_name, exam_body, country_code, status)
            VALUES (:n, :s, 'Test body', 'NG', 'active') RETURNING id
            """,
            n=f"Practice exam {suffix}",
            s=f"PR{suffix[:4]}",
        )
        ids["subject"] = await scalar(
            conn,
            """
            INSERT INTO subjects (examination_id, code, name, status)
            VALUES (:e, 'ENG', 'English Language', 'active') RETURNING id
            """,
            e=ids["exam"],
        )
        ids["doc"] = await scalar(
            conn,
            """
            INSERT INTO source_documents (examination_id, subject_id, document_type, title,
              file_uri, file_sha256, mime_type, licence_status, storage_permission,
              student_delivery_permission, review_status, reviewed_by, reviewed_at)
            VALUES (:e, :s, 'syllabus', 'Practice syllabus', :uri, :sha, 'application/pdf',
              'verified', true, true, 'approved', :r, now()) RETURNING id
            """,
            e=ids["exam"],
            s=ids["subject"],
            uri=f"test://practice/{suffix}",
            sha=uuid.uuid4().hex + uuid.uuid4().hex,
            r=ids["reviewer"],
        )
        ids["version"] = await scalar(
            conn,
            """
            INSERT INTO syllabus_versions (subject_id, version_label, source_document_id,
              status, is_current, approved_by, approved_at)
            VALUES (:s, :label, :d, 'approved', true, :r, now()) RETURNING id
            """,
            s=ids["subject"],
            label=f"practice-{suffix}",
            d=ids["doc"],
            r=ids["reviewer"],
        )

        parent = None
        for item_type, code in (("topic", "LEX"), ("subtopic", "LEX.V"), ("skill", "LEX.V.1")):
            item = await scalar(
                conn,
                """
                INSERT INTO curriculum_items (syllabus_version_id, subject_id, parent_id,
                  item_type, code, name, syllabus_status, pilot_support_status)
                VALUES (:v, :s, :p, :t, :c, :c, 'explicit', 'supported') RETURNING id
                """,
                v=ids["version"],
                s=ids["subject"],
                p=parent,
                t=item_type,
                c=f"{code}.{suffix}",
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO curriculum_evidence (curriculum_item_id, source_document_id,
                      evidence_kind, source_location, review_status, reviewed_by, reviewed_at)
                    VALUES (:i, :d, 'inclusion', 'page 1', 'approved', :r, now())
                    """
                ),
                {"i": item, "d": ids["doc"], "r": ids["reviewer"]},
            )
            await conn.execute(
                text(
                    """
                    UPDATE curriculum_items SET review_status = 'approved',
                      approved_by = :r, approved_at = now() WHERE id = :i
                    """
                ),
                {"i": item, "r": ids["reviewer"]},
            )
            parent = item
        ids["skill"] = str(parent)

        # Two questions on the same skill, one level apart, so the ladder has
        # somewhere to move to.
        for label, level in (("q3", 3), ("q4", 4)):
            question = await scalar(
                conn,
                """
                INSERT INTO questions (subject_id, origin, usage_pool, created_by)
                VALUES (:s, 'authored', 'practice', :r) RETURNING id
                """,
                s=ids["subject"],
                r=ids["author"],
            )
            version = await scalar(
                conn,
                """
                INSERT INTO question_versions (question_id, subject_id, version, stem,
                  response_format, marking_method, solution_steps, hints, marks,
                  expected_seconds, mastery_level_number, option_count, content_hash,
                  authored_by, answer_source, level_source)
                VALUES (:q, :s, 1, :stem, 'mcq_single', 'auto_key',
                  '["Work it through", "Check the sense"]'::jsonb,
                  '["Which word means not moving?"]'::jsonb,
                  1, 45, :lvl, 4, :hash, :r, 'expert_verified', 'expert_verified')
                RETURNING id
                """,
                q=question,
                s=ids["subject"],
                stem=f"Practice question at level {level} ({suffix}).",
                lvl=level,
                hash=uuid.uuid4().hex + uuid.uuid4().hex,
                r=ids["author"],
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO question_options (question_version_id, subject_id,
                      option_key, body, is_correct, display_order)
                    VALUES (:v, :s, 'A', 'stationary', true, 1),
                           (:v, :s, 'B', 'stagnant', false, 2),
                           (:v, :s, 'C', 'stationed', false, 3),
                           (:v, :s, 'D', 'stationery', false, 4)
                    """
                ),
                {"v": version, "s": ids["subject"]},
            )
            await conn.execute(
                text(
                    """
                    UPDATE question_versions SET review_status = 'approved',
                      reviewed_by = :r, reviewed_at = now() WHERE id = :v
                    """
                ),
                {"v": version, "r": ids["reviewer"]},
            )
            await conn.execute(
                text("UPDATE questions SET current_version_id = :v WHERE id = :q"),
                {"v": version, "q": question},
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO question_classifications (question_id, subject_id,
                      curriculum_item_id, syllabus_version_id, classification_role,
                      classification_reason, review_status, reviewed_by, reviewed_at)
                    VALUES (:q, :s, :skill, :v, 'primary', 'Vocabulary choice.',
                      'approved', :r, now())
                    """
                ),
                {
                    "q": question,
                    "s": ids["subject"],
                    "skill": ids["skill"],
                    "v": ids["version"],
                    "r": ids["reviewer"],
                },
            )
            ids[label] = question

        user = await scalar(
            conn,
            """
            INSERT INTO users (first_name, last_name, email, role, status)
            VALUES ('Ada', 'Practice', :email, 'student', 'active') RETURNING id
            """,
            email=f"ada.{suffix}@example.test",
        )
        ids["user"] = user
        ids["student"] = await scalar(
            conn,
            "INSERT INTO student_profiles (user_id) VALUES (:u) RETURNING id",
            u=user,
        )

    yield ids

    async with engine.begin() as conn:
        # The guards this schema exists to provide -- append-only history, frozen
        # placements -- also refuse a test's cleanup, which is the correct
        # behaviour. Teardown lowers them explicitly rather than the schema being
        # made weaker to accommodate it.
        guarded = (
            "mastery_events",
            "student_skill_mastery",
            "assessment_questions",
            "question_versions",
            "question_options",
        )
        for table in guarded:
            await conn.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))

        for sql in (
            "DELETE FROM mastery_events WHERE student_id = :student",
            "DELETE FROM student_skill_mastery WHERE student_id = :student",
        ):
            await conn.execute(text(sql), {"student": ids["student"]})
        await conn.execute(
            text(
                """
                DELETE FROM student_responses WHERE attempt_id IN
                  (SELECT id FROM assessment_attempts WHERE student_id = :student)
                """
            ),
            {"student": ids["student"]},
        )
        await conn.execute(
            text("DELETE FROM assessment_attempts WHERE student_id = :student"),
            {"student": ids["student"]},
        )
        await conn.execute(
            text(
                """
                DELETE FROM assessment_questions WHERE assessment_id IN
                  (SELECT id FROM assessments WHERE created_for_student_id = :student)
                """
            ),
            {"student": ids["student"]},
        )
        await conn.execute(
            text("DELETE FROM assessments WHERE created_for_student_id = :student"),
            {"student": ids["student"]},
        )
        # The profile references the account with RESTRICT, so it goes first.
        await conn.execute(
            text("DELETE FROM student_profiles WHERE id = :student"),
            {"student": ids["student"]},
        )
        await conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": ids["user"]})
        for question in (ids["q3"], ids["q4"]):
            await conn.execute(
                text("UPDATE questions SET current_version_id = NULL WHERE id = :q"),
                {"q": question},
            )
            await conn.execute(
                text("DELETE FROM question_classifications WHERE question_id = :q"),
                {"q": question},
            )
            await conn.execute(
                text(
                    """
                    DELETE FROM question_options WHERE question_version_id IN
                      (SELECT id FROM question_versions WHERE question_id = :q)
                    """
                ),
                {"q": question},
            )
            await conn.execute(
                text("DELETE FROM question_versions WHERE question_id = :q"), {"q": question}
            )
            await conn.execute(text("DELETE FROM questions WHERE id = :q"), {"q": question})
        await conn.execute(
            text("DELETE FROM curriculum_evidence WHERE source_document_id = :d"),
            {"d": ids["doc"]},
        )
        for item_type in ("skill", "subtopic", "topic"):
            await conn.execute(
                text(
                    """
                    DELETE FROM curriculum_items
                    WHERE syllabus_version_id = :v AND item_type = :t
                    """
                ),
                {"v": ids["version"], "t": item_type},
            )
        await conn.execute(
            text("DELETE FROM syllabus_versions WHERE id = :v"), {"v": ids["version"]}
        )
        await conn.execute(text("DELETE FROM source_documents WHERE id = :d"), {"d": ids["doc"]})
        await conn.execute(text("DELETE FROM subjects WHERE id = :s"), {"s": ids["subject"]})
        await conn.execute(text("DELETE FROM examinations WHERE id = :e"), {"e": ids["exam"]})
        await conn.execute(
            text("DELETE FROM academic_reviewers WHERE id = ANY(:ids)"),
            {"ids": [ids["reviewer"], ids["author"]]},
        )

        for table in guarded:
            await conn.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER USER"))


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_a_question_arrives_without_its_answer(
    client: httpx.AsyncClient, practice_fixture: dict[str, str]
) -> None:
    response = await client.get(
        f"/v1/practice/{practice_fixture['student']}/next",
        params={"skill_id": practice_fixture["skill"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["stem"]
    assert len(body["options"]) == 4
    # The single thing this endpoint must never do.
    assert all("is_correct" not in option for option in body["options"])
    assert "stationary" in [option["body"] for option in body["options"]]
    # A cold start opens at the level nearest a 70% chance, which for theta 0 is 3.
    assert body["level"] == 3
    assert "level 3" in body["chosen_because"]


async def test_a_correct_answer_is_marked_and_recorded(
    client: httpx.AsyncClient, practice_fixture: dict[str, str]
) -> None:
    served = (
        await client.get(
            f"/v1/practice/{practice_fixture['student']}/next",
            params={"skill_id": practice_fixture["skill"]},
        )
    ).json()
    correct = next(o for o in served["options"] if o["body"] == "stationary")

    marked = await client.post(
        f"/v1/practice/{practice_fixture['student']}/answer",
        json={
            "assessment_question_id": served["assessment_question_id"],
            "selected_option_id": correct["option_id"],
            "response_ms": 30_000,
        },
    )

    assert marked.status_code == 200
    body = marked.json()
    assert body["is_correct"] is True
    assert body["awarded_marks"] == 1
    assert body["help"] is None
    assert body["scored"] is True
    assert body["engine_version"] == ENGINE_VERSION
    # One answer is not enough evidence to claim a band.
    assert body["band"] == "not_assessed"
    assert body["mastery"] > 0.5

    engine = get_engine()
    async with engine.connect() as conn:
        events = (
            await conn.execute(
                text(
                    """
                    SELECT count(*) FROM mastery_events
                    WHERE student_id = :s AND curriculum_item_id = :skill
                    """
                ),
                {"s": practice_fixture["student"], "skill": practice_fixture["skill"]},
            )
        ).scalar_one()
    assert events == 1, "the rating moved without recording why"


async def test_a_wrong_answer_offers_the_smallest_help(
    client: httpx.AsyncClient, practice_fixture: dict[str, str]
) -> None:
    served = (
        await client.get(
            f"/v1/practice/{practice_fixture['student']}/next",
            params={"skill_id": practice_fixture["skill"]},
        )
    ).json()
    wrong = next(o for o in served["options"] if o["body"] != "stationary")

    body = (
        await client.post(
            f"/v1/practice/{practice_fixture['student']}/answer",
            json={
                "assessment_question_id": served["assessment_question_id"],
                "selected_option_id": wrong["option_id"],
                "response_ms": 40_000,
            },
        )
    ).json()

    assert body["is_correct"] is False
    assert body["awarded_marks"] == 0
    assert body["correct_option_key"] == "A"
    assert body["help"] in {"check_again", "hint", "worked_solution", "micro_lesson"}
    # Something useful came back, whichever rung the ladder chose.
    assert body["hint"] or body["solution_steps"]


async def test_the_same_question_is_not_served_twice(
    client: httpx.AsyncClient, practice_fixture: dict[str, str]
) -> None:
    first = (
        await client.get(
            f"/v1/practice/{practice_fixture['student']}/next",
            params={"skill_id": practice_fixture["skill"]},
        )
    ).json()
    correct = next(o for o in first["options"] if o["body"] == "stationary")
    await client.post(
        f"/v1/practice/{practice_fixture['student']}/answer",
        json={
            "assessment_question_id": first["assessment_question_id"],
            "selected_option_id": correct["option_id"],
            "response_ms": 30_000,
        },
    )

    second = (
        await client.get(
            f"/v1/practice/{practice_fixture['student']}/next",
            params={"skill_id": practice_fixture["skill"]},
        )
    ).json()

    assert second["question_id"] != first["question_id"]
    # Both live in one session, so the sitting carries on rather than restarting.
    assert second["attempt_id"] == first["attempt_id"]


async def test_a_skill_nobody_approved_is_refused(
    client: httpx.AsyncClient, practice_fixture: dict[str, str]
) -> None:
    response = await client.get(
        f"/v1/practice/{practice_fixture['student']}/next",
        params={"skill_id": str(uuid.uuid4())},
    )

    assert response.status_code == 404
