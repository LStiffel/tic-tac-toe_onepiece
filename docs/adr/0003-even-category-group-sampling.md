# Even out Category Group sampling: prune dead Categories, weight the within-Group draw by Valid-partner count

## Context

Grid generation (`app/gridgen.py`, issue #4) samples six Category Groups
uniformly with replacement, picks one Category within each, then re-rolls the
whole Grid until it is solvable and no pair is subset-related or blocklisted.

CONTEXT.md and user story 6 want Category Groups to "show up roughly evenly
across Matches". Measured over 300+ seeded Grids they do not: the solvability
re-roll rejects almost every candidate that contains an Affiliation or Race
Category, because those Groups are made of many tiny Categories (Affiliation has
93, most with 3–15 Characters) whose playable sets rarely intersect the rest of
the board without also being a subset of something. Post-filter, Affiliation held
**~1 %** of Category slots and Race **~1.8 %**, against a ~8.3 % uniform
expectation and a ~15.8 % top Group (Visited). Issue #4's property test only
asserted `top_share < 0.20`, so it passed while the bottom end was clearly not
"roughly even".

Issue #11 (trivial-Category exclusion, `docs/adr/0002`) already edits this same
candidate pool but does not touch the skew — it noted the Group question is
issue #12's.

The issue #12 discussion recorded a decision: **a mix of options 2 (re-weight
sampling) and 3 (prune dead Categories)**; explicitly *not* option 1 (accept and
document the skew). This ADR records how that was implemented and what it bought.

## Decision

Both levers key on a Category's **valid-partner count**: the number of other
pool Categories it can share a Cell with — non-empty playable-set intersection,
neither set a subset of the other, pair not on `DEGENERATE_BLOCKLIST`
(`_valid_partner` / `_valid_partner_counts` in `app/gridgen.py`). That is exactly
the pairwise test the solvability re-roll applies, so the count predicts how
often a Category survives to a finished Grid. It is computed once per dataset
(O(n²) frozenset intersections) and cached.

- **`MIN_VALID_PARTNERS = 3` — dead-Category prune (option 3).** A Category with
  fewer than three valid partners cannot fill a row or a column of any solvable
  Grid (a row needs three columns it intersects without subset relation, and
  vice versa), so it is dropped from the random-path pool up front. On the repo
  dataset this removes **11** Categories — 10 Affiliation, 1 Race, every one with
  a playable set ≤ 6. None of them ever reached a generated Grid anyway; the
  prune just stops the sampler spending draws on them. This is the
  "can't be in any solvable Grid" floor only — not the broader viable-threshold
  tuning floated in issue #2.

- **`VALID_PARTNER_WEIGHT_EXPONENT = 2` — partner-count-weighted within-Group
  draw (option 2).** Within each Group a Category is drawn with weight
  `valid_partner_count ** 2`. When Affiliation is the sampled Group the board now
  almost always gets `aff_Marines` or `aff_Big Mom Pirates` (dozens of valid
  partners) rather than a random one of 90-odd fan crews, so the solvability
  filter rejects far fewer candidates and the Group's post-filter share rises.

- **Groups themselves stay uniform.** Weighting the *Group* draw by Category
  count or by aggregate Valid-partner count was tried and rejected (see below):
  it pushes probability toward the already-fat Groups, the opposite of the goal.

- **A forced Grid keeps bypassing all of it.** `_forced_grid` never consults the
  pool, so `generate_grid(..., category_ids=[...])` uses the six named Categories
  verbatim — trivial ones, sparsely-connected ones, all of it — subject only to
  the Grid being solvable and non-degenerate. Same contract as issues #4 and #11.

Setting `VALID_PARTNER_WEIGHT_EXPONENT = 0` recovers a uniform within-Group
draw; `MIN_VALID_PARTNERS = 0` disables the prune.

### Measured effect

Over 1000 seeded Grids (full numbers, harness, and the near-cut Categories in
`docs/measurements/category-group-sampling.md`):

| | off | on |
| --- | --- | --- |
| Affiliation share | 1.0 % | **3.5 %** |
| Race share | 1.8 % | **5.1 %** |
| top Group share | 15.8 % | 12.8 % |
| top / floor spread | 16× | **3.6×** |
| re-roll attempts (mean / max) | 38 / 366 | **9 / 71** |
| generation failures | 0 | 0 |

