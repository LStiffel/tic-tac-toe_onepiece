"""Shared fixtures.

The test suite has two seams (see ``docs/agents/testing.md``):

* **Seam 1 - HTTP**: drive the app through FastAPI's ``TestClient`` and assert on
  responses. The ``client`` fixture below is the entry point.
* **Seam 2 - pure functions**: call domain/storage code directly, no HTTP.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.storage import InMemoryMatchStore


@pytest.fixture
def store() -> InMemoryMatchStore:
    return InMemoryMatchStore()


@pytest.fixture
def client(store: InMemoryMatchStore) -> TestClient:
    """A ``TestClient`` backed by a fresh in-memory store per test."""

    return TestClient(create_app(store))
