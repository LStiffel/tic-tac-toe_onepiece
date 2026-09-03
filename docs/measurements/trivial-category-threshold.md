# Trivial-Category exclusion — measurement

Evidence for `docs/adr/0002-trivial-category-exclusion.md`, which sets
`TRIVIAL_CATEGORY_MAX_ROSTER_FRACTION = 0.60` in `app/gridgen.py`.

A Category whose playable set is true for almost the whole Roster is a poor
trivia clue. `generate_grid` drops such Categories from the candidate pool before
sampling; `is_trivial_category` decides, comparing `len(playable set)` to
`fraction * roster_size` with a strict `>`. Forced Grids (`category_ids`) are an
explicit override and skip the check — see the ADR.

All figures below are from `default_game_data()` (repo `characters.json` /
`categories.json`) and the helpers in `app/gridgen.py`, reproduced with the
script in the "Reproducing" section. Roster: **1536** Characters, **195**
playable Categories.

The per-Category coverage figures (the section below and the appendix) were
refreshed 2026-09-03 against the post-#22 catch-up-Refresh dataset. The re-roll
and Group-distribution simulations further down still carry their original
issue #11 numbers — they exercise a since-superseded sampling path and are
flagged in place.

## Where 0.60 falls

The 0.60 limit is 921.6 Characters, so a Category is dropped at **≥ 922**
(60 %+). The Categories nearest the cut:

| Category            | Group             | Playable / Roster | Coverage | Dropped? |
| ------------------- | ----------------- | ----------------- | -------- | -------- |
| `status_Alive`      | Status            | 1216 / 1536       | 79.2 %   | **drop** |
| `race_Human`        | Race              | 1118 / 1536       | 72.8 %   | **drop** |
| `debut_598_9999`    | Debut chapter     | 807 / 1536        | 52.5 %   | keep     |
| `debut_1_597`       | Debut chapter     | 692 / 1536        | 45.1 %   | keep     |
| `age_known`         | Age               | 512 / 1536        | 33.3 %   | keep     |
| `debut_900_9999`    | Debut chapter     | 426 / 1536        | 27.7 %   | keep     |
| `rel_5plus`         | Misc              | 397 / 1536        | 25.8 %   | keep     |
| `visited_Wano …`    | Visited (journey) | 367 / 1536        | 23.9 %   | keep     |

The threshold removes exactly two Categories: **`status_Alive` and
`race_Human`** — the only ones true for a clear majority of every Character. The
next-broadest survivor, `debut_598_9999` at 52.5 %, is ~7 points clear, so a
modest dataset drift will not change which Categories drop, though the margin is
tighter than a ~0.40 cut would give. A ~0.40 cut would also remove
`debut_598_9999` and `debut_1_597`; those play as fair "when did they debut"
clues, so the cut is set higher to catch only the everyone-qualifies Categories
(see the ADR). No Category Group is emptied. The full per-Category table is in
the appendix.

> The issue #11 body cites `status_Alive` at 1211/1521 and `race_Human` at
> 1114/1521 ("e.g."). The dataset has drifted since; the current counts are
> 1216 and 1118. Both drop under any threshold from ~0.35 to ~0.73.

## Generation stays comfortable

> Figures below are the original issue #11 measurement (Roster 1521, pre-#12
> sampling). `generate_grid`'s random path has since gained the Dead-Category
> prune and partner-weighted draw (ADR-0003); `docs/measurements/category-group-sampling.md`
> and `docs/measurements/dataset-validation-thresholds.md` measure the current
> path. The conclusion here — the trivial filter costs only a handful of
> re-rolls and never starves generation — still holds.

Re-roll attempts to find a solvable Grid, **1000 seeds** (`random.Random(seed)`,
`seed` in `0..999`), same harness with the exclusion on and off:

| exclusion | failures | min | median | mean | p95 | max | cap    |
| --------- | -------- | --- | ------ | ---- | --- | --- | ------ |
| on (0.60) | 0        | 1   | 26     | 36.2 | 106 | 193 | 10 000 |
| off       | 0        | 1   | 24     | 32.0 | 96  | 157 | 10 000 |

Every seed produces a Grid; the filter costs a handful of extra re-rolls and
stays two orders of magnitude inside `DEFAULT_MAX_ATTEMPTS`. The property tests
`test_no_generated_grid_uses_a_trivial_category` and
`test_generation_succeeds_for_every_seed_in_a_large_sample`
(`tests/test_gridgen.py`) guard both invariants over a 500-seed sample.