Affiliation and Race still land a little below the ~8.3 % uniform line — even
their best-connected Categories have fewer valid partners than the weakest
Category in Bounty or Haki, a real property of a dataset with 93 small
Affiliation Categories. Closing that last gap needs a per-Group boost the
decision chose not to take. The change also *lowers* the attempt count, because
the sampler stops proposing pairings that were bound to be rejected.

### Test

`test_category_groups_are_distributed_roughly_evenly` (`tests/test_gridgen.py`)
now asserts, over 300 seeds: all 12 Groups present, `top_share < 0.16`,
`floor_share >= 0.025`, `top_share / floor_share < 5` — a real floor that fails
if a Group slides back toward the pre-#12 ~1 %, replacing the lone
`top_share < 0.20`. `test_no_generated_grid_uses_a_dead_category` recomputes the
`< MIN_VALID_PARTNERS` set from the dataset and asserts none of it reaches a
Grid.

## Considered options

- **Accept and document the skew (option 1).** Rejected by the issue #12
  decision: "Grids that all feel like the same handful of themes … is a bad first
  impression".
- **Weight the *Group* draw** (by Category count, by mean/max valid-partner
  count). Measured: `sqrt(count)` and `max-degree` weighting made it *worse* —
  Status collapsed to ~4 %, Visited ran up to ~17 % — because they hand
  probability to the Groups that were already fine. Uniform Group draw + weighted
  within-Group draw was cleanly best.
- **A higher exponent (3).** Lifts Affiliation to ~4.8 % and cuts attempts
  further, but concentrates Race onto a single Category (`race_Animal` ~57 % of
  Race slots) and Affiliation onto `aff_Marines` — within-Group variety suffers
  for a marginal floor gain. Exponent 2 keeps ~27 distinct Affiliation Categories
  in rotation.
- **Clipped weights** (`min(count, 40) ** 2`). Meant to preserve variety among
  healthy Categories while still suppressing the tail. Measured worse on every
  axis than the plain square — more attempts, lower floor. Not worth the extra
  knob.
- **A stronger prune** (require the three partners to be mutually compatible — a
  4-clique). Sound, but only catches a handful more Categories than the degree-3
  floor and costs a much more expensive precompute. The decision scoped option 3
  to the cheap "can't be in any solvable Grid" floor.
- **A hard per-Group probability boost** for Affiliation / Race until every Group
  hits ~8.3 %. Would meet "even" literally, but it is a fudge factor with no
  grounding in the data and needs re-tuning on every dataset change; the
  partner-count weight adapts on its own. The residual sag is small and
  explainable.

## Consequences

- The random pool is now 182 Categories (195 playable → 193 after the trivial
  exclusion → 182 after the dead-Category prune). The 11 pruned Categories are
  still valid for forced Grids.
- `_valid_partner_counts` is `lru_cache`d on the pool tuple. `generate_grid`
  rebuilds an equal tuple each call, so the O(n²) precompute runs once per
  dataset per process; the full test suite stays ~3 s.
- The counts are taken over the *non-trivial* pool and reused for both the prune
  and the weights — not recomputed on the 182 survivors. The pruned Dead
  Categories have fewer than three partners each, so a survivor's count changes
  by at most a rounding-level amount and no weight shifts meaningfully; the
  measurement harness does the same, so its numbers match the shipped code.
- Grid generation switched from `random.Random.choice` to `.choices` (weighted).
  Seeds therefore map to different Grids than before this change — no test pins a
  seed→Grid mapping (the testing guide forbids it), and determinism for a given
  seed is unchanged and still covered.
- Two new tunables (`MIN_VALID_PARTNERS`, `VALID_PARTNER_WEIGHT_EXPONENT`) sit
  alongside `TRIVIAL_CATEGORY_MAX_ROSTER_FRACTION` as the knobs on the candidate
  pool. All three are bypassed by forced Grids.
- Affiliation and Race remain below a uniform share (~3.5 % / ~5 % vs ~8.3 %).
  This is documented in CONTEXT.md's "Category Group" entry as expected. If a
  later ticket wants them at parity, the per-Group boost is the lever, and it
  would build on this one.
- If the dataset drifts enough that Affiliation's share falls below 2.5 % at 300
  seeds, `test_category_groups_are_distributed_roughly_evenly` fails — a
  deliberate prompt to re-tune rather than a silent regression.
