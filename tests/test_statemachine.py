"""Seam 2 - the claim state machine, no HTTP.

A small crafted :class:`GameData` and a hand-built in-progress :class:`Match` so
every "does this Character fit this Cell" assertion is exact (see
``docs/agents/testing.md``). The HTTP view of the same behaviour lives in
``tests/test_claim_api.py``.
"""

from __future__ import annotations

import pytest

from app.domain import Cell, Grid, Match, MatchStatus, Player
from app.statemachine import (
    AxisResult,
    ClaimOutcome,
    RejectionReason,
    claim_cell,
)
from tests.support import CRAFTED_CATEGORIES, crafted_game_data

# The crafted universe (see ``tests/support.py``): row Categories are the first
# three, column Categories the last three.
_ROWS = CRAFTED_CATEGORIES[:3]
_COLS = CRAFTED_CATEGORIES[3:]

_data = crafted_game_data


def _match(
    *,
    active_player: Player = Player.P1,
    used_pool: frozenset[str] = frozenset(),
    status: MatchStatus = MatchStatus.IN_PROGRESS,
) -> Match:
    grid = Grid(
        row_categories=(_ROWS[0].category, _ROWS[1].category, _ROWS[2].category),
        column_categories=(_COLS[0].category, _COLS[1].category, _COLS[2].category),
        cells=tuple(Cell(row=r, column=c) for r in range(3) for c in range(3)),
    )
    return Match(
        id="m",
        grid=grid,
        active_player=active_player,
        status=status,
        used_pool=used_pool,
    )


def _cell(match: Match, row: int, column: int) -> Cell:
    return next(
        c for c in match.grid.cells if c.row == row and c.column == column
    )


# --- claimed -----------------------------------------------------------


def test_correct_guess_claims_the_cell_for_the_active_player() -> None:
    # Cell (0, 0) is race_a INTERSECT haki_arm = {"Luffy", "Zoro"}.
    result = claim_cell(
        _match(active_player=Player.P1),
        _data(),
        player=Player.P1,
        row=0,
        column=0,
        character="Zoro",
    )

    assert result.outcome is ClaimOutcome.CLAIMED
    assert result.row is AxisResult.PASS
    assert result.column is AxisResult.PASS
    claimed = _cell(result.match, 0, 0)
    assert claimed.claimed_by is Player.P1
    assert claimed.character == "Zoro"


def test_correct_guess_adds_the_character_to_the_used_pool_and_passes_turn() -> None:
    result = claim_cell(
        _match(active_player=Player.P1),
        _data(),
        player=Player.P1,
        row=0,
        column=0,
        character="Zoro",
    )

    assert result.match.used_pool == frozenset({"Zoro"})
    assert result.match.active_player is Player.P2
    assert result.match.status is MatchStatus.IN_PROGRESS


def test_a_claim_leaves_the_input_match_untouched() -> None:
    before = _match(active_player=Player.P1)

    claim_cell(
        before,
        _data(),
        player=Player.P1,
        row=0,
        column=0,
        character="Zoro",
    )

    assert before.used_pool == frozenset()
    assert before.active_player is Player.P1
    assert all(cell.is_empty for cell in before.grid.cells)


def test_canonicalises_the_named_character_before_matching() -> None:
    result = claim_cell(
        _match(active_player=Player.P1),
        _data(),
        player=Player.P1,
        row=0,
        column=0,
        character="  Zoro ",
    )

    assert result.outcome is ClaimOutcome.CLAIMED
    assert _cell(result.match, 0, 0).character == "Zoro"
    assert result.match.used_pool == frozenset({"Zoro"})


# --- wrong -----------------------------------------------------------


def test_wrong_guess_reports_per_axis_and_forfeits_the_turn() -> None:
    # Cell (0, 1) is race_a INTERSECT df_para = {"Luffy"}. "Nami" is in race_a
    # (row passes) but not df_para (column fails).
    result = claim_cell(
        _match(active_player=Player.P1),
        _data(),
        player=Player.P1,
        row=0,
        column=1,
        character="Nami",
    )

    assert result.outcome is ClaimOutcome.WRONG
    assert result.row is AxisResult.PASS
    assert result.column is AxisResult.FAIL
    assert result.match.active_player is Player.P2


