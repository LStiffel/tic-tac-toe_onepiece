# One Piece Trivia Tic-Tac-Toe

A local two-player trivia game built on a One Piece dataset. See `CONTEXT.md` for
the domain vocabulary (Match, Grid, Cell, Category, Category Group, ...) and
`docs/adr/0001-stack-and-state.md` for the stack decision.

This repo is being built ticket by ticket (GitHub Issues on
`LStiffel/tic-tac-toe_onepiece`). Current state: **a complete Match, on a web
screen** — the server loads the One Piece dataset at startup, generates a real
seeded Grid on Match creation, and resolves a Guess to claimed / wrong /
already-used / rejected with win-and-draw detection. A stuck Active player can
Pass, and two Passes in immediate succession end the Match as a draw. A no-build
HTML/JS/CSS frontend renders the Grid and drives the whole Match on one shared
screen: an end-of-Match banner that locks the Grid, a Pass button, a live
Used-pool view, a Rematch button, and Character-art `<img>` tags that fall back
to a placeholder when the image file is absent (which, in text-only v1, is
always).

## Requirements

- Python 3.11+

## Setup

```bash
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -e ".[dev]"
```

## Play

```bash
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/>: the frontend creates a Match, renders the Grid
with its six Category labels and a turn indicator, and lets whoever's turn it is
select an empty Cell and name a Character (autocompleted from the Roster), or
Pass. When the Match ends a banner announces the winner or the draw and the Grid
locks; **Rematch** starts a fresh Match in place. The Used-pool panel lists the
Characters claimed so far. Manual browser checks:
`docs/manual-checks/v1-frontend-grid-claim.md` (claim loop) and
`docs/manual-checks/v1-frontend-complete-match.md` (banner, Pass, Used pool,
Rematch, art fallback).

## API

The JSON API is at <http://127.0.0.1:8000> (interactive docs at `/docs`):

| Method & path            | Purpose                                              |
| ------------------------ | --------------------------------------------------- |
| `POST /matches`          | Create a Match; returns the match id, the generated Grid (3 row + 3 column Categories, nine Cells), the Active player, and status `in-progress`. Optional body: `seed`, `category_ids`. |
| `GET /matches/{id}`      | Fetch a Match: its `grid` (Categories + the nine Cells with any claims), the Active player, the Used pool, status, and `winner` on a win. `404` if the id is unknown. |
| `POST /matches/{id}/rematch` | Start a fresh Match from an existing one without restarting the server: a newly generated Grid, an empty Used pool, a first player chosen anew. Returns the new Match (its own id); the source Match is left untouched. `404` if the source id is unknown. Optional body: `seed`, `category_ids`. |
| `POST /matches/{id}/guesses` | Attempt to claim a Cell (`player`, `row`, `column`, `character`); returns the outcome (`claimed` / `wrong` / `already-used` / `rejected`) plus the Match after it. The Roster check is re-run here, so a hand-crafted request cannot bypass it. |
| `POST /matches/{id}/passes` | Pass the turn without attempting a Cell (`player`); returns the outcome (`passed` / `rejected`) plus the Match after it. Two Passes in immediate succession end the Match as a `draw`; a Pass out of turn or on a finished Match is `rejected` with no state change. |
| `GET /roster`            | The Roster as a flat, sorted list of canonical Character names, for client-side autocomplete. Excludes the Category-to-Characters answer key. |
| `GET /characters`        | The Roster as `{name, image}` records, sorted by name, for the Character-art `<img>` tags. `image` is `""` when the dataset carries no art for that Character; the client shows a placeholder for both an empty path and a 404. Excludes the answer key. |
| `GET /diagnostics/data-quality` | The data-quality report from the dataset load: Category-referenced names that do not resolve to a Roster Character, and Categories excluded from play for having fewer than three resolved Characters. |

The frontend is served from `static/` (`GET /`, assets under `/static`).

Match state lives in an in-memory map keyed by match id, reached only through the
`MatchStore` interface (`app/storage.py`), so a database can replace it later
without touching game logic. State is lost when the server stops.

At startup the server loads `characters.json` and `categories.json` once
(`app/dataset.py`). The **Roster** is every Character from `characters.json`,
keyed by canonical name (whitespace trimmed and collapsed, Unicode NFC). Each
**Category** from `categories.json` is assigned a **Category Group** from its
`id` prefix and has its `characters` list resolved against the Roster; unresolved
names are dropped and collected in the data-quality report, which is also logged
at startup. Only Character names and their art paths reach the client — the
Category-to-Characters answer key stays server-side.

## Tests

```bash
pytest        # full suite
mypy          # type check (app/)
```

See `docs/agents/testing.md` for the two-seam test pattern this suite follows.
