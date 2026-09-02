# Trivial-Category exclusion: threshold 0.40, forced Grids exempt

## Context

Grid generation (`app/gridgen.py`, issue #4) samples Categories to build a
playable 3×3 Grid. Some Categories are true for almost the whole Roster —
`status_Alive` covers 79% of the 1521 Characters, `race_Human` 73%. A Cell built
on one is a near-gimme: most names satisfy it, so it carries little trivia value.

Issue #4 added `is_trivial_category` — a single predicate comparing a Category's
playable-set size to a fraction of the Roster — and wired it into the sampling
path, but left the knob (`TRIVIAL_CATEGORY_MAX_ROSTER_FRACTION`) at `None`, a
pass-through. Issue #4 suggested a 35–40% cut; issue #11 is to pick a value and
turn it on.

## Decision

- **`TRIVIAL_CATEGORY_MAX_ROSTER_FRACTION = 0.40`.** A Category whose playable
  set exceeds 40% of the Roster is dropped from the candidate pool before
  sampling. On the repo dataset this removes exactly four Categories —
  `status_Alive` (79%), `race_Human` (73%), `debut_598_9999` (52%),
  `debut_1_597` (47%). The next-broadest survivor, `age_known`, covers 33%, so
  the cut sits in a ~14-point empty band: anything from ~0.34 to ~0.47 removes
  the same four, and the choice is not sensitive to dataset drift.
- **A forced Grid keeps bypassing the exclusion.** When a caller passes an
  explicit six-Category list (`generate_grid(..., category_ids=[...])`), those
  Categories are used verbatim, over-large ones included; the Grid still has to
  be solvable and non-degenerate. Forced Grids exist for tests, replays and
  hand-picked boards — deliberate overrides where the caller has already chosen.
  This matches the behaviour issue #4 shipped and is documented at `_forced_grid`.

The per-Category coverage figures, the post-exclusion re-roll attempt counts, and
the Category Group distribution before/after are recorded in
`docs/measurements/trivial-category-threshold.md`.

## Considered options

- **Leave it at `None`.** A board full of gimme cells is a poor first impression
  (user story 7); the mechanism is already built and measured.
- **A lower cut (~0.30).** Also removes `age_known` (33%) and starts eating into
  Categories that make reasonable clues; no evidence they play badly.
- **Apply the exclusion to forced Grids too.** Would break the "pin an exact
  Grid" contract that the claim / Pass / Rematch tests and any future replay
  feature rely on, for no gain — a forced Grid is already a conscious choice.
- **A hard blocklist of Category ids instead of a fraction.** Needs manual
  upkeep as the dataset grows; a fraction adapts. The existing
  `DEGENERATE_BLOCKLIST` stays for pair-wise combos a fraction cannot catch.

## Consequences

- Generation still succeeds comfortably: over 1000 seeds, every seed produces a
  Grid, mean 41 re-rolls, max 283 — two orders of magnitude inside
  `DEFAULT_MAX_ATTEMPTS` (10 000).
- Category Groups shift only slightly (top Group share ~16% either way). Race and
  Affiliation stay thin — `race_Human` was a large share of Race slots — but they
  were thin before; the Group-skew question is issue #12's.
- `TRIVIAL_CATEGORY_MAX_ROSTER_FRACTION` is now "live". `is_trivial_category`
  binds its `threshold` default at import, so `generate_grid` reads the value as
  it stood at import time; a test that monkeypatches the module constant must
  pass `threshold` explicitly (as the property tests do).
