"""Shared fixtures.

The test suite has two seams (see ``docs/agents/testing.md``):

* **Seam 1 - HTTP**: drive the app through FastAPI's ``TestClient`` and assert on
  responses. The ``client`` fixture below is the entry point.
* **Seam 2 - pure functions**: call domain/storage code directly, no HTTP.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.dataset import GameData
from app.domain import (
    Category,
    CategoryGroup,
    Cell,
    Grid,
    Match,
    MatchStatus,
    Player,
)
from app.main import create_app
from app.storage import InMemoryMatchStore


@pytest.fixture
def store() -> InMemoryMatchStore:
    return InMemoryMatchStore()


@pytest.fixture
def build_match() -> Callable[..., Match]:
    """A hand-made in-progress Match on a well-formed 3x3 Grid, for tests that
    do not exercise real Grid generation (storage, wire mapping, ...)."""

    def _build(
        *,
        match_id: str = "m",
        first_player: Player = Player.P1,
        used_pool: frozenset[str] = frozenset(),
    ) -> Match:
        rows = tuple(
            Category(id=f"r{i}", label=f"Row {i}", group=CategoryGroup.RACE)
            for i in range(3)
        )
        columns = tuple(
            Category(id=f"c{i}", label=f"Col {i}", group=CategoryGroup.BOUNTY)
            for i in range(3)
        )
        grid = Grid(
            row_categories=rows,
            column_categories=columns,
            cells=tuple(
                Cell(row=r, column=c) for r in range(3) for c in range(3)
            ),
        )
        return Match(
            id=match_id,
            grid=grid,
            active_player=first_player,
            status=MatchStatus.IN_PROGRESS,
            used_pool=used_pool,
        )

    return _build


@pytest.fixture
def game_data() -> GameData | None:
    """The dataset the ``client`` app is built on. ``None`` means the real repo
    dataset; a test module overrides this fixture to supply a small crafted
    :class:`GameData` instead."""

    return None


@pytest.fixture
def client(
    store: InMemoryMatchStore, game_data: GameData | None
) -> TestClient:
    """A ``TestClient`` backed by a fresh in-memory store per test."""

    return TestClient(create_app(store, game_data))
