"""Shared test setup.

Each test runs in its own event loop, and the database engine caches connections
bound to the loop that created them. Disposing it between tests keeps a pooled
connection from being reused on a loop that has already closed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from app.db import dispose_engine


@pytest.fixture(autouse=True)
async def _fresh_engine() -> AsyncIterator[None]:
    yield
    await dispose_engine()
