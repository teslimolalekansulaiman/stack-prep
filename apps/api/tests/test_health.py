"""The health endpoint answers even when the database is down."""

from __future__ import annotations

import httpx
import pytest

from app.main import app
from engine import ENGINE_VERSION


@pytest.fixture
async def client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_health_reports_versions(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["engine_version"] == ENGINE_VERSION
    assert body["api_version"]
    assert body["database"] in {"reachable", "unreachable"}
    assert body["status"] == ("ok" if body["database"] == "reachable" else "degraded")


async def test_openapi_schema_is_generated(client: httpx.AsyncClient) -> None:
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/health" in paths
    assert "/v1/curriculum/subjects" in paths
