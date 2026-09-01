"""Seam 2 - the Pass state machine, no HTTP.

A stuck Active player Passes instead of guessing (CONTEXT.md: "a turn in which a
player claims no Cell"). Two Passes in immediate succession end the Match as a
draw (issue #7); any claim or wrong guess in between resets the counter. The
HTTP view of the same behaviour lives in ``tests/test_pass_api.py``.
"""

from __future__ import annotations

from app.domain import Cell, Grid, Match, MatchStatus, Player
from app.statemachine import (
    ClaimOutcome,
    PassOutcome,
    RejectionReason,
    claim_cell,
    pass_turn,
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
    status: MatchStatus = MatchStatus.IN_PROGRESS,
    consecutive_passes: int = 0,
    used_pool: frozenset[str] = frozenset(),
) -> Match:
    grid = Grid(
        row_categories=(_ROWS[0].category, _ROWS[1].category, _ROWS[2].category),
        column_categories=(
            _COLS[0].category,
            _COLS[1].category,
            _COLS[2].category,
        ),
        cells=tuple(Cell(row=r, column=c) for r in range(3) for c in range(3)),
    )
    return Match(
        id="m",
        grid=grid,
        active_player=active_player,
        status=status,
        used_pool=used_pool,
        consecutive_passes=consecutive_passes,
    )


# --- a single Pass ---------------------------------------------------


def test_a_pass_on_the_callers_turn_passes_the_turn_and_counts() -> None:
    result = pass_turn(_match(active_player=Player.P1), player=Player.P1)

    assert result.outcome is PassOutcome.PASSED
    assert result.reason is None
    assert result.match.active_player is Player.P2
    assert result.match.consecutive_passes == 1
    assert result.match.status is MatchStatus.IN_PROGRESS


def test_a_pass_leaves_the_input_match_untouched() -> None:
    before = _match(active_player=Player.P1)

    pass_turn(before, player=Player.P1)

    assert before.active_player is Player.P1
    assert before.consecutive_passes == 0
    assert before.status is MatchStatus.IN_PROGRESS


# --- double Pass -> draw ------------------------------------------


def test_two_passes_in_immediate_succession_end_the_match_as_a_draw() -> None:
    first = pass_turn(_match(active_player=Player.P1), player=Player.P1)
    second = pass_turn(first.match, player=Player.P2)

    assert second.outcome is PassOutcome.PASSED
    assert second.match.status is MatchStatus.DRAW
    assert second.match.winner is None


# --- a claim / wrong guess between two Passes resets the counter ----


def test_a_claim_between_two_passes_stops_the_next_pass_drawing() -> None:
    # P1 Passes; P2 claims Cell (0, 0) with "Zoro" (race_a INTERSECT haki_arm);
    # P1 Passes again - a single Pass in this run, so the Match keeps going.
    after_pass = pass_turn(
        _match(active_player=Player.P1), player=Player.P1
    ).match
    after_claim = claim_cell(
        after_pass, _data(), player=Player.P2, row=0, column=0, character="Zoro"
    ).match

    result = pass_turn(after_claim, player=Player.P1)

    assert result.match.status is MatchStatus.IN_PROGRESS


def test_a_wrong_guess_between_two_passes_stops_the_next_pass_drawing() -> None:
    # "Nami" is in race_a (row 0 passes) but not haki_arm (column 0 fails) - a
    # wrong guess, which resets the consecutive-Pass counter.
    after_pass = pass_turn(
        _match(active_player=Player.P1), player=Player.P1
    ).match
    after_wrong = claim_cell(
        after_pass, _data(), player=Player.P2, row=0, column=0, character="Nami"
    ).match

    result = pass_turn(after_wrong, player=Player.P1)

    assert result.match.status is MatchStatus.IN_PROGRESS


def test_an_already_used_guess_between_two_passes_does_not_stop_the_draw() -> None:
    # An already-used Guess claims nothing and does not forfeit the turn, so it
    # is not "a claim or a wrong guess" between the Passes: the run survives it.
    after_pass = pass_turn(
        _match(active_player=Player.P1, used_pool=frozenset({"Zoro"})),
        player=Player.P1,
    ).match
    after_used = claim_cell(
        after_pass, _data(), player=Player.P2, row=0, column=0, character="Zoro"
    )
    assert after_used.outcome is ClaimOutcome.ALREADY_USED

    result = pass_turn(after_used.match, player=Player.P2)

    assert result.match.status is MatchStatus.DRAW


# --- rejected ------------------------------------------------------


def test_a_pass_out_of_turn_is_rejected_with_no_state_change() -> None:
    before = _match(active_player=Player.P1, consecutive_passes=1)

    result = pass_turn(before, player=Player.P2)

    assert result.outcome is PassOutcome.REJECTED
    assert result.reason is RejectionReason.NOT_YOUR_TURN
    assert result.match is before


def test_a_pass_on_a_finished_match_is_rejected_with_no_state_change() -> None:
    ended = _match(status=MatchStatus.DRAW, consecutive_passes=2)

    result = pass_turn(ended, player=Player.P1)

    assert result.outcome is PassOutcome.REJECTED
    assert result.reason is RejectionReason.MATCH_OVER
    assert result.match is ended
