# Category Group sampling — measurement

Evidence for `docs/adr/0003-even-category-group-sampling.md`, which changes the
random Grid-generation path in `app/gridgen.py` so Category Groups show up more
evenly across Matches (issue #12).

Two changes, both keyed on a Category's **valid-partner count** — the number of
other pool Categories it can share a Cell with: non-empty playable-set
intersection, neither set a subset of the other, pair not on
`DEGENERATE_BLOCKLIST`. That is exactly what the solvability re-roll filters on,
so it predicts how often a Category survives to a finished Grid.

1. **Dead-Category prune** (`MIN_VALID_PARTNERS = 3`). A Category with fewer than
   three valid partners cannot fill a row or a column of any solvable Grid, so it
   is dropped from the candidate pool before sampling.
2. **Partner-count-weighted within-Group draw**
   (`VALID_PARTNER_WEIGHT_EXPONENT = 2`). Within each Group a Category is drawn
   with weight `valid_partner_count ** 2`. Groups themselves stay uniform.

All figures are from `default_game_data()` (repo `characters.json` /
`categories.json`) run through the actual `app.gridgen` code. Roster: **1521**
Characters, **195** playable Categories, **193** after the trivial-Category
exclusion (issue #11), **182** after the dead-Category prune.

## The dead-Category prune

The prune removes **11** Categories — 10 Affiliation, 1 Race, every one with a
playable set of 6 Characters or fewer:

| Category | Group | Playable set | Valid partners |
| --- | --- | --- | --- |
| `aff_Alvida Pirates (disbanded)` | Affiliation | 3 | 0 |
| `aff_Beasts Pirates (Armored Division)` | Affiliation | 6 | 0 |
| `aff_Germ Pirates` | Affiliation | 5 | 0 |
| `aff_Usopp Pirates (disbanded)` | Affiliation | 3 | 0 |
| `aff_Endurance Curry Pirates` | Affiliation | 3 | 1 |
| `aff_Island of Rare Animals` | Affiliation | 4 | 1 |
| `aff_Rebel Army` | Affiliation | 4 | 1 |
| `aff_Roshwan Kingdom` | Affiliation | 5 | 1 |
| `race_Human-Longarm hybrid` | Race | 4 | 1 |
| `aff_Baroque Works (Billions)` | Affiliation | 3 | 2 |
| `aff_Lvneel Kingdom` | Affiliation | 3 | 2 |

These are crews / factions whose members are near-perfectly correlated with a
bigger Category (all one race, all one origin, all deceased), so almost every
pairing is subset-related or has an empty intersection. They never appeared in a
generated Grid before the prune either — the prune just stops the sampler wasting
draws on them. The property test `test_no_generated_grid_uses_a_dead_category`
(`tests/test_gridgen.py`) recomputes this set from the dataset and asserts none
of it reaches a Grid.

## Group distribution — before / after

Group shares of the six Category slots across **1000** generated Grids
(`seed` in `0..999`), with the sampling change off (uniform within-Group draw
over the full non-trivial pool — i.e. issue #4 / #11 behaviour) and on:

| Group | off | on |
| --- | --- | --- |
| Visited (journey) | 15.8 % | 12.8 % |
| Misc | 10.5 % | 11.8 % |
| Debut chapter | 10.3 % | 9.6 % |
| Status | 10.4 % | 9.5 % |
| Origin sea | 8.1 % | 9.0 % |
| Haki | 10.7 % | 8.8 % |
| Devil Fruit | 6.9 % | 8.1 % |
| Bounty | 9.3 % | 7.6 % |
| Height | 8.2 % | 7.4 % |
| Age | 7.1 % | 6.7 % |
| **Race** | **1.8 %** | **5.1 %** |
| **Affiliation** | **1.0 %** | **3.5 %** |
| floor | 1.0 % | 3.5 % |
| top | 15.8 % | 12.8 % |
| top / floor | 16.3 | 3.6 |

A uniform draw over the 12 Groups would be ~8.3 % each. The change roughly
triples the two squeezed Groups (Affiliation 1.0 → 3.5 %, Race 1.8 → 5.1 %) and
pulls the top Group down (15.8 → 12.8 %), cutting the top-to-floor spread from
**16×** to **3.6×**. Affiliation and Race still sit below uniform: even their
best-connected Categories (`aff_Marines`, 87 members; `race_Animal`, 111) have
fewer valid partners than the *weakest* Category in Bounty or Haki, so the filter
still rejects them somewhat more often. Closing that last gap would need a
per-Group boost the recorded decision did not take (see the ADR).

Over the 300-seed range the property test uses (`seed` in `0..299`): floor
**3.7 %** (Affiliation), top **11.8 %** (Misc), top / floor **3.2**.
`test_category_groups_are_distributed_roughly_evenly` asserts all 12 Groups
present, `top < 0.16`, `floor >= 0.025`, `top / floor < 5`.

## Attempt counts

Re-rolls to find a solvable Grid, same 1000 seeds:

| | pool | failures | min | median | mean | p95 | p99 | max | cap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| off | 193 | 0 | 1 | 26 | 38.4 | 115 | 170 | 366 | 10 000 |
| on | 182 | 0 | 1 | 6 | 8.8 | 24 | 36 | 71 | 10 000 |

The change **lowers** the attempt count — sharply. Weighting toward
better-connected Categories means the sampler stops proposing pairings the
solvability filter is bound to reject, so a valid Grid turns up in a median of 6
re-rolls instead of 26, and the worst seed in 1000 needs 71, two orders of
magnitude inside `DEFAULT_MAX_ATTEMPTS`. `test_generation_succeeds_for_every_seed_in_a_large_sample`
guards "every seed yields a Grid" over a 500-seed sample.

## Reproducing

```python
from collections import Counter, defaultdict
import random, statistics
from app.dataset import default_game_data
from app import gridgen
from app.gridgen import (
    is_trivial_category, _valid_partner_counts,
    MIN_VALID_PARTNERS, VALID_PARTNER_WEIGHT_EXPONENT,
)

d = default_game_data(); N = len(d.roster)

def search(prune, exponent, seeds=range(1000)):
    nt = tuple(c for c in d.categories if not is_trivial_category(c, N))
    pc = _valid_partner_counts(nt)
    floor = MIN_VALID_PARTNERS if prune else 0
    pool = tuple(c for c in nt if pc[c.category.id] >= floor)
    bg = defaultdict(list)
    for c in pool:
        bg[c.category.group].append(c)
    groups = sorted(bg, key=lambda g: g.value)
    w = {g: [pc[c.category.id] ** exponent for c in bg[g]] for g in groups}
    gc, attempts = Counter(), []
    for s in seeds:
        rng = random.Random(s)
        for attempt in range(1, 10_001):
            sg = rng.choices(groups, k=6)
            chosen = [rng.choices(bg[g], weights=w[g], k=1)[0] for g in sg]
            if len({c.category.id for c in chosen}) != 6:
                continue
            if gridgen._pairing_is_valid(chosen[:3], chosen[3:]):
                attempts.append(attempt)
                for c in chosen:
                    gc[c.category.group] += 1
                break
    total = sum(gc.values())
    return {g.value: n / total for g, n in gc.items()}, statistics.mean(attempts)

print(search(prune=False, exponent=0))                              # off
print(search(prune=True, exponent=VALID_PARTNER_WEIGHT_EXPONENT))  # on
```

The dead-Category list: `[c.category.id for c in default_game_data().categories
if _valid_partner_counts(tuple(...)).get(c.category.id, 0) < MIN_VALID_PARTNERS]`
over the non-trivial pool.
