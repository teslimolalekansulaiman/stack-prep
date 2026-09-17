"""Apply the numbered SQL migrations in database/migrations (ADR-0006).

Each file runs inside one transaction and is recorded with a checksum, so an
edited migration that has already been applied is reported instead of silently
diverging from the deployed schema.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import asyncpg

from app.config import Settings, get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[4] / "database" / "migrations"

_LEDGER = """
CREATE TABLE IF NOT EXISTS public.schema_migrations (
  version     text PRIMARY KEY,
  checksum    text NOT NULL,
  applied_at  timestamptz NOT NULL DEFAULT now()
)
"""


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode()).hexdigest()


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    return [
        Migration(version=path.stem, path=path, sql=path.read_text())
        for path in sorted(directory.glob("*.sql"))
    ]


def asyncpg_dsn(settings: Settings) -> str:
    """asyncpg wants a plain PostgreSQL URL, not SQLAlchemy's dialect form."""
    return settings.database_url.replace("+asyncpg", "", 1)


async def baseline(settings: Settings | None = None) -> list[str]:
    """Record existing migrations as applied, without running them.

    For a database whose schema was created before this ledger existed (the
    syllabus loader applied the first migrations itself). Returns the versions
    recorded.
    """
    settings = settings or get_settings()
    conn = await asyncpg.connect(asyncpg_dsn(settings))
    recorded: list[str] = []
    try:
        await conn.execute(_LEDGER)
        for migration in discover():
            inserted = await conn.fetchval(
                """
                INSERT INTO public.schema_migrations (version, checksum)
                VALUES ($1, $2)
                ON CONFLICT (version) DO NOTHING
                RETURNING version
                """,
                migration.version,
                migration.checksum,
            )
            if inserted:
                recorded.append(migration.version)
    finally:
        await conn.close()
    return recorded


async def apply_pending(settings: Settings | None = None) -> list[str]:
    """Apply every migration not yet recorded. Returns the versions applied."""
    settings = settings or get_settings()
    conn = await asyncpg.connect(asyncpg_dsn(settings))
    applied: list[str] = []
    try:
        await conn.execute(_LEDGER)
        recorded = {
            row["version"]: row["checksum"]
            for row in await conn.fetch("SELECT version, checksum FROM public.schema_migrations")
        }

        for migration in discover():
            if migration.version in recorded:
                if recorded[migration.version] != migration.checksum:
                    raise RuntimeError(
                        f"{migration.path.name} was edited after it was applied. "
                        "Write a new migration instead."
                    )
                continue

            async with conn.transaction():
                await conn.execute(migration.sql)
                await conn.execute(
                    "INSERT INTO public.schema_migrations (version, checksum) VALUES ($1, $2)",
                    migration.version,
                    migration.checksum,
                )
            applied.append(migration.version)
    finally:
        await conn.close()
    return applied
