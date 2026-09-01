"""Seam 2 - the storage interface and its in-memory implementation.

Storage is indifferent to how a Grid is built, so these tests use a hand-made
:class:`Match` rather than the real generator.
"""

from __future__ import annotations

from app.domain import (
    Category,
    CategoryGroup,
    Cell,
    Grid,
    Match,
    MatchStatus,
    Player,
)
from app.storage import InMemoryMatchStore


def _match(match_id: str, first_player: Player) -> Match:
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
        cells=tuple(Cell(row=r, column=c) for r in range(3) for c in range(3)),
    )
    return Match(
        id=match_id,
        grid=grid,
        active_player=first_player,
        status=MatchStatus.IN_PROGRESS,
    )


def test_add_then_get_roundtrips_the_match() -> None:
    store = InMemoryMatchStore()
    match = _match("abc", Player.P1)

    store.add(match)

    assert store.get("abc") is match


def test_get_unknown_id_returns_none() -> None:
    assert InMemoryMatchStore().get("nope") is None


def test_add_is_keyed_by_match_id() -> None:
    store = InMemoryMatchStore()
    store.add(_match("one", Player.P1))
    store.add(_match("two", Player.P2))

    assert store.get("one").id == "one"
    assert store.get("two").id == "two"


def test_add_replaces_a_match_with_the_same_id() -> None:
    store = InMemoryMatchStore()
    store.add(_match("dup", Player.P1))
    replacement = _match("dup", Player.P2)

    store.add(replacement)

    assert store.get("dup") is replacement
