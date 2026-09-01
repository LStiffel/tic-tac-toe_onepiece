"""Seam 2 - the pure domain types, no HTTP.

Grid generation moved to :mod:`app.gridgen` (see ``tests/test_gridgen.py``);
what is left here is the behaviour that lives on the dataclasses themselves.
"""

from __future__ import annotations

from collections.abc import Callable

from app.domain import Cell, Match, MatchStatus, Player


def test_a_fresh_cell_is_empty() -> None:
    cell = Cell(row=0, column=2)

    assert cell.is_empty
    assert cell.claimed_by is None
    assert cell.character is None


def test_a_claimed_cell_is_not_empty() -> None:
    cell = Cell(row=1, column=1, claimed_by=Player.P2, character="Nami")

    assert not cell.is_empty
    assert cell.claimed_by is Player.P2
    assert cell.character == "Nami"


def test_a_match_exposes_its_grid_and_nine_cells(
    build_match: Callable[..., Match],
) -> None:
    match = build_match(match_id="m1", first_player=Player.P1)

    assert match.id == "m1"
    assert match.active_player is Player.P1
    assert match.status is MatchStatus.IN_PROGRESS
    assert len(match.grid.row_categories) == 3
    assert len(match.grid.column_categories) == 3
    assert {(c.row, c.column) for c in match.grid.cells} == {
        (r, c) for r in range(3) for c in range(3)
    }
