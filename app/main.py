"""FastAPI application: create a Match, read its state, and serve the dataset
surface the client legitimately needs.

Run locally with::

    uvicorn app.main:app --reload
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status

from app.dataset import GameData, default_game_data, log_data_quality
from app.gridgen import GridGenerationError, InvalidForcedGridError, new_match
from app.schemas import (
    DataQualityReportOut,
    GuessCreate,
    GuessResult,
    MatchCreate,
    MatchOut,
)
from app.statemachine import claim_cell
from app.storage import InMemoryMatchStore, MatchStore


def create_app(
    store: MatchStore | None = None, game_data: GameData | None = None
) -> FastAPI:
    """Build the app around a :class:`MatchStore` (a fresh in-memory one by
    default) and a :class:`GameData` (the repo dataset by default). Tests pass
    both explicitly to get an isolated store and a small crafted dataset."""

    match_store: MatchStore = store or InMemoryMatchStore()
    data: GameData = game_data if game_data is not None else default_game_data()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Runs when the server actually starts serving, not on every build.
        log_data_quality(data)
        yield

    app = FastAPI(title="One Piece Trivia Tic-Tac-Toe", lifespan=lifespan)

    def get_store() -> MatchStore:
        return match_store

    @app.post(
        "/matches",
        response_model=MatchOut,
        status_code=status.HTTP_201_CREATED,
    )
    def create_match(
        body: MatchCreate | None = None,
        store: MatchStore = Depends(get_store),
    ) -> MatchOut:
        params = body or MatchCreate()
        try:
            match = new_match(
                data, seed=params.seed, category_ids=params.category_ids
            )
        except InvalidForcedGridError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        except GridGenerationError as exc:  # pragma: no cover - pool too thin
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc
        store.add(match)
        return MatchOut.from_domain(match)

    @app.get("/matches/{match_id}", response_model=MatchOut)
    def get_match(
        match_id: str, store: MatchStore = Depends(get_store)
    ) -> MatchOut:
        match = store.get(match_id)
        if match is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
            )
        return MatchOut.from_domain(match)

    @app.post("/matches/{match_id}/guesses", response_model=GuessResult)
    def submit_guess(
        match_id: str,
        body: GuessCreate,
        store: MatchStore = Depends(get_store),
    ) -> GuessResult:
        """Attempt to claim a Cell by naming a Character. Returns exactly one
        outcome (``claimed`` / ``wrong`` / ``already-used`` / ``rejected``) plus
        the Match state after the attempt."""

        match = store.get(match_id)
        if match is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
            )
        result = claim_cell(
            match,
            data,
            player=body.player,
            row=body.row,
            column=body.column,
            character=body.character,
        )
        if result.match is not match:  # nothing to persist for a no-op outcome
            store.add(result.match)
        return GuessResult.from_domain(result)

    @app.get("/roster", response_model=list[str])
    def get_roster() -> list[str]:
        """The Roster as a flat list of canonical Character names, for
        autocomplete. Deliberately excludes the Category-to-Characters answer
        key."""

        return data.roster_names

    @app.get("/diagnostics/data-quality", response_model=DataQualityReportOut)
    def get_data_quality() -> DataQualityReportOut:
        """The data-quality report from the dataset load: Category-referenced
        names that do not resolve to a Roster Character, and Categories excluded
        from play for having too few resolved Characters."""

        return DataQualityReportOut.from_domain(data.report)

    return app


app = create_app()
