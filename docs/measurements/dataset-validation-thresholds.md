# Dataset validation thresholds — measurement

Evidence for the pinned numbers in `scripts/validate_dataset.py`
(`Thresholds`), the Refresh gate from `docs/adr/0004-dataset-refresh-pipeline.md`
(issue #21). Each threshold is pinned against the committed dataset and given
enough headroom that an ordinary weekly Refresh (a handful of new Characters)
stays quiet, while the one-time catch-up Refresh — or a genuine regression —
trips it for a human to look at.

## Before / after

"Before" is the dataset committed at `HEAD` when this note was written
(2026-09-03): `characters.json` at ~chapter 1130, `devil_fruits.json` /
`islands.json` still at the April pull. "After" is the working-tree files
validated against `HEAD` — the `__main__` self-check. With a clean tree the two
sides are identical, so every delta is zero and the run is green
(`0 BLOCK, 0 REVIEW, 2 INFO`; the two INFO lines are the builder's stale-join
report, see below). `main()` uses the working tree as the candidate so it also
catches uncommitted edits; on a CI PR checkout the tree already equals the
committed files, matching the issue's "committed repo files as candidate".

All figures are from `app.dataset.load_game_data()` and
`app.gridgen.generation_pool()` over the committed files:

| quantity | value |
| --- | --- |
| Roster | 1521 Characters |
| playable Categories (`GameData.categories`) | 195 |
| Categories excluded below the Viable threshold | 0 |
| unresolved Category-referenced names | 0 |
| Trivial Categories (`is_trivial_category`) | 2 — `status_Alive`, `race_Human` |
| non-trivial Categories | 193 |
| Dead Categories (`< MIN_VALID_PARTNERS` valid partners) | 11 |
| generation pool (non-trivial, non-Dead) | 182 |

Generation-pool share by Category Group (denominator 182):

| Group | count | share |
| --- | --- | --- |
| Affiliation | 83 | 45.6 % |
| Visited (journey) | 28 | 15.4 % |
| Race | 18 | 9.9 % |
| Misc | 10 | 5.5 % |
| Origin sea | 8 | 4.4 % |
| Bounty | 7 | 3.8 % |
| Debut chapter | 7 | 3.8 % |
| Devil Fruit | 6 | 3.3 % |
| Haki | 5 | 2.7 % |
| Height | 4 | 2.2 % |
| Age | 4 | 2.2 % |
| Status | 2 | 1.1 % |

Grid-generation smoke test: `generate_grid(data, seed=s)` for `s` in `0..49`
each returns a solvable Grid, in **0.03 s** total.

## The thresholds

### `min_surviving_categories = 175` — BLOCK

Playable Categories today: **195**. `175` is ~10 % below that. The predicate
table in `scripts/build_categories.py` is fixed at 195 rows; a Category only
disappears if a Refresh drops its membership below `MIN_CHARACTERS` (3). Losing
20 Categories at once means an Upstream field (`race`, `affiliation`, `haki`, a
join key) changed shape — exactly the "dataset will not load / is unplayable"
case this severity is for. A weekly Refresh moves this by 0–1.

### `smoke_test_seeds = 25` — BLOCK

The full 50-seed sweep passes in 0.03 s and every seed in `0..999` passes in the
`gridgen` property tests. `25` is a cheap subset that still exercises the
Group-uniform / partner-weighted draw across many pools. A single failure means
some Category Group's pool cannot be paired into a Grid — the pool went too thin
— which is a BLOCK.

### `group_share_drift_pct = 5.0` — REVIEW

Largest pool share is Affiliation at **45.6 %**; the rest are ≤ 15.4 %. A weekly
Refresh adds a few Characters, moving any one Group's share by well under a
percentage point. `5.0` pts is a move no ordinary Refresh makes; the catch-up
Refresh (≈ 30 chapters of new Characters, heavy on new Affiliation / Visited
rows) is expected to cross it, which is the point — a human then decides whether
ADR-0003's within-Group weighting needs re-tuning. The validator only flags; it
never edits `VALID_PARTNER_WEIGHT_EXPONENT` / `MIN_VALID_PARTNERS`.

### `new_unresolved_names = 10` — REVIEW

Unresolved names today: **0** — the builder and the loader canonicalise names
the same way, so every Category reference resolves. Any Refresh that leaves more
than 10 references dangling has hit a systematic rename that the wholesale Raw
swap did not keep internally consistent (it should — same `characters.json`
feeds both files), so it is worth a look. 1–10 is absorbed as noise / genuine
mid-Refresh Upstream inconsistency.

### `count_delta = 25` — INFO

Category playable-set sizes span 3 to ~1211 (`status_Alive`). A weekly Refresh
adds ~10–20 Characters spread across Categories, so a single Category rarely
moves by 25. When one does, the reviewer wants the line in the PR body. INFO
only — it never blocks or requires review.

## Roster / join INFO lines (no threshold)

`characters-added` / `characters-removed` / `characters-renamed` diff the two
Rosters; a rename is a removed name that Upstream kept as a `[...]` segment of an
added name, or a whole-token prefix/suffix of it (`_is_rename_of`).
`new-devil-fruits` / `new-islands` diff the `name` rows of the candidate and
baseline `devil_fruits.json` / `islands.json` — so they need `baseline_raw`,
which only the `__main__` path has (the derived baseline `GameData` carries
neither file). All are INFO: they populate the Refresh PR body, never gate it.

## The builder join report (INFO, informational)

Running `scripts.build_categories.build_categories` over the committed files
today reports 1 unjoinable `devil_fruit` value (`Jiki Jiki no Mi`) and 9
unjoinable journey locations. These are the stale April `devil_fruits.json` /
`islands.json` against the September `characters.json`; the catch-up Refresh
(issue #15 step 3) re-pulls all three together. The validator surfaces this list
as INFO — it is the same `BuildReport` the builder already emits, not a new
check.

## Reproducing

```python
from collections import Counter
from app.dataset import load_game_data
from app.gridgen import generation_pool

d = load_game_data()
gp = generation_pool(d)
print(len(d.roster), len(d.categories), len(gp.trivial), len(gp.dead), len(gp.pool))
shares = Counter(c.category.group.value for c in gp.pool)
for g, n in shares.most_common():
    print(f"{g:20s} {n:3d} {100*n/len(gp.pool):5.1f}%")
```

The `__main__` self-check (`python -m scripts.validate_dataset`) prints the
findings and the `BLOCK / REVIEW / INFO` tally and exits non-zero iff any finding
is BLOCK.
