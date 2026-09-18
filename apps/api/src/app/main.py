"""Score Pilot API.

Routes are thin: validate, call the engine or SQL, return typed models. Decisions
live in packages/engine so they can be tested and replayed (ADR-0005).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import dispose_engine
from app.routers import (
    checkup,
    curriculum,
    dev,
    health,
    pool,
    practice,
    publishing,
    review,
    student,
)

API_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Score Pilot API",
        version=API_VERSION,
        summary="Adaptive exam preparation: curriculum, practice, mastery and plans",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["content-type", "authorization"],
    )
    app.include_router(health.router)
    app.include_router(curriculum.router)
    app.include_router(review.router)
    app.include_router(publishing.router)
    app.include_router(checkup.router)
    app.include_router(pool.router)
    app.include_router(practice.router)
    app.include_router(student.router)
    # Student creation without a login, for building the student side. The router refuses to
    # answer unless app_env is local or ci, so shipping it is not the same as exposing it.
    app.include_router(dev.router)
    return app


app = create_app()
