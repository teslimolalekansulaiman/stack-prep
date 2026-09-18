"""The guided loop, against the local database.

The tests are about the rules that protect the numbers, not about the wording of a hint. If
one of these breaks, the product has started counting help as knowledge.
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

FIXTURE = """
WITH reviewer AS (
  INSERT INTO academic_reviewers (display_name) VALUES (:author) RETURNING id
), checker AS (
  INSERT INTO academic_reviewers (display_name) VALUES (:reviewer) RETURNING id
), exam AS (
  INSERT INTO examinations (name, short_name, exam_body, country_code, status)
  VALUES (:exam_name, :short, 'Test body', 'NG', 'active') RETURNING id
), subject AS (
  INSERT INTO subjects (examination_id, code, name, status)
  SELECT exam.id, 'PRA', 'Practice subject', 'active' FROM exam RETURNING id, examination_id
), document AS (
  INSERT INTO source_documents (examination_id, subject_id, document_type, title, file_uri,
    file_sha256, mime_type, licence_status, storage_permission, student_delivery_permission,
    review_status, reviewed_by, reviewed_at)
  SELECT subject.examination_id, subject.id, 'syllabus', :doc_title, :doc_uri, :doc_hash,
    'application/pdf', 'verified', true, true, 'approved', checker.id, now()
  FROM subject, checker RETURNING id
), version AS (
  INSERT INTO syllabus_versions (subject_id, version_label, source_document_id, status,
    is_current, approved_by, approved_at)
  SELECT subject.id, :label, document.id, 'approved', true, checker.id, now()
  FROM subject, document, checker RETURNING id, subject_id
), topic AS (
  INSERT INTO curriculum_items (syllabus_version_id, subject_id, item_type, code, name,
    syllabus_status, pilot_support_status, review_status, approved_by, approved_at)
  SELECT version.id, version.subject_id, 'topic', 'PRA.I', 'The topic', 'explicit',
    'supported', 'draft', NULL, NULL
  FROM version, checker RETURNING id, syllabus_version_id, subject_id
), sub AS (
  INSERT INTO curriculum_items (syllabus_version_id, subject_id, parent_id, item_type, code,
    name, syllabus_status, pilot_support_status, review_status, approved_by, approved_at)
  SELECT topic.syllabus_version_id, topic.subject_id, topic.id, 'subtopic', 'PRA.I.1',
    'The subtopic', 'explicit', 'supported', 'draft', NULL, NULL
  FROM topic, checker RETURNING id, syllabus_version_id, subject_id
), skill AS (
  INSERT INTO curriculum_items (syllabus_version_id, subject_id, parent_id, item_type, code,
    name, syllabus_status, pilot_support_status, review_status, approved_by, approved_at)
  SELECT sub.syllabus_version_id, sub.subject_id, sub.id, 'skill', 'PRA.I.1.i', 'The skill',
    'explicit', 'supported', 'draft', NULL, NULL
  FROM sub, checker RETURNING id, subject_id
), evidence AS (
  INSERT INTO curriculum_evidence (curriculum_item_id, source_document_id, evidence_kind,
    source_location, source_excerpt, review_status, reviewed_by, reviewed_at)
  SELECT item.id, document.id, 'inclusion', 'page 1', 'printed', 'approved', checker.id, now()
  FROM (SELECT id FROM topic UNION ALL SELECT id FROM sub UNION ALL SELECT id FROM skill) item,
       document, checker RETURNING id
)
SELECT (SELECT id FROM subject) AS subject_id, (SELECT id FROM skill) AS skill_id,
       (SELECT id FROM version) AS version_id,
       (SELECT id FROM reviewer) AS author_id, (SELECT id FROM checker) AS reviewer_id
