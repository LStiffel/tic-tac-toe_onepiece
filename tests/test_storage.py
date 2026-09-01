"""Seam 2 - the storage interface and its in-memory implementation.

Storage is indifferent to how a Grid is built, so these tests use the
``build_match`` fixture rather than the real generator.
"""

from __future__ import annotations

from collections.abc import Callable

from app.domain import Match, Player
from app.storage import InMemoryMatchStore


def test_add_then_get_roundtrips_the_match(
    build_match: Callable[..., Match],
) -> None:
    store = InMemoryMatchStore()
    match = build_match(match_id="abc", first_player=Player.P1)

    store.add(match)

    assert store.get("abc") is match


def test_get_unknown_id_returns_none() -> None:
    assert InMemoryMatchStore().get("nope") is None


def test_add_is_keyed_by_match_id(build_match: Callable[..., Match]) -> None:
    store = InMemoryMatchStore()
    store.add(build_match(match_id="one", first_player=Player.P1))
    store.add(build_match(match_id="two", first_player=Player.P2))

    assert store.get("one").id == "one"
    assert store.get("two").id == "two"


def test_add_replaces_a_match_with_the_same_id(
    build_match: Callable[..., Match],
) -> None:
    store = InMemoryMatchStore()
    store.add(build_match(match_id="dup", first_player=Player.P1))
    replacement = build_match(match_id="dup", first_player=Player.P2)

    store.add(replacement)

    assert store.get("dup") is replacement
