"""Runtime configuration, read from the environment (see .env.example)."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["local", "ci", "staging", "production"] = "local"
    log_level: str = "info"

    database_url: str = "postgresql+asyncpg://teslimsulaiman@127.0.0.1:55439/scorepilot"
    database_schema: str = "stackprep"
    database_pool_size: int = 10

    redis_url: str = "redis://127.0.0.1:6379/0"

    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    anthropic_api_key: str = ""
    ai_runtime_model: str = "claude-haiku-4-5-20251001"
    ai_batch_model: str = "claude-sonnet-5"
    ai_daily_calls_per_student: int = Field(default=20, ge=0)

    @field_validator("database_schema")
    @classmethod
    def _schema_is_a_bare_identifier(cls, value: str) -> str:
        # The schema name is interpolated into search_path, so it must not be
        # able to carry anything but an identifier.
        if not _IDENTIFIER.match(value):
            raise ValueError("database_schema must be a lowercase SQL identifier")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