def test_wrong_guess_can_fail_the_row_axis() -> None:
    # Cell (0, 0) is race_a INTERSECT haki_arm. "Robin" is in haki_arm (column
    # passes) but not race_a (row fails).
    result = claim_cell(
        _match(active_player=Player.P1),
        _data(),
        player=Player.P1,
        row=0,
        column=0,
        character="Robin",
    )

    assert result.outcome is ClaimOutcome.WRONG
    assert result.row is AxisResult.FAIL
    assert result.column is AxisResult.PASS


def test_wrong_guess_does_not_add_the_character_to_the_used_pool() -> None:
    result = claim_cell(
        _match(active_player=Player.P1),
        _data(),
        player=Player.P1,
        row=0,
        column=1,
        character="Nami",
    )

    assert result.match.used_pool == frozenset()
    assert all(cell.is_empty for cell in result.match.grid.cells)


# --- already-used --------------------------------------------------


def test_already_used_character_is_distinct_from_wrong_and_keeps_the_turn() -> None:
    result = claim_cell(
        _match(active_player=Player.P1, used_pool=frozenset({"Zoro"})),
        _data(),
        player=Player.P1,
        row=0,
        column=0,
        character="Zoro",
    )

    assert result.outcome is ClaimOutcome.ALREADY_USED
    assert result.row is None and result.column is None
    assert result.match.active_player is Player.P1
    assert result.match.used_pool == frozenset({"Zoro"})
    assert all(cell.is_empty for cell in result.match.grid.cells)


def test_already_used_check_ignores_whether_the_character_fits() -> None:
    # "Franky" is not in race_a and not in haki_arm - a category miss - but it
    # is already used, and that verdict wins.
    result = claim_cell(
        _match(active_player=Player.P1, used_pool=frozenset({"Franky"})),
        _data(),
        player=Player.P1,
        row=0,
        column=0,
        character="Franky",
    )

    assert result.outcome is ClaimOutcome.ALREADY_USED


# --- rejected ----------------------------------------------------------


def test_acting_out_of_turn_is_rejected_with_no_state_change() -> None:
    before = _match(active_player=Player.P1)

    result = claim_cell(
        before,
        _data(),
        player=Player.P2,
        row=0,
        column=0,
        character="Zoro",
    )

    assert result.outcome is ClaimOutcome.REJECTED
    assert result.reason is RejectionReason.NOT_YOUR_TURN
    assert result.match is before


def test_claiming_a_taken_cell_is_rejected() -> None:
    first = claim_cell(
        _match(active_player=Player.P1),
        _data(),
        player=Player.P1,
        row=0,
        column=0,
        character="Zoro",
    )

    result = claim_cell(
        first.match,
        _data(),
        player=Player.P2,
        row=0,
        column=0,
        character="Luffy",
    )

    assert result.outcome is ClaimOutcome.REJECTED
    assert result.reason is RejectionReason.CELL_TAKEN
    assert result.match is first.match


def test_naming_a_character_absent_from_the_roster_is_rejected() -> None:
    before = _match(active_player=Player.P1)

    result = claim_cell(
        before,
        _data(),
        player=Player.P1,
        row=0,
        column=0,
        character="Shanks",
    )

    assert result.outcome is ClaimOutcome.REJECTED
    assert result.reason is RejectionReason.UNKNOWN_CHARACTER
    assert result.match is before


@pytest.mark.parametrize("bad_name", ["", "   ", "not a character"])
def test_unknown_character_reason_covers_blank_and_junk_input(bad_name: str) -> None:
    result = claim_cell(
        _match(active_player=Player.P1),
        _data(),
        player=Player.P1,
        row=1,
        column=1,
        character=bad_name,
    )

    assert result.outcome is ClaimOutcome.REJECTED
    assert result.reason is RejectionReason.UNKNOWN_CHARACTER