"""


@pytest.fixture
async def fixture() -> AsyncIterator[dict[str, str]]:
    if not await database_is_reachable():
        pytest.skip("database unreachable — run `make db-start && make migrate`")
    engine = get_engine()
    suffix = uuid.uuid4().hex[:8]
    async with engine.begin() as conn:
        row = (
            (
                await conn.execute(
                    text(FIXTURE),
                    {
                        "author": f"Practice author {suffix}",
                        "reviewer": f"Practice reviewer {suffix}",
                        "exam_name": f"Practice exam {suffix}",
                        "short": f"PR{suffix[:5]}",
                        "doc_title": f"Practice syllabus {suffix}",
                        "doc_uri": f"test://practice/{suffix}",
                        "doc_hash": uuid.uuid4().hex + uuid.uuid4().hex,
                        "label": f"pra-{suffix}",
                    },
                )
            )
            .mappings()
            .one()
        )
        ids = {key: str(value) for key, value in row.items()}
        # Parents before children: the trigger refuses a child of a draft parent.
        for item_type in ("topic", "subtopic", "skill"):
            await conn.execute(
                text(
                    """
                    UPDATE curriculum_items
                       SET review_status = 'approved', approved_by = CAST(:r AS uuid),
                           approved_at = now()
                     WHERE subject_id = CAST(:s AS uuid) AND item_type = :t
                    """
                ),
                {"s": ids["subject_id"], "t": item_type, "r": ids["reviewer_id"]},
            )
        ids["student"] = str(
            (
                await conn.execute(
                    text(
                        """
                        INSERT INTO students (display_name, external_ref, status,
                          requires_guardian_consent)
                        VALUES (:n, :ref, 'active', false) RETURNING id
                        """
                    ),
                    {"n": f"Practice student {suffix}", "ref": f"test:{suffix}"},
                )
            ).scalar_one()
        )
        # Three deliverable questions, so the loop always has something to offer next.
        for index in range(3):
            question_id = (
                await conn.execute(
                    text(
                        """
                        INSERT INTO questions (subject_id, origin, usage_pool, created_by)
                        VALUES (CAST(:s AS uuid), 'authored', 'practice', CAST(:a AS uuid))
                        RETURNING id
                        """
                    ),
                    {"s": ids["subject_id"], "a": ids["author_id"]},
                )
            ).scalar_one()
            version_id = (
                await conn.execute(
                    text(
                        """
                        INSERT INTO question_versions (question_id, subject_id, version, stem,
                          response_format, marking_method, solution_steps, hints, marks,
                          expected_seconds, option_count, content_hash, authored_by,
                          answer_source, mastery_level_number, level_source, review_status,
                          reviewed_by, reviewed_at)
                        VALUES (:q, CAST(:s AS uuid), 1, :stem, 'mcq_single', 'auto_key',
                          CAST(:steps AS jsonb), CAST(:hints AS jsonb), 1, 45, 4,
                          :hash, CAST(:a AS uuid),
                          'expert_verified', 3, 'expert_verified', 'draft', NULL, NULL)
                        RETURNING id
                        """
                    ),
                    {
                        "q": question_id,
                        "s": ids["subject_id"],
                        "stem": f"Question {index}",
                        "steps": '["first step", "second step"]',
                        "hints": '["the general hint"]',
                        "hash": uuid.uuid4().hex + uuid.uuid4().hex,
                        "a": ids["author_id"],
                        "r": ids["reviewer_id"],
                    },
                )
            ).scalar_one()
            for order, letter in enumerate("ABCD", 1):
                await conn.execute(
                    text(
                        """
                        INSERT INTO question_options (question_version_id, subject_id,
                          option_key, body, is_correct, display_order)
                        VALUES (:v, CAST(:s AS uuid), :k, :b, :correct, :o)
                        """
                    ),
                    {
                        "v": version_id,
                        "s": ids["subject_id"],
                        "k": letter,
                        "b": f"option {letter}",
                        "correct": letter == "A",
                        "o": order,
                    },
                )
            await conn.execute(
                text(
                    """
                    INSERT INTO question_classifications (question_id, subject_id,
                      curriculum_item_id, syllabus_version_id, classification_role,
                      classification_reason, review_status, reviewed_by, reviewed_at,
                      proposed_by)
                    VALUES (:q, CAST(:s AS uuid), CAST(:skill AS uuid), CAST(:ver AS uuid),
                      'primary', 'fixture', 'approved', CAST(:r AS uuid), now(), 'human')
                    """
                ),
                {
                    "q": question_id,
                    "s": ids["subject_id"],
                    "skill": ids["skill_id"],
                    "ver": ids["version_id"],
                    "r": ids["reviewer_id"],
                },
            )
            await conn.execute(
                text("UPDATE questions SET current_version_id = :v WHERE id = :q"),
                {"v": version_id, "q": question_id},
            )
            await conn.execute(
                text(
                    """
                    UPDATE question_versions
                       SET review_status = 'approved', reviewed_by = CAST(:r AS uuid),
                           reviewed_at = now()
                     WHERE id = :v
                    """
                ),
                {"v": version_id, "r": ids["reviewer_id"]},
            )
    yield ids
    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL scorepilot.allow_erasure = 'on'"))
        for statement in (
            "DELETE FROM attempts WHERE student_id = CAST(:student AS uuid)",
            "DELETE FROM study_sessions WHERE student_id = CAST(:student AS uuid)",
            "DELETE FROM students WHERE id = CAST(:student AS uuid)",
            "DELETE FROM question_classifications WHERE subject_id = CAST(:subject_id AS uuid)",
            # Approved content is immutable by design, so a fixture has to withdraw before it
            # can clean up after itself.
            "UPDATE question_versions SET review_status = 'withdrawn' "
            "WHERE subject_id = CAST(:subject_id AS uuid)",
            "DELETE FROM question_options WHERE subject_id = CAST(:subject_id AS uuid)",
            "UPDATE questions SET current_version_id = NULL "
            "WHERE subject_id = CAST(:subject_id AS uuid)",
            "DELETE FROM question_versions WHERE subject_id = CAST(:subject_id AS uuid)",
            "DELETE FROM questions WHERE subject_id = CAST(:subject_id AS uuid)",
            "DELETE FROM curriculum_evidence WHERE curriculum_item_id IN "
            "(SELECT id FROM curriculum_items WHERE subject_id = CAST(:subject_id AS uuid))",
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
            await conn.execute(text(statement), {**ids, "short": f"PR{suffix[:5]}"})


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def start(client: httpx.AsyncClient, ids: dict[str, str], length: int = 3) -> dict:
    response = await client.post(
        "/v1/practice/start",
        json={"student_id": ids["student"], "subject_id": ids["subject_id"], "length": length},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def answer(
    client: httpx.AsyncClient, session: str, state: dict, key: str, confidence: str | None = None
) -> dict:
    response = await client.post(
        f"/v1/practice/{session}/answer",
        json={
            "question_version_id": state["question"]["question_version_id"],
            "selected_option_key": key,
            "response_ms": 9000,
            "confidence": confidence,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_miss_brings_a_hint_and_the_same_question_back(
    client: httpx.AsyncClient, fixture: dict[str, str]
) -> None:
    state = await start(client, fixture)
    asked = state["question"]["question_version_id"]
    state = await answer(client, state["session_id"], state, "B")
    assert state["stage"] == "hint"
    assert state["hint"] == "the general hint"
    # The same question, not the next one: the point is to try again with help.
    assert state["question"]["question_version_id"] == asked
    assert state["question"]["hints_used"] == 1


async def test_a_second_miss_opens_the_board(
    client: httpx.AsyncClient, fixture: dict[str, str]
) -> None:
    state = await start(client, fixture)
    state = await answer(client, state["session_id"], state, "B")
    state = await answer(client, state["session_id"], state, "C")
    assert state["stage"] == "explain"
    assert state["solution_steps"] == ["first step", "second step"]
    assert state["correct_option_key"] == "A"
    assert state["taught"] == 1
    # Taught is not known, and the session's own counters say so.
    assert state["correct_unaided"] == 0


async def test_a_right_answer_after_a_hint_is_not_evidence(
    client: httpx.AsyncClient, fixture: dict[str, str]
) -> None:
    state = await start(client, fixture)
    state = await answer(client, state["session_id"], state, "B")
    state = await answer(client, state["session_id"], state, "A")
    assert state["stage"] == "asking"
    # Right, but with help. It moves the student on and not the estimate.
    assert state["correct_unaided"] == 0


async def test_a_right_answer_the_student_calls_a_guess_is_not_evidence(
    client: httpx.AsyncClient, fixture: dict[str, str]
) -> None:
    state = await start(client, fixture)
    state = await answer(client, state["session_id"], state, "A", confidence="guessed")
    assert state["correct_unaided"] == 0
    state = await answer(client, state["session_id"], state, "A", confidence="sure")
    assert state["correct_unaided"] == 1


async def test_the_ladder_cannot_be_talked_past(
    client: httpx.AsyncClient, fixture: dict[str, str]
) -> None:
    """A client that replays the first wrong answer does not get a second first hint.

    The stage is read from what is stored, so the second miss opens the board however the
    client numbers its calls.
    """
    state = await start(client, fixture)
    first = state
    state = await answer(client, state["session_id"], first, "B")
    assert state["stage"] == "hint"
    state = await answer(client, state["session_id"], first, "B")
    assert state["stage"] == "explain"


async def test_a_session_ends_when_its_questions_are_used_up(
    client: httpx.AsyncClient, fixture: dict[str, str]
) -> None:
    state = await start(client, fixture, length=2)
    for _ in range(2):
        state = await answer(client, state["session_id"], state, "A", confidence="sure")
    assert state["stage"] == "finished"
    assert state["question"] is None
    assert "2 of 2 answered without help" in (state["closing_note"] or "")
