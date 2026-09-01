"""Seam 2 - the storage interface and its in-memory implementation."""

from __future__ import annotations

from app.domain import Player, new_match
from app.storage import InMemoryMatchStore


def test_add_then_get_roundtrips_the_match() -> None:
    store = InMemoryMatchStore()
    match = new_match(match_id="abc", first_player=Player.P1)

    store.add(match)

    assert store.get("abc") is match


def test_get_unknown_id_returns_none() -> None:
    assert InMemoryMatchStore().get("nope") is None


def test_add_is_keyed_by_match_id() -> None:
    store = InMemoryMatchStore()
    store.add(new_match(match_id="one", first_player=Player.P1))
    store.add(new_match(match_id="two", first_player=Player.P2))

    assert store.get("one").id == "one"
    assert store.get("two").id == "two"


def test_add_replaces_a_match_with_the_same_id() -> None:
    store = InMemoryMatchStore()
    store.add(new_match(match_id="dup", first_player=Player.P1))
    replacement = new_match(match_id="dup", first_player=Player.P2)

    store.add(replacement)

    assert store.get("dup") is replacement
