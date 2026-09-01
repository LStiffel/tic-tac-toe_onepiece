# One Piece Trivia Tic-Tac-Toe

A local two-player trivia game built on a One Piece dataset. See `CONTEXT.md` for
the domain vocabulary (Match, Grid, Cell, Category, Category Group, ...) and
`docs/adr/0001-stack-and-state.md` for the stack decision.

This repo is being built ticket by ticket (GitHub Issues on
`LStiffel/tic-tac-toe_onepiece`). Current state: **project scaffold + Match
skeleton** — you can create a Match and read its state back over HTTP. The Grid
is a fixed stub; real Grid generation and the guess/Pass state machine land in
later tickets.

## Requirements

- Python 3.11+

## Setup

```bash
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -e ".[dev]"
```

## Run the server

```bash
uvicorn app.main:app --reload
```

The API is then at <http://127.0.0.1:8000> (interactive docs at `/docs`):

| Method & path            | Purpose                                              |
| ------------------------ | --------------------------------------------------- |
| `POST /matches`          | Create a Match; returns the game id, the stub Grid, the Active player, and status `in-progress`. |
| `GET /matches/{id}`      | Fetch a Match: its Grid, the nine (empty) Cells, the Active player, and status. `404` if the id is unknown. |
| `GET /health`            | Liveness check.                                     |

Match state lives in an in-memory map keyed by game id, reached only through the
`MatchStore` interface (`app/storage.py`), so a database can replace it later
without touching game logic. State is lost when the server stops.

## Tests

```bash
pytest        # full suite
mypy          # type check (app/)
```

See `docs/agents/testing.md` for the two-seam test pattern this suite follows.
