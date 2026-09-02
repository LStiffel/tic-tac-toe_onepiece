"""FastAPI application: create a Match, read its state, serve the dataset
surface the client legitimately needs, and host the single-screen frontend
(``static/``) at ``/``.

Run locally with::

    uvicorn app.main:app --reload
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from app.dataset import GameData, default_game_data, log_data_quality
from app.domain import Match
from app.gridgen import GridGenerationError, InvalidForcedGridError, new_match
from app.schemas import (
    CharacterOut,
    DataQualityReportOut,
    GuessCreate,
    GuessResult,
    MatchCreate,
    MatchOut,
    PassCreate,
    PassOut,
)
from app.statemachine import claim_cell, pass_turn
from app.storage import InMemoryMatchStore, MatchStore

#: The no-build frontend (issue #9): ``<root>/static`` holds ``index.html`` plus
#: its CSS/JS. Served at ``/`` with the assets mounted under ``/static``; the
#: page talks to the same JSON API the rest of this module exposes.
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

#: ``Cache-Control`` for the frontend assets. ``no-cache`` = the browser may
#: keep a copy but must revalidate before every use; paired with the ``ETag``
#: Starlette sends for ``/static``, an unchanged asset then comes back as a
#: cheap 304. Without it a browser holding an earlier screen kept running a
#: stale ``app.js`` — no Pass / Rematch wiring — for the whole Match (issue #13).
_ASSET_CACHE_CONTROL = "no-cache"


class RevalidatedStaticFiles(StaticFiles):
    """A ``/static`` mount that stamps every response — 200 or 304 — with
    ``Cache-Control: no-cache`` (see ``_ASSET_CACHE_CONTROL``)."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = _ASSET_CACHE_CONTROL
        return response


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

    def generate_match(params: MatchCreate) -> Match:
        """A fresh in-progress Match on a newly generated Grid, mapping the
        Grid-generation failures onto HTTP status codes. Shared by ``POST
        /matches`` and ``POST /matches/{id}/rematch`` so both create a Match the
        exact same way."""

        try:
            return new_match(
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

    @app.post(
        "/matches",
        response_model=MatchOut,
        status_code=status.HTTP_201_CREATED,
    )
    def create_match(
        body: MatchCreate | None = None,
        store: MatchStore = Depends(get_store),
    ) -> MatchOut:
        match = generate_match(body or MatchCreate())
        store.add(match)
        return MatchOut.from_domain(match)

    @app.post(
        "/matches/{match_id}/rematch",
        response_model=MatchOut,
        status_code=status.HTTP_201_CREATED,
    )
    def rematch(
        match_id: str,
        body: MatchCreate | None = None,
        store: MatchStore = Depends(get_store),
    ) -> MatchOut:
        """Start a fresh Match from an existing one (issue #8): a newly generated
        Grid, an empty Used pool, a zeroed consecutive-Pass counter and a first
        player chosen anew at random. The new Match gets its own id and is stored
        alongside the source Match, which is left untouched (its id may simply be
        dropped by the client). 404 if the source Match id is unknown."""

        if store.get(match_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
            )
        match = generate_match(body or MatchCreate())
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

    @app.post("/matches/{match_id}/passes", response_model=PassOut)
    def submit_pass(
        match_id: str,
        body: PassCreate,
        store: MatchStore = Depends(get_store),
    ) -> PassOut:
        """Pass the turn without attempting a Cell. Two Passes in immediate
        succession end the Match as a ``draw`` (issue #7); a Pass out of turn or
        on a finished Match is ``rejected`` with no state change."""

        match = store.get(match_id)
        if match is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
            )
        result = pass_turn(match, player=body.player)
        if result.match is not match:  # nothing to persist for a rejected Pass
            store.add(result.match)
        return PassOut.from_domain(result)

    @app.get("/roster", response_model=list[str])
    def get_roster() -> list[str]:
        """The Roster as a flat list of canonical Character names, for
        autocomplete. Deliberately excludes the Category-to-Characters answer
        key."""

        return data.roster_names

    @app.get("/characters", response_model=list[CharacterOut])
    def get_characters() -> list[CharacterOut]:
        """The Roster as ``{name, image}`` records, sorted by name, for the
        Character-art ``<img>`` tags (issue #10). ``image`` is ``""`` when the
        dataset has no art for that Character; the client shows a placeholder for
        both an empty path and a 404. Like ``/roster`` it excludes the
        Category-to-Characters answer key."""

        return [
            CharacterOut(name=name, image=image)
            for name, image in data.character_art
        ]

    @app.get("/diagnostics/data-quality", response_model=DataQualityReportOut)
    def get_data_quality() -> DataQualityReportOut:
        """The data-quality report from the dataset load: Category-referenced
        names that do not resolve to a Roster Character, and Categories excluded
        from play for having too few resolved Characters."""

        return DataQualityReportOut.from_domain(data.report)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        """Serve the single-screen frontend: the Grid, the turn indicator, the
        Cell-selection + autocomplete input and the feedback line (issue #9).
        ``no-cache`` so the page — and the ``app.js`` it pulls — is re-fetched
        on every load rather than served stale from an earlier screen (#13)."""

        return FileResponse(
            _STATIC_DIR / "index.html",
            headers={"Cache-Control": _ASSET_CACHE_CONTROL},
        )

    app.mount(
        "/static",
        RevalidatedStaticFiles(directory=str(_STATIC_DIR)),
        name="static",
    )

    return app


app = create_app()
