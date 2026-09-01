# Testing

How this repo is tested. Established by the scaffold ticket (v1 issue #2);
later tickets follow the same two seams.

## Tooling

- **`pytest`** — the runner. Config lives in `pyproject.toml`
  (`[tool.pytest.ini_options]`); `pytest` from the repo root discovers everything
  under `tests/`.
- **FastAPI `TestClient`** (`fastapi.testclient.TestClient`, httpx under the
  hood) — drives the HTTP seam in-process, no running server.
- **`mypy`** (`mypy`, strict, over `app/`) — run alongside the suite.

Install both with `pip install -e ".[dev]"`.

## The two seams

Test **externally observable behaviour**, not internal structure. Don't assert on
the shape of the in-memory state object, private helper names, or how the RNG is
threaded.

### Seam 1 - HTTP API (primary)

Integration tests through `TestClient`: the responses a client actually sees.
A good test reads as *"given this Grid and these guesses, the API says X"*.
Use the `client` fixture from `tests/conftest.py`, which wires a fresh
`InMemoryMatchStore` per test. Files: `tests/test_match_api.py`.

Once Match creation accepts a `seed` / explicit Category ids (later ticket), use
that affordance for deterministic Grids rather than mocking.

### Seam 2 - pure domain functions (secondary)

Direct calls, no HTTP: the Grid generator, the roster/category loader, the state
machine helpers. Files: `tests/test_domain.py`, `tests/test_storage.py`.

Prefer small hand-built fixtures over the full dataset so assertions are exact.

## Vocabulary

Test names and assertions use the `CONTEXT.md` glossary — Match, Grid, Cell,
Category, Category Group, Character, Roster, Used pool, Pass — not synonyms.
