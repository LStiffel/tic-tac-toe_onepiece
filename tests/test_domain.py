"""Seam 2 - the pure domain types, no HTTP.

Grid generation moved to :mod:`app.gridgen` (see ``tests/test_gridgen.py``);
what is left here is the shape and semantics of the dataclasses themselves.
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


def test_grid_and_match_hold_the_categories_and_status_they_are_built_with() -> None:
    rows = tuple(
        Category(id=f"r{i}", label=f"Row {i}", group=CategoryGroup.RACE)
        for i in range(3)
    )
    columns = tuple(
        Category(id=f"c{i}", label=f"Col {i}", group=CategoryGroup.BOUNTY)
        for i in range(3)
    )
    cells = tuple(Cell(row=r, column=c) for r in range(3) for c in range(3))
    grid = Grid(row_categories=rows, column_categories=columns, cells=cells)

    match = Match(
        id="m1",
        grid=grid,
        active_player=Player.P1,
        status=MatchStatus.IN_PROGRESS,
    )

    assert match.grid is grid
    assert len(match.grid.cells) == 9
    assert {(c.row, c.column) for c in match.grid.cells} == {
        (r, c) for r in range(3) for c in range(3)
    }
    assert match.status is MatchStatus.IN_PROGRESS
