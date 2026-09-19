"""The sandbox cleanup, and the guard that keeps it honest.

Every foreign key into `students` is ON DELETE RESTRICT, so `DELETE /v1/dev/students` has to
name every table that points at a student. That list is the kind that rots: a migration adds a
student-owned table, nobody remembers this endpoint, and the next cleanup returns a 500 that
looks like a database problem rather than a missing line of SQL.

So there are two tests here. One clears a student who has a row in every one of those tables
and proves the statement survives it. The other reads the catalogue and fails when a table
appears that the statement does not mention — that one is the guard, because it needs no
fixture and cannot be satisfied by a developer who did not think about erasure.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import text

from app.db import database_is_reachable, get_engine
from app.main import app
from app.routers.dev import CLEAR_STUDENTS_SQL, SANDBOX_PREFIX

pytestmark = pytest.mark.integration

# Content the student's rows can hang off: a subject, a skill, and one approved question.
CONTENT = """
WITH reviewer AS (
  INSERT INTO academic_reviewers (display_name) VALUES (:reviewer) RETURNING id
), exam AS (
  INSERT INTO examinations (name, short_name, exam_body, country_code, status)
  VALUES (:exam_name, :short, 'Test body', 'NG', 'active') RETURNING id
), subject AS (
  INSERT INTO subjects (examination_id, code, name, status)
  SELECT exam.id, 'DEV', 'Dev cleanup subject', 'active' FROM exam RETURNING id, examination_id
), document AS (
  INSERT INTO source_documents (examination_id, subject_id, document_type, title, file_uri,
    file_sha256, mime_type, licence_status, storage_permission, student_delivery_permission,
    review_status, reviewed_by, reviewed_at)
  SELECT subject.examination_id, subject.id, 'syllabus', :doc_title, :doc_uri, :doc_hash,
    'application/pdf', 'verified', true, true, 'approved', reviewer.id, now()
  FROM subject, reviewer RETURNING id
), version AS (
  INSERT INTO syllabus_versions (subject_id, version_label, source_document_id, status,
    is_current, approved_by, approved_at)
  SELECT subject.id, :label, document.id, 'approved', true, reviewer.id, now()
  FROM subject, document, reviewer RETURNING id, subject_id
), topic AS (
  INSERT INTO curriculum_items (syllabus_version_id, subject_id, item_type, code, name,
    syllabus_status, pilot_support_status, review_status)
  SELECT version.id, version.subject_id, 'topic', 'DEV.I', 'The topic', 'explicit',
    'supported', 'draft'
  FROM version RETURNING id, syllabus_version_id, subject_id
), sub AS (
  INSERT INTO curriculum_items (syllabus_version_id, subject_id, parent_id, item_type, code,
    name, syllabus_status, pilot_support_status, review_status)
  SELECT topic.syllabus_version_id, topic.subject_id, topic.id, 'subtopic', 'DEV.I.1',
    'The subtopic', 'explicit', 'supported', 'draft'
  FROM topic RETURNING id, syllabus_version_id, subject_id
), skill AS (
  INSERT INTO curriculum_items (syllabus_version_id, subject_id, parent_id, item_type, code,
    name, syllabus_status, pilot_support_status, review_status)
  SELECT sub.syllabus_version_id, sub.subject_id, sub.id, 'skill', 'DEV.I.1.i', 'The skill',
    'explicit', 'supported', 'draft'
  FROM sub RETURNING id
), question AS (
  INSERT INTO questions (subject_id, origin, usage_pool, created_by)
  SELECT subject.id, 'authored', 'practice', reviewer.id FROM subject, reviewer RETURNING id
), question_version AS (
  INSERT INTO question_versions (question_id, subject_id, version, stem, response_format,
    marking_method, solution_steps, hints, marks, expected_seconds, option_count,
    content_hash, authored_by, answer_source, mastery_level_number, level_source,
    review_status)
  SELECT question.id, subject.id, 1, 'A question', 'mcq_single', 'auto_key',
    '["first step"]'::jsonb, '["a hint"]'::jsonb, 1, 45, 4, :hash, reviewer.id,
    'expert_verified', 3, 'expert_verified', 'draft'
  FROM question, subject, reviewer RETURNING id
), assessment AS (
  INSERT INTO assessments (subject_id, title, assessment_type, required_pool, status)
  SELECT subject.id, 'Dev cleanup paper', 'checkup', 'practice', 'draft' FROM subject
  RETURNING id
), guardian AS (
  INSERT INTO guardians (display_name, phone) VALUES (:guardian, :phone) RETURNING id
)
SELECT (SELECT id FROM subject) AS subject_id, (SELECT id FROM skill) AS skill_id,
       (SELECT id FROM question_version) AS question_version_id,
       (SELECT id FROM assessment) AS assessment_id,
       (SELECT id FROM guardian) AS guardian_id