## Category Group distribution

> This table is the pre-issue-#12 baseline (its "on (0.60)" column is a plain
> uniform draw with only the trivial filter applied). ADR-0003's Group-even
> sampling landed afterwards; `docs/measurements/category-group-sampling.md` has
> the current Group shares. Kept here as the "before" the trivial filter was
> measured against.

Group shares of the six Category slots across 300 generated Grids
(`seed` in `0..299`), before and after the exclusion:

| Group             | off    | on (0.60) |
| ----------------- | ------ | --------- |
| Visited (journey) | 15.3 % | 15.4 %    |
| Haki              | 10.3 % | 10.9 %    |
| Status            | 12.8 % | 10.3 %    |
| Debut chapter     | 9.1 %  | 10.3 %    |
| Bounty            | 9.2 %  | 10.1 %    |
| Misc              | 10.2 % | 9.7 %     |
| Origin sea        | 8.3 %  | 8.6 %     |
| Height            | 7.7 %  | 8.0 %     |
| Devil Fruit       | 6.9 %  | 7.4 %     |
| Age               | 6.5 %  | 7.0 %     |
| Race              | 2.3 %  | 1.5 %     |
| Affiliation       | 1.3 %  | 0.9 %     |

The exclusion barely moves the distribution — the top Group share stays ~15 %,
well under the `top_share < 0.20` bound in
`test_category_groups_are_distributed_roughly_evenly`, which still passes
unchanged. Race and Affiliation remain thin (`race_Human` was a large share of
Race's slots), but they were thin before the exclusion too; evening the Groups
out is issue #12's job, not this one.

## Reproducing

```python
from app.dataset import default_game_data
from app.gridgen import is_trivial_category

d = default_game_data()
n = len(d.roster)
for c in sorted(d.categories, key=lambda c: -len(c.characters)):
    s = len(c.characters)
    print(f"{c.category.id:34} {s:5d} {s / n:6.1%}  {'DROP' if is_trivial_category(c, n) else ''}")
```

Attempt counts and Group shares: replicate `generate_grid`'s re-roll loop over a
seed range, passing `threshold=None` for the "off" column. The exact script used
for this note lives in the issue #11 work log.

## Appendix — every playable Category by Roster coverage

<details>
<summary>All 195 playable Categories, widest first</summary>

| Category | Group | Playable | Coverage |
| -------- | ----- | -------- | -------- |
| `status_Alive` | Status | 1216 | 79.2% |
| `race_Human` | Race | 1118 | 72.8% |
| `debut_598_9999` | Debut chapter | 807 | 52.5% |
| `debut_1_597` | Debut chapter | 692 | 45.1% |
| `age_known` | Age | 512 | 33.3% |
| `debut_900_9999` | Debut chapter | 426 | 27.7% |
| `rel_5plus` | Misc | 397 | 25.8% |
| `visited_Wano Country's Island` | Visited (journey) | 367 | 23.9% |
| `debut_1_300` | Debut chapter | 326 | 21.2% |
| `origin_Grand Line` | Origin sea | 308 | 20.1% |
| `has_epithet` | Misc | 263 | 17.1% |
| `has_df` | Misc | 223 | 14.5% |
| `bounty_1` | Bounty | 221 | 14.4% |
| `haki_any` | Haki | 186 | 12.1% |
| `status_Unknown` | Status | 169 | 11.0% |
| `rel_10plus` | Misc | 165 | 10.7% |
| `visited_Marineford` | Visited (journey) | 161 | 10.5% |
| `haki_arm` | Haki | 160 | 10.4% |
| `status_Deceased` | Status | 158 | 10.3% |
| `debut_1000_9999` | Debut chapter | 146 | 9.5% |
| `visited_Totto Land` | Visited (journey) | 140 | 9.1% |
| `bounty_100000000` | Bounty | 139 | 9.0% |
| `visited_Dressrosa` | Visited (journey) | 139 | 9.0% |
| `visited_Mary Geoise` | Visited (journey) | 136 | 8.9% |
| `height_150_200` | Height | 133 | 8.7% |
| `haki_obs` | Haki | 126 | 8.2% |
| `visited_Elbaph Island` | Visited (journey) | 122 | 7.9% |
| `visited_Sabaody Archipelago` | Visited (journey) | 122 | 7.9% |
| `debut_1_100` | Debut chapter | 119 | 7.7% |
| `visited_Fish-Man Island` | Visited (journey) | 116 | 7.6% |
| `has_image_pre` | Misc | 113 | 7.4% |
| `race_Animal` | Race | 111 | 7.2% |
| `origin_East Blue` | Origin sea | 110 | 7.2% |
| `df_Zoan` | Devil Fruit | 107 | 7.0% |
| `df_Paramecia` | Devil Fruit | 100 | 6.5% |
| `aff_Big Mom Pirates` | Affiliation | 95 | 6.2% |
| `aff_Marines` | Affiliation | 87 | 5.7% |
| `name_charlotte` | Misc | 86 | 5.6% |
| `bounty_under_100m` | Bounty | 82 | 5.3% |
| `visited_Shipbuilding Island` | Visited (journey) | 80 | 5.2% |
| `bounty_500000000` | Bounty | 75 | 4.9% |
| `visited_Zou` | Visited (journey) | 75 | 4.9% |
| `aff_Beasts Pirates` | Affiliation | 73 | 4.8% |
| `visited_Sandy Island` | Visited (journey) | 73 | 4.8% |
| `height_giant` | Height | 68 | 4.4% |
| `visited_Skypiea` | Visited (journey) | 68 | 4.4% |
| `age_60_plus` | Age | 64 | 4.2% |
| `visited_Impel Down` | Visited (journey) | 64 | 4.2% |
| `origin_North Blue` | Origin sea | 62 | 4.0% |
| `visited_Egghead` | Visited (journey) | 62 | 4.0% |
| `visited_Punk Hazard` | Visited (journey) | 62 | 4.0% |
| `visited_Hachinosu` | Visited (journey) | 60 | 3.9% |
| `race_Giant` | Race | 59 | 3.8% |
| `aff_Whitebeard Pirates` | Affiliation | 59 | 3.8% |
| `visited_God Valley` | Visited (journey) | 57 | 3.7% |
| `visited_Enies Lobby` | Visited (journey) | 56 | 3.6% |
| `df_sub_Artificial` | Devil Fruit | 51 | 3.3% |
| `age_under_18` | Age | 45 | 2.9% |
| `visited_Jaya` | Visited (journey) | 42 | 2.7% |
| `race_Fish-man` | Race | 41 | 2.7% |
| `visited_Island of Women` | Visited (journey) | 40 | 2.6% |
| `visited_Thriller Bark` | Visited (journey) | 39 | 2.5% |
| `origin_West Blue` | Origin sea | 38 | 2.5% |
| `origin_South Blue` | Origin sea | 36 | 2.3% |
| `visited_Dawn Island` | Visited (journey) | 36 | 2.3% |
| `race_Merfolk` | Race | 32 | 2.1% |
| `height_over_1000` | Height | 31 | 2.0% |
| `bounty_1000000000` | Bounty | 29 | 1.9% |
| `haki_conq` | Haki | 28 | 1.8% |
| `aff_Kouzuki Family` | Affiliation | 27 | 1.8% |
| `aff_Thriller Bark Pirates` | Affiliation | 26 | 1.7% |
| `aff_Roger Pirates` | Affiliation | 25 | 1.6% |
| `race_Mink` | Race | 25 | 1.6% |
| `visited_Little Garden` | Visited (journey) | 25 | 1.6% |
| `visited_Baratie` | Visited (journey) | 24 | 1.6% |
| `visited_Drum Island` | Visited (journey) | 24 | 1.6% |
| `visited_Ohara` | Visited (journey) | 24 | 1.6% |
| `aff_Kuja` | Affiliation | 23 | 1.5% |
| `aff_Kid Pirates` | Affiliation | 22 | 1.4% |
| `aff_Tontatta Kingdom` | Affiliation | 22 | 1.4% |
| `aff_Walrus School` | Affiliation | 22 | 1.4% |
| `race_Dwarf` | Race | 22 | 1.4% |
| `bounty_1500000000` | Bounty | 21 | 1.4% |
| `haki_all3` | Haki | 20 | 1.3% |
| `visited_Baltigo` | Visited (journey) | 20 | 1.3% |
| `aff_Revolutionary Army` | Affiliation | 19 | 1.2% |
| `aff_Spade Pirates` | Affiliation | 19 | 1.2% |
| `aff_World Government` | Affiliation | 19 | 1.2% |
| `origin_Calm Belt` | Origin sea | 19 | 1.2% |
| `origin_Sky Islands` | Origin sea | 19 | 1.2% |
| `race_Devil Fruit creation` | Race | 19 | 1.2% |
| `visited_Laugh Tale` | Visited (journey) | 19 | 1.2% |
| `aff_Mokomo Dukedom` | Affiliation | 18 | 1.2% |
| `aff_Giant Warrior Pirates` | Affiliation | 17 | 1.1% |
| `debut_ch1` | Debut chapter | 17 | 1.1% |
| `race_Moon people - Shandian` | Race | 17 | 1.1% |
| `race_Object` | Race | 17 | 1.1% |
| `aff_Blackbeard Pirates` | Affiliation | 16 | 1.0% |
| `aff_Donquixote Pirates` | Affiliation | 16 | 1.0% |
| `bounty_3000000000` | Bounty | 16 | 1.0% |
| `df_sub_Mythical` | Devil Fruit | 16 | 1.0% |
| `aff_Baroque Works` | Affiliation | 15 | 1.0% |
| `aff_Arabasta Kingdom` | Affiliation | 15 | 1.0% |
| `aff_Foxy Pirates` | Affiliation | 15 | 1.0% |
| `aff_CP0` | Affiliation | 14 | 0.9% |
| `aff_Impel Down` | Affiliation | 14 | 0.9% |
| `aff_Shandia` | Affiliation | 14 | 0.9% |
| `df_Logia` | Devil Fruit | 14 | 0.9% |
| `name_has_D` | Misc | 14 | 0.9% |
| `race_Robot` | Race | 14 | 0.9% |
| `aff_Red Hair Pirates` | Affiliation | 13 | 0.8% |
| `aff_Ryugu Kingdom` | Affiliation | 13 | 0.8% |
| `aff_Kurozumi Family` | Affiliation | 12 | 0.8% |
| `age_over_100` | Age | 12 | 0.8% |
| `aff_Mermaid Café` | Affiliation | 11 | 0.7% |
| `aff_Straw Hat Pirates` | Affiliation | 11 | 0.7% |
| `aff_Beasts Pirates (Numbers)` | Affiliation | 10 | 0.7% |
| `aff_Caesar Clown` | Affiliation | 10 | 0.7% |
| `aff_Fake Straw Hat Crew` | Affiliation | 10 | 0.7% |
| `race_Artificial Giant` | Race | 10 | 0.7% |
| `race_Moon people - Birkan` | Race | 10 | 0.7% |
| `aff_Cross Guild` | Affiliation | 9 | 0.6% |
| `aff_Franky Family` | Affiliation | 9 | 0.6% |
| `aff_Germa Kingdom` | Affiliation | 9 | 0.6% |
| `aff_Heart Pirates` | Affiliation | 9 | 0.6% |
| `aff_New Fish-Man Pirates` | Affiliation | 9 | 0.6% |
| `aff_Ohara Archaeologists` | Affiliation | 9 | 0.6% |
| `aff_Shimotsuki Family` | Affiliation | 9 | 0.6% |
| `df_sub_Ancient` | Devil Fruit | 9 | 0.6% |
| `height_under_100` | Height | 9 | 0.6% |
| `race_Moon people - Skypiean` | Race | 9 | 0.6% |
| `aff_Arlong Pirates` | Affiliation | 8 | 0.5% |
| `aff_Bellamy Pirates` | Affiliation | 8 | 0.5% |
| `aff_God's Army` | Affiliation | 8 | 0.5% |
| `aff_Knights of God` | Affiliation | 7 | 0.5% |
| `aff_New Spiders Cafe` | Affiliation | 7 | 0.5% |
| `race_Human-Snakeneck hybrid` | Race | 7 | 0.5% |
| `aff_Beasts Pirates (Armored Division)` | Affiliation | 6 | 0.4% |
| `aff_Five Elders` | Affiliation | 6 | 0.4% |
| `aff_Krieg Pirates` | Affiliation | 6 | 0.4% |
| `aff_New Giant Warrior Pirates` | Affiliation | 6 | 0.4% |
| `aff_Poseidon` | Affiliation | 6 | 0.4% |
| `aff_Rocks Pirates` | Affiliation | 6 | 0.4% |
| `aff_Underworld` | Affiliation | 6 | 0.4% |
| `name_vinsmoke` | Misc | 6 | 0.4% |
| `origin_Red Line` | Origin sea | 6 | 0.4% |
| `race_Longarm` | Race | 6 | 0.4% |
| `aff_Automata` | Affiliation | 5 | 0.3% |
| `aff_Baroque Works (Millions)` | Affiliation | 5 | 0.3% |
| `aff_Bonney Pirates` | Affiliation | 5 | 0.3% |
| `aff_Charlotte Family` | Affiliation | 5 | 0.3% |
| `aff_Dressrosa Kingdom` | Affiliation | 5 | 0.3% |
| `aff_Fire Tank Pirates` | Affiliation | 5 | 0.3% |
| `aff_Galley-La Company` | Affiliation | 5 | 0.3% |
| `aff_Germ Pirates` | Affiliation | 5 | 0.3% |
| `aff_Goa Kingdom` | Affiliation | 5 | 0.3% |
| `aff_Marines (SSG)` | Affiliation | 5 | 0.3% |
| `aff_Marines (SWORD)` | Affiliation | 5 | 0.3% |
| `aff_Roshwan Kingdom` | Affiliation | 5 | 0.3% |
| `aff_Ukkari Hot-Spring Island` | Affiliation | 5 | 0.3% |
| `aff_Black Cat Pirates` | Affiliation | 4 | 0.3% |
| `aff_CP9` | Affiliation | 4 | 0.3% |
| `aff_Drum Kingdom` | Affiliation | 4 | 0.3% |
| `aff_God's Guards` | Affiliation | 4 | 0.3% |
| `aff_Ideo Pirates` | Affiliation | 4 | 0.3% |
| `aff_Island of Rare Animals` | Affiliation | 4 | 0.3% |
| `aff_Newkama Land` | Affiliation | 4 | 0.3% |
| `aff_Rebel Army` | Affiliation | 4 | 0.3% |
| `aff_Sun Pirates` | Affiliation | 4 | 0.3% |
| `aff_Vegapunk` | Affiliation | 4 | 0.3% |
| `aff_Warland Kingdom` | Affiliation | 4 | 0.3% |
| `name_kouzuki` | Misc | 4 | 0.3% |
| `race_Human-Longarm hybrid` | Race | 4 | 0.3% |
| `aff_Alvida Pirates (disbanded)` | Affiliation | 3 | 0.2% |
| `aff_Baratie` | Affiliation | 3 | 0.2% |
| `aff_Baroque Works (Billions)` | Affiliation | 3 | 0.2% |
| `aff_Beasts Pirates (Tobiroppo)` | Affiliation | 3 | 0.2% |
| `aff_Beautiful Pirates` | Affiliation | 3 | 0.2% |
| `aff_Dadan Family` | Affiliation | 3 | 0.2% |
| `aff_Endurance Curry Pirates` | Affiliation | 3 | 0.2% |
| `aff_Galley-La Company (Zambai's Company Union)` | Affiliation | 3 | 0.2% |
| `aff_Happo Navy` | Affiliation | 3 | 0.2% |
| `aff_Kyoshiro Family` | Affiliation | 3 | 0.2% |
| `aff_Lvneel Kingdom` | Affiliation | 3 | 0.2% |
| `aff_Macro Pirates` | Affiliation | 3 | 0.2% |
| `aff_Rumbar Pirates` | Affiliation | 3 | 0.2% |
| `aff_Tom's Workers` | Affiliation | 3 | 0.2% |
| `aff_Usopp Pirates (disbanded)` | Affiliation | 3 | 0.2% |
| `aff_Wagomuland` | Affiliation | 3 | 0.2% |
| `aff_World Economy News Paper` | Affiliation | 3 | 0.2% |
| `aff_Yes Pirates` | Affiliation | 3 | 0.2% |
| `name_boa` | Misc | 3 | 0.2% |
| `race_Human-Fish-man hybrid` | Race | 3 | 0.2% |
| `race_Human-Longleg hybrid` | Race | 3 | 0.2% |
| `race_Merfolk-Human hybrid` | Race | 3 | 0.2% |

</details>
