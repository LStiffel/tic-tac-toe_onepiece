# Keep the dataset current with a vendored Raw dataset, a deterministic Category builder, and a weekly review-only Refresh

## Context

The game's data originates from a scrape of oparchive.com — a fan site that
publishes `characters.json`, `devil_fruits.json` and `islands.json` as plain
static files at `https://oparchive.com/data/` and tracks the manga chapter by
chapter. The repo's copy of `characters.json` was last pulled in April and had
fallen ~4 months / ~30 chapters behind. Nothing in the repo could re-pull it: no
scraper was committed, and `categories.json` (the derived file the game actually
plays from — 195 Categories with their resolved character lists) was built by an
exploratory Jupyter notebook that is not reproducible and does not even emit
`categories.json`.

Issue #15 asked how the data keeps up when a new chapter comes out. A grilling
session settled the shape below. Comparing the stale local file against Upstream
at the time: identical schema, 1532 → 1550 entries, and — the sharp edge —
Upstream *renames* entries (`Kouzuki Toki` → `Amatsuki Toki [Kouzuki Toki]`,
`Marco` → an epithet form) and backfills fields (`age` +19) as chapters reveal
them. The three files are served as direct JSON with no API, no auth, no stated
licence.

## Decision

- **Upstream is oparchive.com; the Raw dataset stays vendored.** The three JSON
  files are committed to the repo verbatim and are the input of record. They diff
  cleanly and pin the game to a known dataset even if Upstream changes or goes
  down. `data/PROVENANCE.md` records the source URLs, the fetch timestamp, the
  Upstream `CHANGELOG_VERSION`, and entry counts; it is regenerated on every
  Refresh.

- **`scripts/build_categories.py` is a deterministic builder.** It reads the
  three Raw files and emits `categories.json` + `categories.txt`, sorted and
  stable. The 195 Category predicates and their Category Group assignments live in
  it as code, reverse-engineered from the current committed output. A **golden
  test** asserts that running the builder on the currently-committed Raw dataset
  reproduces the currently-committed `categories.json` byte-for-byte. An
  unjoinable `devil_fruit` value or journey location is **reported, never
  silently dropped** — the Character keeps every Category that does not depend on
  the join. The exploratory notebook and its scratch CSV are retired.

- **`scripts/validate_dataset.py` gates a Refresh with three severities**, run in
  CI alongside `mypy` / `pytest`:
  - **BLOCK** (CI red, cannot merge): dataset will not load; a Category Group ends
    with zero usable Categories; total surviving Categories fall below a floor;
    the Grid-generation smoke test cannot produce a solvable Grid; the fetched
    JSON fails a shape / required-key / type check (Upstream schema drift). On
    schema drift the fetched file is not written over the vendored copy.
  - **REVIEW** (CI green, PR labelled `needs-review` with a checklist; merges only
    after a human ticks it): the Trivial Category set is no longer exactly
    `{status_Alive, race_Human}` (ADR-0002); the Dead Category count moved
    (ADR-0003); a Category fell below the Viable threshold; a Category Group's
    share of the pool shifted beyond a pinned threshold; more than N newly
    unresolved names.
  - **INFO** (PR body only): characters added / removed / renamed, `count` deltas,
    new devil fruits / islands, the unjoinable-join report.

- **The Refresh runs weekly and only ever opens a pull request.**
  `.github/workflows/refresh.yml` (`cron: '0 6 * * 1'`, Monday 06:00 UTC) fetches
  the three files, runs the builder, runs the validator, and — only if
  `git diff` shows a change — opens or force-updates a single rolling
  `data-refresh` PR (via `peter-evans/create-pull-request`), with the Upstream
  changelog entries since the last Refresh in the body. No diff means no PR and
  no noise. **Nothing auto-merges.** A failed fetch or a BLOCK check fails the
  scheduled run, which GitHub emails to the repo owner.

- **A Refresh replaces the Raw dataset wholesale; no alias map.** The local files
  have never been hand-edited, so there is nothing to preserve. Because
  `categories.json` is always rebuilt from the same fresh `characters.json`,
  Category → Character references stay internally consistent for free; an Upstream
  rename only changes which name a player types, and the roster diff surfaces it
  as an INFO/REVIEW item.

- **A Refresh never re-tunes the Grid-generation knobs.**
  `TRIVIAL_CATEGORY_MAX_ROSTER_FRACTION` (ADR-0002),
  `MIN_VALID_PARTNERS` and `VALID_PARTNER_WEIGHT_EXPONENT` (ADR-0003) are
  calibrated against dataset statistics and play-informed judgement. When a
  Refresh moves one of their documented invariants the validator raises the
  REVIEW warning with the new proportions; a human decides whether to file a
  separate tuning issue. Mechanism (the Refresh) and policy (the tuning) stay
  apart.

- **Rollout is four tickets under #15**, in order, so the cron only ever sees
  small weekly diffs: (1) `build_categories.py` + golden test, no behaviour
  change; (2) `validate_dataset.py` + severities, wired into CI; (3) a one-time
  catch-up Refresh to the current chapter, its large diff hand-reviewed once;
  (4) the scheduled workflow + `data/PROVENANCE.md`.

## Considered options

- **Fetch Upstream at server start or build time instead of vendoring.**
  Rejected: non-reproducible, breaks offline, unversioned, and a bad Upstream day
  silently degrades the game. Vendoring makes every dataset change a reviewable
  commit.
- **Auto-merge the Refresh PR.** Rejected: ADR-0002 / ADR-0003 tuned knobs
  against specific roster counts, so a silent per-chapter dataset swap can regress
  Grid generation. A human skim plus green CI is cheap insurance.
- **An alias map for renamed Characters.** Rejected as unnecessary: the builder
  rebuilds `categories.json` from the same snapshot, so references never dangle;
  the roster diff already surfaces renames. Revisit only if the Raw dataset ever
  starts being hand-curated.
- **Keep the notebook / rebuild `categories.json` by hand.** Rejected: not
  reproducible, not testable, and not runnable in CI.
- **Have the Refresh re-tune the knobs automatically** (e.g. keep the Trivial
  Category set at size two by moving the fraction). Rejected: ADR-0002 explicitly
  made that a play-informed judgement call, not a formula. Automating it would
  turn a deliberate design lever into a moving target.
- **Move the dataset into a database.** Out of scope. ADR-0001 keeps state
  in-memory and data in flat JSON; nothing here needs more.

## Consequences

- The golden test must be updated by hand whenever a legitimate data change alters
  `categories.json`. That is the intended human checkpoint on the first Refresh
  PR that changes the output — not friction to remove.
- The repo setting *Settings → Actions → General → "Allow GitHub Actions to
  create and approve pull requests"* must be enabled for the workflow's
  `GITHUB_TOKEN` to open the PR; the fallback is a fine-grained PAT in a secret.
- The first catch-up Refresh (step 3) is a large one-time diff — months of new
  Characters, renames, and backfilled fields — reviewed once by hand. Steady
  state is a handful of entries per week.
- The `data-refresh` PR can sit unmerged indefinitely with no harm: the game runs
  on the last merged dataset until someone reviews and merges.
- REVIEW-level validator warnings are now the trigger for any future ADR-0002 /
  ADR-0003 re-tuning issue, replacing "someone happened to notice the
  distribution looked off".
- `validate_dataset.py` runs on every PR, not just the Refresh one, so a
  hand-edit to the Raw dataset or a broken `dataset.py` contract is caught the
  same way.
