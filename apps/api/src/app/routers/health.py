"""Liveness and version information."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings
from app.db import database_is_reachable
from engine import ENGINE_VERSION

router = APIRouter(tags=["system"])


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    environment: str
    api_version: str
    engine_version: str
    database: Literal["reachable", "unreachable"]


@router.get("/health", response_model=Health, summary="Service health")
async def health() -> Health:
    from app.main import API_VERSION

    reachable = await database_is_reachable()
    return Health(
        status="ok" if reachable else "degraded",
        environment=get_settings().app_env,
        api_version=API_VERSION,
        engine_version=ENGINE_VERSION,
        database="reachable" if reachable else "unreachable",
    )
