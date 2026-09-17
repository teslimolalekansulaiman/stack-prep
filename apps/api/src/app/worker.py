"""Background worker (ADR-0008).

Run with: uv run arq app.worker.WorkerSettings

Jobs must be idempotent: running yesterday's metrics twice produces identical
rows. Scheduled work (item statistics, metrics rollups, review scheduling, mock
repair, digests) is added here as those milestones land.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.config import get_settings
from app.db import database_is_reachable


async def ping(ctx: dict[str, Any]) -> str:
    """Smoke-test job: proves the worker is wired to Redis and the database."""
    return "ok" if await database_is_reachable() else "database unreachable"


class WorkerSettings:
    functions: ClassVar[list[Callable[..., Any]]] = [ping]
    cron_jobs: ClassVar[list[Any]] = []

    @staticmethod
    def redis_settings() -> RedisSettings:
        return RedisSettings.from_dsn(get_settings().redis_url)
