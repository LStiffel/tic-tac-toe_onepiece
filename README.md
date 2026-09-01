# One Piece Trivia Tic-Tac-Toe

A local two-player trivia game built on a One Piece dataset. See `CONTEXT.md` for
the domain vocabulary (Match, Grid, Cell, Category, Category Group, ...) and
`docs/adr/0001-stack-and-state.md` for the stack decision.

This repo is being built ticket by ticket (GitHub Issues on
`LStiffel/tic-tac-toe_onepiece`). Current state: **project scaffold + Match
skeleton + dataset loading** — you can create a Match and read its state back
over HTTP, and the server loads the One Piece dataset at startup into a Roster
and a set of playable Categories. The Grid is still a fixed stub; real Grid
generation and the guess/Pass state machine land in later tickets.

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
| `POST /matches`          | Create a Match; returns the match id, the stub Grid (3 row + 3 column Categories, nine Cells), the Active player, and status `in-progress`. |
| `GET /matches/{id}`      | Fetch a Match: its `grid` (Categories + the nine empty Cells), the Active player, and status. `404` if the id is unknown. |
| `GET /roster`            | The Roster as a flat, sorted list of canonical Character names, for client-side autocomplete. Excludes the Category-to-Characters answer key. |
| `GET /diagnostics/data-quality` | The data-quality report from the dataset load: Category-referenced names that do not resolve to a Roster Character, and Categories excluded from play for having fewer than three resolved Characters. |

Match state lives in an in-memory map keyed by match id, reached only through the
`MatchStore` interface (`app/storage.py`), so a database can replace it later
without touching game logic. State is lost when the server stops.

At startup the server loads `characters.json` and `categories.json` once
(`app/dataset.py`). The **Roster** is every Character from `characters.json`,
keyed by canonical name (whitespace trimmed and collapsed, Unicode NFC). Each
**Category** from `categories.json` is assigned a **Category Group** from its
`id` prefix and has its `characters` list resolved against the Roster; unresolved
names are dropped and collected in the data-quality report, which is also logged
at startup. Only Character names reach the client — the answer key stays
server-side.

## Tests

```bash
pytest        # full suite
mypy          # type check (app/)
```

See `docs/agents/testing.md` for the two-seam test pattern this suite follows.
