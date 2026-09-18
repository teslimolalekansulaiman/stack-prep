"""The student's own endpoints: the catalogue, the goal, and the list of sittings.

The catalogue test is the one that matters. A subject with an approved syllabus and no
approved questions has to appear and say why, because hiding it is how a catalogue comes to
look complete when it is not.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import text

from app.db import database_is_reachable, get_engine
from app.main import app
from app.routers.student import SESSION_MINUTES, sessions_before

pytestmark = pytest.mark.integration


@pytest.fixture
async def fixture() -> AsyncIterator[dict[str, str]]:
    """A student, and an active subject with no approved questions.

    The subject matters as much as the student: the test database is built from migrations
    and holds no seed data, so without one the catalogue is empty and a test asserting on it
    would pass by looking at nothing.
    """
    if not await database_is_reachable():
        pytest.skip("database unreachable — run `make db-start && make migrate`")
    engine = get_engine()
    suffix = uuid.uuid4().hex[:8]
    ids: dict[str, str] = {}
    async with engine.begin() as conn:
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
                    {"n": f"Goal test student {suffix}", "ref": f"test:{suffix}"},
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
                        VALUES (:n, :s, 'Test body', 'NG', 'active') RETURNING id
                        """
                    ),
                    {"n": f"Student test exam {suffix}", "s": f"ST{suffix[:5]}"},
                )
            ).scalar_one()
        )
        ids["subject"] = str(
            (
                await conn.execute(
                    text(
                        """
                        INSERT INTO subjects (examination_id, code, name, status)
                        VALUES (CAST(:e AS uuid), 'STU', 'Student test subject', 'active')
                        RETURNING id
                        """
                    ),
                    {"e": ids["exam"]},
                )
            ).scalar_one()
        )
    yield ids
    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL scorepilot.allow_erasure = 'on'"))
        for statement in (
            "DELETE FROM student_exam_goals WHERE student_id = CAST(:s AS uuid)",
            "DELETE FROM students WHERE id = CAST(:s AS uuid)",
        ):
            await conn.execute(text(statement), {"s": ids["student"]})
        await conn.execute(
            text("DELETE FROM subjects WHERE id = CAST(:x AS uuid)"), {"x": ids["subject"]}
        )
        await conn.execute(
            text("DELETE FROM examinations WHERE id = CAST(:e AS uuid)"), {"e": ids["exam"]}
        )


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def test_a_goal_without_a_date_has_no_runway() -> None:
    """Sessions cannot be counted towards a date that was never given."""
    assert sessions_before(None, 45, [1, 2, 3]) is None
    assert sessions_before(date.today() + timedelta(days=30), None, [1, 2, 3]) is None


def test_a_date_already_past_leaves_no_sessions() -> None:
    assert sessions_before(date.today() - timedelta(days=1), 45, [1, 2, 3, 4, 5]) == 0


def test_the_runway_counts_only_the_days_the_student_named() -> None:
    """Seven days a week is twice the runway of three, on the same calendar."""
    when = date.today() + timedelta(days=70)
    every_day = sessions_before(when, SESSION_MINUTES, [1, 2, 3, 4, 5, 6, 7])
    three_days = sessions_before(when, SESSION_MINUTES, [1, 3, 5])
    assert every_day is not None and three_days is not None
    assert every_day > three_days * 2


def test_a_longer_evening_is_more_than_one_session() -> None:
    when = date.today() + timedelta(days=70)
    short = sessions_before(when, SESSION_MINUTES, [1, 2, 3])
    long = sessions_before(when, SESSION_MINUTES * 2, [1, 2, 3])
    assert short is not None and long is not None
    assert long == short * 2


async def test_the_catalogue_shows_what_is_not_ready_and_why(
    client: httpx.AsyncClient, fixture: dict[str, str]
) -> None:
    response = await client.get("/v1/student/catalogue")
    assert response.status_code == 200, response.text
    subjects = {
        subject["subject_id"]: subject
        for exam in response.json()
        for subject in exam["subjects"]
    }
    mine = subjects[fixture["subject"]]
    # An active subject with no approved questions is listed, not hidden, and says why.
    assert mine["ready"] is False
    assert mine["deliverable_questions"] == 0
    assert mine["blocked_reason"] is not None
    for subject in subjects.values():
        # Ready and blocked are two halves of one statement: exactly one of them holds.
        assert subject["ready"] == (subject["blocked_reason"] is None)


async def test_a_goal_round_trips_and_replaces_itself(
    client: httpx.AsyncClient, fixture: dict[str, str]
) -> None:
    student, subject_id = fixture["student"], fixture["subject"]
    when = (date.today() + timedelta(days=100)).isoformat()

    first = await client.put(
        f"/v1/student/{student}/goals/{subject_id}",
        json={
            "target_score": 70,
            "exam_date": when,
            "minutes_per_day": 45,
            "study_days": [1, 2, 3],
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["sessions_before_exam"] is not None

    # Setting it again replaces the active goal rather than leaving two for a reader to
    # choose between; the database only allows one active goal per subject anyway.
    second = await client.put(
        f"/v1/student/{student}/goals/{subject_id}",
        json={
            "target_score": 85,
            "exam_date": when,
            "minutes_per_day": 90,
            "study_days": [1, 2, 3, 4, 5, 6],
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["target_score"] == 85

    goals = (await client.get(f"/v1/student/{student}/goals")).json()
    assert len(goals) == 1
    assert goals[0]["target_score"] == 85
    assert goals[0]["sessions_before_exam"] > first.json()["sessions_before_exam"]


async def test_a_goal_for_an_unknown_student_is_refused(
    client: httpx.AsyncClient, fixture: dict[str, str]
) -> None:
    response = await client.put(
        f"/v1/student/{uuid.uuid4()}/goals/{fixture['subject']}",
        json={"target_score": 70, "exam_date": date.today().isoformat()},
    )
    assert response.status_code == 404
