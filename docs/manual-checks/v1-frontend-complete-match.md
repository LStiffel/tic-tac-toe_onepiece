# Manual browser check — v1 Frontend: complete Match (issue #10)

The frontend JS is thin and has no test harness (see `docs/agents/testing.md`).
This is the manual check that stands in for it, covering what issue #10 adds on
top of the issue #9 screen: the end-of-Match banner, the Pass button, the
Used-pool view, the Rematch button, and Character-art `<img>` tags that fall
back to a placeholder. Re-run it whenever `static/` changes.

Issue #9's own steps (Grid render, Cell selection, autocomplete, claim / wrong /
already-used / server re-validation) still apply — see
`v1-frontend-grid-claim.md`.

## Setup

```bash
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/>.

## Steps

Each step maps to an acceptance criterion on the ticket.

1. **Character art with placeholder fallback.** On load, and after every claim,
   Cells that hold a Character and the "Last claimed" figure under the input show
   a portrait box. `v1` ships no `/images/…webp` files, so every box renders the
   hatched placeholder with a ☠ glyph rather than a broken image. Confirm in
   DevTools that the `<img>` `src` is the real `/images/characters/<Name>.webp`
   path from `GET /characters` and that the box degrades on the 404 — no broken
   image icon.

2. **Used-pool view.** The "Used pool (N)" panel starts at `0` with
   "No Characters used yet." Claim a Character: the count becomes `1` and the
   name appears in the list with its portrait. Claim another on a later turn: the
   list grows and stays sorted. A **wrong** guess and an **already-used** guess
   do *not* add a row.

3. **End-of-Match banner on a win.** Play a full Match to a Line (three Cells in
   a row/column/diagonal for one player). The moment the Line forms, a banner
   reads "Player N (X|O) wins the Match!", the turn line switches to "Match
   over", and every empty Cell is disabled — clicking one does nothing, and the
   Guess and Pass buttons are disabled.

4. **End-of-Match banner on a full-Grid draw.** Play a Match where all nine Cells
   get claimed with no Line (wrong guesses forfeit turns, so this takes some
   engineering — claim Cells so neither player completes a Line). When the ninth
   Cell is claimed the banner reads "The Match is a draw." and the Grid locks.

5. **Pass.** On your turn, click **Pass** without selecting a Cell. The feedback
   line reads "Turn passed. Player M … to move." and the turn indicator flips.
   The Grid is unchanged and nothing is added to the Used pool.

6. **Double-Pass draw.** Pass, then have the other player Pass immediately (no
   claim or wrong guess in between). The banner reads "The Match is a draw.", the
   feedback line reads "Two Passes in immediate succession — the Match is a
   draw.", and the Grid locks.

7. **Rematch.** With a finished Match on screen (from step 3, 4 or 6), click
   **Rematch**. Without a page reload the Grid is replaced with a freshly
   generated one (different Categories), the banner clears, the Used-pool view is
   back to `0` / "No Characters used yet.", the "Last claimed" figure is gone,
   and the feedback line reads "Rematch. Fresh Grid, empty Used pool. Player N …
   to move." Play a move to confirm the new Match is live.

## Status

- **Automated** (`tests/test_frontend.py`, part of `pytest`): `GET /` serves the
  page; `/static/app.js` and `/static/styles.css` are served; the page carries
  the `banner`, `pass-btn`, `rematch-btn`, `used-pool-list` and `art` ids the
  script binds to. `GET /characters` shape is covered by
  `tests/test_roster_api.py`.
- **Steps 1–7 above**: pending a human run in a real browser — they exercise DOM
  rendering and interaction that the automated checks do not cover. Record the
  date and outcome here after running them.

| Date | Runner | Result |
| ---- | ------ | ------ |
|      |        |        |
