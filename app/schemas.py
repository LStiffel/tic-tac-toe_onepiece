"""Pydantic models for the HTTP surface.

These are the wire shapes only; each carries a ``from_domain`` mapper so the
domain dataclasses never leak FastAPI concerns and vice versa. The nesting
mirrors the domain: a Match has a Grid, a Grid has Categories and Cells.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.dataset import DataQualityReport
from app.domain import Category, Cell, Grid, Match, Player
from app.statemachine import ClaimResult


class MatchCreate(BaseModel):
    """Optional knobs on ``POST /matches``.

    ``seed`` makes Grid generation reproducible. ``category_ids`` forces a
    specific Grid: exactly six Category ids, three rows then three columns; the
    request is rejected if that Grid is unsolvable.
    """

    seed: int | None = None
    category_ids: list[str] | None = None


class GuessCreate(BaseModel):
    """A claim attempt on ``POST /matches/{id}/guesses``: the acting player, the
    Cell coordinates, and the Character named. ``player`` is explicit so the
    server can enforce turn order (``not-your-turn``)."""

    player: Player
    row: int = Field(ge=0, le=2)
    column: int = Field(ge=0, le=2)
    character: str


class CategoryOut(BaseModel):
    id: str
    label: str
    group: str

    @classmethod
    def from_domain(cls, category: Category) -> CategoryOut:
        return cls(id=category.id, label=category.label, group=category.group.value)


class CellOut(BaseModel):
    row: int
    column: int
    claimed_by: str | None = None
    character: str | None = None

    @classmethod
    def from_domain(cls, cell: Cell) -> CellOut:
        return cls(
            row=cell.row,
            column=cell.column,
            claimed_by=cell.claimed_by.value if cell.claimed_by else None,
            character=cell.character,
        )


class GridOut(BaseModel):
    row_categories: list[CategoryOut]
    column_categories: list[CategoryOut]
    cells: list[CellOut]

    @classmethod
    def from_domain(cls, grid: Grid) -> GridOut:
        return cls(
            row_categories=[CategoryOut.from_domain(c) for c in grid.row_categories],
            column_categories=[
                CategoryOut.from_domain(c) for c in grid.column_categories
            ],
            cells=[CellOut.from_domain(c) for c in grid.cells],
        )


class DataQualityReportOut(BaseModel):
    """The diagnostic view of what the dataset load could not resolve.

    ``unresolved`` maps a Category id to the names it referenced that are not in
    the Roster; ``excluded_categories`` lists Categories dropped from play for
    having too few resolved Characters.
    """

    unresolved: dict[str, list[str]]
    excluded_categories: list[str]
    unresolved_name_count: int

    @classmethod
    def from_domain(cls, report: DataQualityReport) -> DataQualityReportOut:
        return cls(
            unresolved={
                category_id: list(names)
                for category_id, names in report.unresolved.items()
            },
            excluded_categories=list(report.excluded_categories),
            unresolved_name_count=report.unresolved_name_count,
        )


class MatchOut(BaseModel):
    """A Match on the wire. ``status`` is ``in-progress`` | ``won`` | ``draw``;
    ``winner`` is ``P1`` / ``P2`` when ``status`` is ``won`` and ``null``
    otherwise, so a completed Match reports its result unambiguously."""

    id: str
    grid: GridOut
    active_player: str
    status: str
    winner: str | None = None
    used_pool: list[str]

    @classmethod
    def from_domain(cls, match: Match) -> MatchOut:
        return cls(
            id=match.id,
            grid=GridOut.from_domain(match.grid),
            active_player=match.active_player.value,
            status=match.status.value,
            winner=match.winner.value if match.winner else None,
            used_pool=sorted(match.used_pool),
        )


class GuessResult(BaseModel):
    """The outcome of a claim attempt plus the Match after it.

    ``outcome`` is ``claimed`` | ``wrong`` | ``already-used`` | ``rejected``.
    ``row`` / ``column`` carry the per-axis ``pass`` / ``fail`` for ``claimed``
    and ``wrong``; ``reason`` carries the rejection reason for ``rejected``.
    """

    outcome: str
    row: str | None = None
    column: str | None = None
    reason: str | None = None
    match: MatchOut

    @classmethod
    def from_domain(cls, result: ClaimResult) -> GuessResult:
        return cls(
            outcome=result.outcome.value,
            row=result.row.value if result.row else None,
            column=result.column.value if result.column else None,
            reason=result.reason.value if result.reason else None,
            match=MatchOut.from_domain(result.match),
        )
