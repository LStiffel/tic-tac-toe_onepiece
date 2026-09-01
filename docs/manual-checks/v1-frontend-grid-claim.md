# Manual browser check — v1 Frontend: Grid render + claim interaction (issue #9)

The frontend JS is thin and has no test harness (see `docs/agents/testing.md`).
This is the manual check that stands in for it. Re-run it whenever `static/`
changes.

## Setup

```bash
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/>.

## Steps

Each step maps to an acceptance criterion on the ticket.

1. **Grid + labels + turn indicator.** On load the page shows a 3×3 Grid. Each of
   the three rows and three columns carries a Category label with its Group
   underneath (six in total). A turn indicator reads "Player N (X|O) to move".

2. **Cell selection surfaces the two Category labels.** Click an empty Cell. It
   highlights, and the line above the input reads
   `Guessing Row: <label> (<group>) ∩ Column: <label> (<group>)` — the two
   Categories that define that Cell. The input takes focus.

3. **Autocomplete from the Roster.** Type into the name box. A suggestion list
   appears, drawn from `GET /roster`, and narrows as you type more letters.

4. **Correct guess.** With a Cell selected, name a Character that satisfies both
   its Categories and submit (button or Enter). The Cell fills with the current
   player's mark and the Character name, the feedback line confirms the claim,
   the input clears, and the turn indicator flips to the other player.

5. **Wrong guess.** Select an empty Cell and name a Character that fits only one
   axis. The feedback line names which axis failed ("fits the row, fails the
   column" / "fails the row, fits the column" / "fails both …") and the turn
   indicator advances. The Cell stays empty.

6. **Already-used.** Claim a Character on some Cell, then select another Cell and
   name the same Character. The feedback line says it is already in the Used pool
   and that your turn continues — the turn indicator does **not** advance.

7. **Server re-validation.** Select a Cell, type a name that is not in the Roster
   (e.g. `Notarealperson`) so it matches no suggestion, and submit anyway. The
   server rejects it ("not in the Roster — the server rejected it"); nothing on
   the Grid changes.

## Status

- **Automated** (`tests/test_frontend.py`, part of `pytest`): `GET /` serves the
  page, `/static/app.js` and `/static/styles.css` are served.
- **Smoke-tested via `curl`** while building the ticket: `GET /roster` returns
  the name list, `POST /matches` returns a generated Grid + first player, and
  `POST /matches/{id}/guesses` returns `rejected` / `unknown-character` for a
  non-Roster name and `not-your-turn` for an out-of-turn player.
- **Steps 1–7 above**: pending a human run in a real browser — they exercise DOM
  rendering and interaction that the automated/`curl` checks do not cover. Record
  the date and outcome here after running them.

## Out of scope here (issue #10)

End-of-Match banner, Pass button, Used-pool view, Rematch button, and
`/images/…webp` fallbacks. This screen only degrades gracefully if a Match ends:
the turn line switches to "Match over — …" and the Grid stops taking input.
