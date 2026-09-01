"""Domain types for a Match.

The vocabulary here is CONTEXT.md's: a **Match** is played on a **Grid** of nine
**Cells**, where every row and every column is a **Category** belonging to one
**Category Group**.

These are pure data types. Real Grid generation lives in :mod:`app.gridgen`; the
claim/Pass state machine lands in a later ticket, so no Cell is ever claimed yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Player(str, Enum):
    """One of the two people playing a Match."""

    P1 = "P1"
    P2 = "P2"


class MatchStatus(str, Enum):
    """Lifecycle of a Match. The won/draw states arrive with the state machine
    in a later ticket; a Match is only ever ``IN_PROGRESS`` here."""

    IN_PROGRESS = "in-progress"


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
    """The 3x3 Grid for a Match: three row Categories, three column Categories,
    and the nine Cells they form (stored row-major)."""

    row_categories: tuple[Category, Category, Category]
    column_categories: tuple[Category, Category, Category]
    cells: tuple[Cell, ...]


@dataclass(frozen=True)
class Match:
    """One complete play session on a single Grid."""

    id: str
    grid: Grid
    active_player: Player
    status: MatchStatus
