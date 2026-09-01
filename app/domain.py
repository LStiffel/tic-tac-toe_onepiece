"""Domain types for a Match.

The vocabulary here is CONTEXT.md's: a **Match** is played on a **Grid** of nine
**Cells**, where every row and every column is a **Category** belonging to one
**Category Group**.

This ticket is a skeleton: the Grid is a fixed stub and no Cell is ever claimed.
Real Grid generation and the claim/Pass state machine land in later tickets.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from enum import Enum


class Player(str, Enum):
    """One of the two people playing a Match."""

    P1 = "P1"
    P2 = "P2"


class MatchStatus(str, Enum):
    """Lifecycle of a Match. Only ``IN_PROGRESS`` is reachable in this ticket."""

    IN_PROGRESS = "in-progress"
    WON_BY_P1 = "won-by-p1"
    WON_BY_P2 = "won-by-p2"
    DRAW = "draw"


class CategoryGroup(str, Enum):
    """The twelve top-level clusters a Category belongs to (CONTEXT.md)."""

    BOUNTY = "Bounty"
    RACE = "Race"
    STATUS = "Status"
    AFFILIATION = "Affiliation"
    ORIGIN_SEA = "Origin sea"
    DEVIL_FRUIT = "Devil Fruit"
    HAKI = "Haki"
    HEIGHT = "Height"
    AGE = "Age"
    DEBUT_CHAPTER = "Debut chapter"
    VISITED = "Visited (journey)"
    MISC = "Misc"


@dataclass(frozen=True)
class Category:
    """A trivia predicate over the Roster, paired with its Category Group.

    The answer key (the Characters that satisfy the predicate) is loaded from
    ``categories.json`` in a later ticket and is deliberately absent here.
    """

    id: str
    label: str
    group: CategoryGroup


@dataclass(frozen=True)
class Cell:
    """One position on the Grid, at the intersection of a row and column Category.

    ``claimed_by`` and ``character`` stay ``None`` until a Player claims the Cell
    by naming a Character; every Cell is empty for now.
    """

    row: int  # 0..2
    column: int  # 0..2
    claimed_by: Player | None = None
    character: str | None = None

    @property
    def is_empty(self) -> bool:
        return self.claimed_by is None


@dataclass(frozen=True)
class Grid:
    """The 3x3 board for a Match: three row Categories, three column Categories,
    and the nine Cells they form (stored row-major)."""

    row_categories: tuple[Category, Category, Category]
    column_categories: tuple[Category, Category, Category]
    cells: tuple[Cell, ...]

    def cell(self, row: int, column: int) -> Cell:
        return self.cells[row * 3 + column]


@dataclass(frozen=True)
class Match:
    """One complete play session on a single Grid."""

    id: str
    grid: Grid
    active_player: Player
    status: MatchStatus


# --- Stub Grid -------------------------------------------------------------
#
# A hardcoded set of six Category ids (real ids/labels from categories.json),
# one per Category Group, standing in until Grid generation is implemented.

STUB_ROW_CATEGORIES: tuple[Category, Category, Category] = (
    Category("bounty_100000000", "Bounty ≥ 100,000,000", CategoryGroup.BOUNTY),
    Category("haki_arm", "Can use Armament Haki", CategoryGroup.HAKI),
    Category("origin_East Blue", "Origin: East Blue", CategoryGroup.ORIGIN_SEA),
)

STUB_COLUMN_CATEGORIES: tuple[Category, Category, Category] = (
    Category("df_Zoan", "Devil Fruit type: Zoan", CategoryGroup.DEVIL_FRUIT),
    Category("height_giant", "Height over 500 cm", CategoryGroup.HEIGHT),
    Category("age_60_plus", "Age 60 or older", CategoryGroup.AGE),
)


def _empty_cells() -> tuple[Cell, ...]:
    return tuple(Cell(row=r, column=c) for r in range(3) for c in range(3))


def stub_grid() -> Grid:
    """The fixed placeholder Grid used until real Grid generation lands."""

    return Grid(
        row_categories=STUB_ROW_CATEGORIES,
        column_categories=STUB_COLUMN_CATEGORIES,
        cells=_empty_cells(),
    )


def new_match(
    *, match_id: str | None = None, first_player: Player | None = None
) -> Match:
    """Create a fresh in-progress Match on the stub Grid.

    A game id and the first Player are generated when not supplied; tests pass
    them explicitly to get a deterministic Match.
    """

    return Match(
        id=match_id or uuid.uuid4().hex,
        grid=stub_grid(),
        active_player=first_player or random.choice((Player.P1, Player.P2)),
        status=MatchStatus.IN_PROGRESS,
    )