"""


@pytest.fixture
async def sandbox(client: httpx.AsyncClient) -> AsyncIterator[dict[str, str]]:
    """A sandbox student with a row in every table that points at a student.

    The student is made through the endpoint under test's own POST, so the `sandbox:` prefix
    is the real one rather than a guess at it.
    """
    if not await database_is_reachable():
        pytest.skip("database unreachable — run `make db-start && make migrate`")
    engine = get_engine()
    suffix = uuid.uuid4().hex[:8]

    async with engine.begin() as conn:
        ids = {
            key: str(value)
            for key, value in (
                (
                    await conn.execute(
                        text(CONTENT),
                        {
                            "reviewer": f"Dev cleanup reviewer {suffix}",
                            "exam_name": f"Dev cleanup exam {suffix}",
                            "short": f"DV{suffix[:5]}",
                            "doc_title": f"Dev cleanup syllabus {suffix}",
                            "doc_uri": f"test://dev/{suffix}",
                            "doc_hash": uuid.uuid4().hex * 2,
                            "label": f"dev-{suffix}",
                            "hash": uuid.uuid4().hex * 2,
                            "guardian": f"Dev cleanup guardian {suffix}",
                            # Digits only: the column checks the shape of a phone number.
                            "phone": f"+234{uuid.uuid4().int % 10**9:09d}",
                        },
                    )
                )
                .mappings()
                .one()
                .items()
            )
        }

    created = await client.post("/v1/dev/students", json={"display_name": f"Doomed {suffix}"})
    assert created.status_code == 200, created.text
    ids["student"] = created.json()["student_id"]
    assert created.json()["external_ref"].startswith(SANDBOX_PREFIX)

    async with engine.begin() as conn:
        # guardian_students, and the consent that points at the link.
        ids["link"] = str(
            (
                await conn.execute(
                    text(
                        """
                        INSERT INTO guardian_students (guardian_id, student_id,
                          relationship_type, status, verified_at)
                        VALUES (CAST(:g AS uuid), CAST(:s AS uuid), 'guardian', 'active', now())
                        RETURNING id
                        """
                    ),
                    {"g": ids["guardian_id"], "s": ids["student"]},
                )
            ).scalar_one()
        )
        await conn.execute(
            text(
                """
                INSERT INTO consents (student_id, consent_type, granted,
                  granted_by_guardian_id, source, evidence_note)
                VALUES (CAST(:s AS uuid), 'research', true, CAST(:link AS uuid), 'guardian_link',
                        'Fixture consent for the cleanup test.')
                """
            ),
            {"s": ids["student"], "link": ids["link"]},
        )
        await conn.execute(
            text(
                """
                INSERT INTO student_exam_goals (student_id, subject_id, target_score,
                  minutes_per_day)
                VALUES (CAST(:s AS uuid), CAST(:sub AS uuid), 70, 45)
                """
            ),
            {"s": ids["student"], "sub": ids["subject_id"]},
        )
        ids["session"] = str(
            (
                await conn.execute(
                    text(
                        """
                        INSERT INTO study_sessions (student_id, subject_id, session_type)
                        VALUES (CAST(:s AS uuid), CAST(:sub AS uuid), 'practice') RETURNING id
                        """
                    ),
                    {"s": ids["student"], "sub": ids["subject_id"]},
                )
            ).scalar_one()
        )
        await conn.execute(
            text(
                """
                INSERT INTO attempts (id, student_id, question_version_id, session_id, context,
                  selected_option_key, is_correct, answered_at_client)
                VALUES (gen_random_uuid(), CAST(:s AS uuid), CAST(:v AS uuid),
                        CAST(:sess AS uuid), 'practice', 'A', true, now())
                """
            ),
            {"s": ids["student"], "v": ids["question_version_id"], "sess": ids["session"]},
        )
        await conn.execute(
            text(
                """
                INSERT INTO tutor_turns (student_id, session_id, question_version_id,
                  step_index, asked, reply, source)
                VALUES (CAST(:s AS uuid), CAST(:sess AS uuid), CAST(:v AS uuid), 0,
                        'why?', 'because.', 'fallback')
                """
            ),
            {"s": ids["student"], "sess": ids["session"], "v": ids["question_version_id"]},
        )
        for table in ("skill_ratings", "review_state"):
            await conn.execute(
                text(
                    f"""
                    INSERT INTO {table} (student_id, skill_id, engine_version)
                    VALUES (CAST(:s AS uuid), CAST(:skill AS uuid), 'test')
                    """
                ),
                {"s": ids["student"], "skill": ids["skill_id"]},
            )
        await conn.execute(
            text(
                """
                INSERT INTO assessment_sittings (assessment_id, student_id, deadline_at)
                VALUES (CAST(:a AS uuid), CAST(:s AS uuid), now() + interval '1 hour')
                """
            ),
            {"a": ids["assessment_id"], "s": ids["student"]},
        )
        # The paper says it was assembled for this student, which is the reference the
        # cleanup has to sever without throwing the paper away.
        await conn.execute(
            text(
                """
                UPDATE assessments SET created_for_student_id = CAST(:s AS uuid)
                 WHERE id = CAST(:a AS uuid)
                """
            ),
            {"s": ids["student"], "a": ids["assessment_id"]},
        )

    yield ids

    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL scorepilot.allow_erasure = 'on'"))
        for statement in (
            "DELETE FROM tutor_turns WHERE student_id = CAST(:student AS uuid)",
            "DELETE FROM attempts WHERE student_id = CAST(:student AS uuid)",
            "DELETE FROM assessment_sittings WHERE student_id = CAST(:student AS uuid)",
            "DELETE FROM study_sessions WHERE student_id = CAST(:student AS uuid)",
            "DELETE FROM student_exam_goals WHERE student_id = CAST(:student AS uuid)",
            "DELETE FROM skill_ratings WHERE student_id = CAST(:student AS uuid)",
            "DELETE FROM review_state WHERE student_id = CAST(:student AS uuid)",
            "DELETE FROM consents WHERE student_id = CAST(:student AS uuid)",
            "DELETE FROM guardian_students WHERE student_id = CAST(:student AS uuid)",
            "UPDATE assessments SET created_for_student_id = NULL "
            "WHERE created_for_student_id = CAST(:student AS uuid)",
            "DELETE FROM students WHERE id = CAST(:student AS uuid)",
            "DELETE FROM guardians WHERE id = CAST(:guardian_id AS uuid)",
            "DELETE FROM assessments WHERE id = CAST(:assessment_id AS uuid)",
            "DELETE FROM question_versions WHERE subject_id = CAST(:subject_id AS uuid)",
            "DELETE FROM questions WHERE subject_id = CAST(:subject_id AS uuid)",
            "DELETE FROM curriculum_items WHERE subject_id = CAST(:subject_id AS uuid) "
            "AND item_type = 'skill'",
            "DELETE FROM curriculum_items WHERE subject_id = CAST(:subject_id AS uuid) "
            "AND item_type = 'subtopic'",
            "DELETE FROM curriculum_items WHERE subject_id = CAST(:subject_id AS uuid)",
            "DELETE FROM syllabus_versions WHERE subject_id = CAST(:subject_id AS uuid)",
            "DELETE FROM source_documents WHERE subject_id = CAST(:subject_id AS uuid)",
            "DELETE FROM subjects WHERE id = CAST(:subject_id AS uuid)",
            "DELETE FROM examinations WHERE short_name = :short",
        ):
            await conn.execute(text(statement), {**ids, "short": f"DV{suffix[:5]}"})


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_a_student_with_a_row_in_every_table_can_still_be_cleared(
    client: httpx.AsyncClient, sandbox: dict[str, str]
) -> None:
    """The regression: a goal alone used to be enough to turn this into a 500."""
    response = await client.delete("/v1/dev/students")
    assert response.status_code == 200, response.text
    assert response.json()["removed"] >= 1

    engine = get_engine()
    async with engine.connect() as conn:
        gone = await conn.scalar(
            text("SELECT count(*) FROM students WHERE id = CAST(:s AS uuid)"),
            {"s": sandbox["student"]},
        )
        assert gone == 0
        for table in (
            "student_exam_goals",
            "study_sessions",
            "attempts",
            "tutor_turns",
            "skill_ratings",
            "review_state",
            "consents",
            "guardian_students",
            "assessment_sittings",
        ):
            left = await conn.scalar(
                text(f"SELECT count(*) FROM {table} WHERE student_id = CAST(:s AS uuid)"),
                {"s": sandbox["student"]},
            )
            assert left == 0, f"{table} still holds rows for a cleared student"
        # The paper outlives the student it was built for; only the attribution goes.
        paper = (
            await conn.execute(
                text(
                    "SELECT created_for_student_id FROM assessments WHERE id = CAST(:a AS uuid)"
                ),
                {"a": sandbox["assessment_id"]},
            )
        ).one_or_none()
        assert paper is not None, "an assessment was deleted; it is content, not evidence"
        assert paper[0] is None


async def test_a_real_student_is_out_of_reach(client: httpx.AsyncClient) -> None:
    """The prefix is the whole safety story, so it gets its own test."""
    if not await database_is_reachable():
        pytest.skip("database unreachable — run `make db-start && make migrate`")
    engine = get_engine()
    suffix = uuid.uuid4().hex[:8]
    async with engine.begin() as conn:
        real = (
            await conn.execute(
                text(
                    """
                    INSERT INTO students (display_name, external_ref, status,
                      requires_guardian_consent)
                    VALUES (:n, :ref, 'active', false) RETURNING id
                    """
                ),
                {"n": f"Real student {suffix}", "ref": f"school:{suffix}"},
            )
        ).scalar_one()

    assert (await client.delete("/v1/dev/students")).status_code == 200

    async with engine.begin() as conn:
        still_here = await conn.scalar(
            text("SELECT count(*) FROM students WHERE id = :s"), {"s": real}
        )
        await conn.execute(text("SET LOCAL scorepilot.allow_erasure = 'on'"))
        await conn.execute(text("DELETE FROM students WHERE id = :s"), {"s": real})
    assert still_here == 1


async def test_every_table_that_points_at_a_student_is_cleared_here() -> None:
    """The guard. A new student-owned table has to be handled here or this fails.

    It reads the catalogue rather than a list written down in this file, so a migration
    cannot add a table that the test does not notice.
    """
    if not await database_is_reachable():
        pytest.skip("database unreachable — run `make db-start && make migrate`")
    engine = get_engine()
    async with engine.connect() as conn:
        referencing = {
            row[0]
            for row in (
                await conn.execute(
                    text(
                        """
                        SELECT DISTINCT cl.relname
                        FROM pg_constraint c
                        JOIN pg_class cl ON cl.oid = c.conrelid
                        WHERE c.contype = 'f'
                          AND c.confrelid = 'students'::regclass
                        """
                    )
                )
            ).all()
        }

    assert referencing, "no foreign keys to students found; the query is wrong, not the schema"

    statement = str(CLEAR_STUDENTS_SQL)
    handled = set(re.findall(r"(?:DELETE FROM|UPDATE)\s+(\w+)", statement))

    missing = referencing - handled
    assert not missing, (
        "these tables reference students but are not cleared by "
        f"clear_students: {sorted(missing)}. Every foreign key into students is ON DELETE "
        "RESTRICT, so DELETE /v1/dev/students will return a 500 for any student holding one "
        "of these rows. Add a CTE for each to CLEAR_STUDENTS_SQL."
    )
