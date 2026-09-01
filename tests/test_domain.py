"""Seam 2 - pure domain functions, no HTTP."""

from __future__ import annotations

from app.domain import (
    CategoryGroup,
    MatchStatus,
    Player,
    new_match,
    stub_grid,
)


def test_new_match_is_in_progress_with_the_given_first_player() -> None:
    match = new_match(match_id="fixed", first_player=Player.P1)

    assert match.id == "fixed"
    assert match.active_player is Player.P1
    assert match.status is MatchStatus.IN_PROGRESS


def test_new_match_builds_nine_distinct_empty_cells() -> None:
    grid = new_match(first_player=Player.P1).grid

    assert len(grid.cells) == 9
    assert {(c.row, c.column) for c in grid.cells} == {
        (r, c) for r in range(3) for c in range(3)
    }
    assert all(cell.is_empty for cell in grid.cells)
    assert all(cell.claimed_by is None for cell in grid.cells)


def test_stub_grid_has_three_row_and_three_column_categories_each_with_a_group() -> None:
    grid = stub_grid()

    assert len(grid.row_categories) == 3
    assert len(grid.column_categories) == 3
    for category in grid.row_categories + grid.column_categories:
        assert category.id
        assert category.label
        assert isinstance(category.group, CategoryGroup)


def test_stub_grid_categories_span_six_distinct_groups() -> None:
    grid = stub_grid()

    groups = [c.group for c in grid.row_categories + grid.column_categories]
    assert len(set(groups)) == 6


def test_new_match_generates_a_unique_id_when_none_given() -> None:
    assert new_match().id != new_match().id
