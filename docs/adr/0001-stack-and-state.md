# FastAPI, vanilla frontend, in-memory game state behind a storage interface

## Context

v1 is a local, hotseat-only web game: two players sharing one browser. It should
be simple to build now, but we intend to add an online real-time mode later where
two separate browsers share a live Match.

## Decision

- **Backend: FastAPI.** Native WebSocket support and Pydantic validation on the
  guess-submission endpoint. The online mode needs sockets; we don't want a
  framework change or a socket extension later.
- **Frontend: vanilla JS / HTML / CSS, no build step.** The UI is a single screen
  (Grid, autocomplete box, status line). A framework is overhead.
- **Game state: an in-memory map keyed by game ID, behind a small storage
  interface.** Zero setup for v1; the interface lets SQLite or Redis slot in later
  without touching game logic.
- **Data: category and character JSON loaded into memory at startup.** Only
  character names (for autocomplete) and their `/images/…webp` art paths (for the
  Cell / detail-area `<img>` tags, added in issue #10) ship to the client; the
  Category-to-Characters answer key stays server-side.

## Considered options

- **Flask** — simpler for a pure request/response v1, but WebSockets are an
  add-on and there is no built-in request validation; the online mode would
  likely force a migration anyway.
- **A frontend framework (React/Svelte)** — unjustified for one screen with no
  build pipeline.
- **SQLite/Postgres from day one** — persists Matches across restarts and is a
  natural home for match history, but adds schema and migration work for state
  whose shape changes frequently early on. The storage interface keeps this
  option open.

## Consequences

- Game state is lost on server restart: acceptable for local v1, mildly
  inconvenient during development.
- Running multiple server workers would break the in-memory map; v1 runs a single
  process.
