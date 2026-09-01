"""Pydantic models for the HTTP surface.

These are the wire shapes only; each carries a ``from_domain`` mapper so the
domain dataclasses never leak FastAPI concerns and vice versa.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.domain import Category, Cell, Match


class CategoryOut(BaseModel):
    id: str
    label: str
    group: str

    @classmethod
    def from_domain(cls, category: Category) -> "CategoryOut":
        return cls(id=category.id, label=category.label, group=category.group.value)


class CellOut(BaseModel):
    row: int
    column: int
    claimed_by: str | None = None
    character: str | None = None

    @classmethod
    def from_domain(cls, cell: Cell) -> "CellOut":
        return cls(
            row=cell.row,
            column=cell.column,
            claimed_by=cell.claimed_by.value if cell.claimed_by else None,
            character=cell.character,
        )


class MatchOut(BaseModel):
    id: str
    row_categories: list[CategoryOut]
    column_categories: list[CategoryOut]
    cells: list[CellOut]
    active_player: str
    status: str

    @classmethod
    def from_domain(cls, match: Match) -> "MatchOut":
        grid = match.grid
        return cls(
            id=match.id,
            row_categories=[CategoryOut.from_domain(c) for c in grid.row_categories],
            column_categories=[
                CategoryOut.from_domain(c) for c in grid.column_categories
            ],
            cells=[CellOut.from_domain(c) for c in grid.cells],
            active_player=match.active_player.value,
            status=match.status.value,
        )
