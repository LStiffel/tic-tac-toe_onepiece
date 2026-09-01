"""FastAPI application: create a Match and read its state back.

Run locally with::

    uvicorn app.main:app --reload
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, status

from app.domain import new_match
from app.schemas import MatchOut
from app.storage import InMemoryMatchStore, MatchStore


def create_app(store: MatchStore | None = None) -> FastAPI:
    """Build the app around a :class:`MatchStore` (a fresh in-memory one by
    default). Tests call this per-test to get an isolated store."""

    app = FastAPI(title="One Piece Trivia Tic-Tac-Toe")
    match_store: MatchStore = store or InMemoryMatchStore()
    app.state.match_store = match_store

    def get_store() -> MatchStore:
        return match_store

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/matches",
        response_model=MatchOut,
        status_code=status.HTTP_201_CREATED,
    )
    def create_match(store: MatchStore = Depends(get_store)) -> MatchOut:
        match = new_match()
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

    return app


app = create_app()
