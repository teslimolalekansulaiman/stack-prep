"""Curriculum reads against the local database.

Needs the cluster from `make db-start` with migrations applied; skipped otherwise.
"""

from __future__ import annotations

import httpx
import pytest

from app.db import database_is_reachable
from app.main import app

pytestmark = pytest.mark.integration


@pytest.fixture
async def client() -> httpx.AsyncClient:
    if not await database_is_reachable():
        pytest.skip("database unreachable — run `make db-start && make migrate`")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_subjects_carry_their_examination(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/curriculum/subjects")

    assert response.status_code == 200
    for subject in response.json():
        assert subject["examination"]
        assert len(subject["country_code"]) == 2


async def test_items_can_be_filtered_by_type(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/curriculum/items", params={"item_type": "topic", "limit": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 5
    assert len(body["items"]) <= 5
    assert all(item["item_type"] == "topic" for item in body["items"])


async def test_unknown_item_type_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/curriculum/items", params={"item_type": "chapter"})

    assert response.status_code == 422
