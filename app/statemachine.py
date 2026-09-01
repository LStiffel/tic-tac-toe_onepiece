"""The claim state machine: an Active player attempts to claim a Cell.

:func:`claim_cell` is a pure function - it takes a :class:`~app.domain.Match`
and returns a :class:`ClaimResult` carrying one outcome plus the Match that
results (the same, unchanged Match when the attempt changes nothing). The
frozen domain dataclasses are never mutated.

The outcomes are CONTEXT.md's and the v1 spec's (issue #5):

* ``claimed`` - the canonical Character is in both the row Category's and the
  column Category's resolved set. The Cell is marked for the Active player, the
  Character joins the Used pool, the consecutive-Pass counter resets, and the
  turn passes.
* ``wrong`` - the Character fails at least one axis. ``row`` / ``column`` report
  ``pass`` / ``fail`` per axis. The turn is forfeited (passes to the other
  player), the Character is *not* added to the Used pool, and the
  consecutive-Pass counter resets - a wrong guess is not a Pass.
* ``already-used`` - the Character is already in the Used pool. The turn is
  *not* forfeited and nothing changes.
* ``rejected`` with a :class:`RejectionReason` - ``not-your-turn``,
  ``cell-taken``, ``match-over`` or ``unknown-character``. Nothing changes.

After a ``claimed`` outcome the Match is resolved (issue #6): if the claim
completed one of the eight Lines the Match ends ``won`` by that player, and if
it filled the Grid with no Line the Match ends in a ``draw``. Both are terminal
- any later Guess on a finished Match is ``rejected`` with ``match-over``.

:func:`pass_turn` (issue #7) is the other way a turn ends: a stuck Active player
Passes instead of guessing. A Pass is accepted only on the caller's turn and
while the Match is in progress (otherwise ``rejected`` with ``not-your-turn`` or
``match-over`` and no state change). Each accepted Pass increments
``consecutive_passes`` and hands the turn over; the second Pass in immediate
succession ends the Match in a ``draw``. Only *immediate* succession counts: a
``claimed`` or ``wrong`` outcome resets ``consecutive_passes`` to zero in
:func:`claim_cell`, which is the sole place that counter is reset.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from app.dataset import GameData, canonical_name
from app.domain import Cell, Grid, Match, MatchStatus, Player


class ClaimOutcome(str, Enum):
    """The one outcome a claim attempt produces."""

    CLAIMED = "claimed"
    WRONG = "wrong"
    ALREADY_USED = "already-used"
    REJECTED = "rejected"


class RejectionReason(str, Enum):
    """Why a claim attempt was ``rejected`` without touching Match state."""

    NOT_YOUR_TURN = "not-your-turn"
    CELL_TAKEN = "cell-taken"
    MATCH_OVER = "match-over"
    UNKNOWN_CHARACTER = "unknown-character"


class AxisResult(str, Enum):
    """Whether the named Character satisfies one axis (row or column) of a Cell."""

    PASS = "pass"
    FAIL = "fail"


class PassOutcome(str, Enum):
    """The one outcome a :func:`pass_turn` attempt produces."""

    PASSED = "passed"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ClaimResult:
    """The outcome of :func:`claim_cell` plus the resulting Match.

    ``row`` / ``column`` are set for ``claimed`` and ``wrong`` (the per-axis
    verdict); ``reason`` is set for ``rejected``. ``match`` is the Match after
    the attempt - identical to the input for ``rejected`` and ``already-used``.
    """

    outcome: ClaimOutcome
    match: Match
    row: AxisResult | None = None
    column: AxisResult | None = None
    reason: RejectionReason | None = None


@dataclass(frozen=True)
class PassResult:
    """The outcome of :func:`pass_turn` plus the resulting Match.

    ``reason`` is set only for ``rejected`` (``not-your-turn`` or ``match-over``),
    where ``match`` is the unchanged input. For ``passed`` the returned ``match``
    has the turn handed over and ``consecutive_passes`` incremented - and its
    ``status`` is ``draw`` when this was the second Pass in a row.
    """

    outcome: PassOutcome
    match: Match
    reason: RejectionReason | None = None


#: The Grid is 3x3; Cells are stored row-major (see :mod:`app.gridgen`).
_GRID_SIZE = 3

#: Two Passes in immediate succession end the Match as a draw (CONTEXT.md).
_PASSES_FOR_DRAW = 2

#: The eight Lines, as triples of row-major Cell indices: three rows, three
#: columns, then the two diagonals.
_LINES: tuple[tuple[int, int, int], ...] = (
    (0, 1, 2),
    (3, 4, 5),
    (6, 7, 8),
    (0, 3, 6),
    (1, 4, 7),
    (2, 5, 8),
    (0, 4, 8),
    (2, 4, 6),
)


def _other(player: Player) -> Player:
    return Player.P2 if player is Player.P1 else Player.P1


def _turn_rejection(match: Match, player: Player) -> RejectionReason | None:
    """Why ``player`` may not act on ``match`` right now - ``match-over`` if the
    Match is finished, else ``not-your-turn`` if it is the other player's turn -
    or ``None`` when the turn is theirs to take.

    Shared by :func:`claim_cell` and :func:`pass_turn` so the two entry points
    reject in the same order (Match state before turn order)."""

    if match.status is not MatchStatus.IN_PROGRESS:
        return RejectionReason.MATCH_OVER
    if player is not match.active_player:
        return RejectionReason.NOT_YOUR_TURN
    return None


def winning_player(grid: Grid) -> Player | None:
    """The Player who holds a full Line on ``grid`` - three Cells claimed by the
    same Player across any row, column or diagonal - or ``None`` if no Line is
    complete. The first Line found wins; a well-formed Match can only ever have
    one."""

    for a, b, c in _LINES:
        owner = grid.cells[a].claimed_by
        if (
            owner is not None
            and grid.cells[b].claimed_by is owner
            and grid.cells[c].claimed_by is owner
        ):
            return owner
    return None


def _resolve(match: Match) -> Match:
    """``match`` with its terminal status applied after a claim: ``WON`` (with
    ``winner``) if a Line is now complete, ``DRAW`` if every Cell is claimed and
    no Line is, otherwise ``match`` unchanged."""

    winner = winning_player(match.grid)
    if winner is not None:
        return replace(match, status=MatchStatus.WON, winner=winner)
    if all(not cell.is_empty for cell in match.grid.cells):
        return replace(match, status=MatchStatus.DRAW)
    return match


def _cell_index(row: int, column: int) -> int:
    return row * _GRID_SIZE + column


def _cell_at(grid: Grid, row: int, column: int) -> Cell:
    """The Cell at ``(row, column)`` - a direct index into the row-major Cells."""

    return grid.cells[_cell_index(row, column)]


def _with_claim(
    match: Match, row: int, column: int, player: Player, character: str
) -> Match:
    """A copy of ``match`` with the Cell claimed, the Character in the Used
    pool, the Pass counter reset, and the turn passed."""

    cells = list(match.grid.cells)
    index = _cell_index(row, column)
    cells[index] = replace(
        cells[index], claimed_by=player, character=character
    )
    return replace(
        match,
        grid=replace(match.grid, cells=tuple(cells)),
        active_player=_other(player),
        used_pool=match.used_pool | {character},
        consecutive_passes=0,
    )


def claim_cell(
    match: Match,
    data: GameData,
    *,
    player: Player,
    row: int,
    column: int,
    character: str,
) -> ClaimResult:
    """Resolve ``player``'s attempt to claim Cell ``(row, column)`` by naming
    ``character``. See the module docstring for the full outcome table."""

    rejection = _turn_rejection(match, player)
    if rejection is not None:
        return ClaimResult(ClaimOutcome.REJECTED, match, reason=rejection)
    if not _cell_at(match.grid, row, column).is_empty:
        return ClaimResult(
            ClaimOutcome.REJECTED, match, reason=RejectionReason.CELL_TAKEN
        )

    name = canonical_name(character)
    if name not in data.roster:
        return ClaimResult(
            ClaimOutcome.REJECTED,
            match,
            reason=RejectionReason.UNKNOWN_CHARACTER,
        )
    if name in match.used_pool:
        return ClaimResult(ClaimOutcome.ALREADY_USED, match)

    resolved = {lc.category.id: lc.characters for lc in data.categories}
    # Every Grid Category is a playable, loaded Category (validated at Match
    # creation), so a missing id here is a bug worth surfacing, not a silent
    # fail.
    row_ok = name in resolved[match.grid.row_categories[row].id]
    column_ok = name in resolved[match.grid.column_categories[column].id]
    row_result = AxisResult.PASS if row_ok else AxisResult.FAIL
    column_result = AxisResult.PASS if column_ok else AxisResult.FAIL

    if row_ok and column_ok:
        return ClaimResult(
            ClaimOutcome.CLAIMED,
            _resolve(_with_claim(match, row, column, player, name)),
            row=row_result,
            column=column_result,
        )

    return ClaimResult(
        ClaimOutcome.WRONG,
        replace(match, active_player=_other(player), consecutive_passes=0),
        row=row_result,
        column=column_result,
    )


def pass_turn(match: Match, *, player: Player) -> PassResult:
    """Resolve ``player``'s Pass - a turn in which they claim no Cell. See the
    module docstring for when a Pass is ``rejected`` and how the
    consecutive-Pass counter drives the double-Pass ``draw``."""

    rejection = _turn_rejection(match, player)
    if rejection is not None:
        return PassResult(PassOutcome.REJECTED, match, reason=rejection)

    passes = match.consecutive_passes + 1
    passed = replace(
        match, active_player=_other(player), consecutive_passes=passes
    )
    if passes >= _PASSES_FOR_DRAW:
        passed = replace(passed, status=MatchStatus.DRAW)
    return PassResult(PassOutcome.PASSED, passed)
