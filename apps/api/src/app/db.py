"""Database access: one async engine, explicit SQL (ADR-0006)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.config import Settings, get_settings

_engine: AsyncEngine | None = None


def create_engine(settings: Settings) -> AsyncEngine:
    """Build the engine, pinning every connection's search_path to our schema."""
    return create_async_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        pool_pre_ping=True,
        connect_args={
            "server_settings": {
                "search_path": f"{settings.database_schema},public",
                "application_name": "score-pilot-api",
            }
        },
    )


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings())
    return _engine


async def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def connection() -> AsyncIterator[AsyncConnection]:
    """FastAPI dependency: one connection per request."""
    async with get_engine().connect() as conn:
        yield conn


async def fetch_all(conn: AsyncConnection, sql: str, **params: Any) -> list[dict[str, Any]]:
    result = await conn.execute(text(sql), params)
    return [dict(row) for row in result.mappings()]


async def database_is_reachable() -> bool:
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        return False
    return True
