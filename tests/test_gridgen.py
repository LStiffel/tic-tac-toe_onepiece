"""Seam 2 - real Grid generation, no HTTP.

Property tests run over the repo dataset (``default_game_data``); the exact
"forced Grid" and rejection tests use a small hand-built :class:`GameData` so
the assertions are precise (see ``docs/agents/testing.md``).
"""

from __future__ import annotations

from collections import Counter

import pytest

from app.dataset import (
    DataQualityReport,
    GameData,
    LoadedCategory,
    default_game_data,
)
from app.domain import Category, CategoryGroup, Grid, MatchStatus, Player
from app.gridgen import (
    MIN_VALID_PARTNERS,
    TRIVIAL_CATEGORY_MAX_ROSTER_FRACTION,
    GridGenerationError,
    InvalidForcedGridError,
    generate_grid,
    is_degenerate_pair,
    is_trivial_category,
    new_match,
)

# --- a small crafted dataset ------------------------------------------------
#
# Twelve Characters ``c1``..``c12`` and Categories with hand-picked playable
# sets. The six "grid" Categories are all size six and pairwise distinct, so no
# one is a subset of another, and every row x column intersection below is
# non-empty - a forced Grid over them stands.

_ROSTER = frozenset(f"c{i}" for i in range(1, 13))


def _cat(cid: str, group: CategoryGroup, members: set[str]) -> LoadedCategory:
    return LoadedCategory(
        category=Category(id=cid, label=cid.replace("_", " ").title(), group=group),
        count=len(members),
        characters=frozenset(members),
    )


_C = {c.category.id: c for c in (
    # rows
    _cat("race_A", CategoryGroup.RACE, {"c1", "c2", "c3", "c4", "c5", "c6"}),
    _cat("bounty_hi", CategoryGroup.BOUNTY, {"c4", "c5", "c6", "c7", "c8", "c9"}),
    _cat("haki_x", CategoryGroup.HAKI, {"c1", "c2", "c7", "c8", "c9", "c10"}),
    # columns
    _cat("age_old", CategoryGroup.AGE, {"c1", "c4", "c7", "c10", "c11", "c12"}),
    _cat("height_tall", CategoryGroup.HEIGHT, {"c2", "c3", "c5", "c8", "c9", "c11"}),
    _cat("origin_eb", CategoryGroup.ORIGIN_SEA, {"c1", "c3", "c6", "c8", "c9", "c12"}),
    # spares
    _cat("visited_x", CategoryGroup.VISITED, {"c2", "c4", "c6", "c8", "c10", "c12"}),
    # deliberately disjoint from race_A - forces an unsolvable Cell if paired.
    _cat("race_far", CategoryGroup.RACE, {"c10", "c11", "c12"}),
)}

_ROW_IDS = ["race_A", "bounty_hi", "haki_x"]
_COL_IDS = ["age_old", "height_tall", "origin_eb"]
_FORCED = _ROW_IDS + _COL_IDS


def _crafted_data() -> GameData:
    return GameData(roster=_ROSTER, categories=tuple(_C.values()), report=DataQualityReport())


def _grid_ids(grid: Grid) -> tuple[str, ...]:
    return tuple(c.id for c in (*grid.row_categories, *grid.column_categories))


# --- determinism ----------------------------------------------------------


def test_same_seed_yields_the_same_grid() -> None:
    data = default_game_data()

    first = generate_grid(data, seed=20260901)
    second = generate_grid(data, seed=20260901)

    assert _grid_ids(first) == _grid_ids(second)
    assert first == second


def test_different_seeds_generally_yield_different_grids() -> None:
    data = default_game_data()

    grids = {_grid_ids(generate_grid(data, seed=s)) for s in range(30)}

    # Not a guarantee, but 30 seeds collapsing to a handful would be a bug.
    assert len(grids) >= 25


# --- solvability + subset/blocklist over a large sample ------------------


def test_every_generated_cell_has_at_least_one_valid_character() -> None:
    data = default_game_data()
    by_id = {c.category.id: c for c in data.categories}

    for seed in range(200):
        grid = generate_grid(data, seed=seed)
        for row in grid.row_categories:
            for col in grid.column_categories:
                intersection = by_id[row.id].characters & by_id[col.id].characters
                assert intersection, (seed, row.id, col.id)


def test_no_row_column_pair_is_subset_related_or_blocklisted() -> None:
    data = default_game_data()
    by_id = {c.category.id: c for c in data.categories}

    for seed in range(200):
        grid = generate_grid(data, seed=seed)
        for row in grid.row_categories:
            for col in grid.column_categories:
                r, c = by_id[row.id].characters, by_id[col.id].characters
                assert not (r <= c or c <= r), (seed, row.id, col.id)
                assert not is_degenerate_pair(row.id, col.id), (seed, row.id, col.id)


def test_generated_grid_uses_six_distinct_categories() -> None:
    data = default_game_data()

    for seed in range(100):
        assert len(set(_grid_ids(generate_grid(data, seed=seed)))) == 6


def test_no_two_rows_and_no_two_columns_are_subset_related() -> None:
    data = default_game_data()
    by_id = {c.category.id: c for c in data.categories}

    for seed in range(200):
        grid = generate_grid(data, seed=seed)
        for axis in (grid.row_categories, grid.column_categories):
            for a, b in ((0, 1), (0, 2), (1, 2)):
                sa = by_id[axis[a].id].characters
                sb = by_id[axis[b].id].characters
                assert not (sa <= sb or sb <= sa), (seed, axis[a].id, axis[b].id)


# --- Category Group distribution ---------------------------------------


def test_category_groups_are_distributed_roughly_evenly() -> None:
    data = default_game_data()
    groups_with_categories = {c.category.group for c in data.categories}

    counts: Counter[CategoryGroup] = Counter()
    sample = 300
    for seed in range(sample):
        grid = generate_grid(data, seed=seed)
        for cat in (*grid.row_categories, *grid.column_categories):
            counts[cat.group] += 1

    total = sum(counts.values())
    assert total == sample * 6

    shares = {group: n / total for group, n in counts.items()}
    top_share = max(shares.values())
    floor_share = min(shares.values())

    # Groups are drawn uniformly; within a Group the draw is weighted toward
    # Categories with more Valid partners and the Dead Category prune trims the
    # tail, so the solvability filter no longer collapses the thin Groups (issue
    # #12). A uniform draw over the 12 Groups would be ~8.3% each; the weighting
    # leaves a real spread but a bounded one. Numbers measured in
    # docs/measurements/category-group-sampling.md (300 seeds): top ~12%
    # (Misc), floor ~3.7% (Affiliation), top/floor ~3.2. The bounds below carry
    # margin for dataset drift while still failing if a Group slides back toward
    # the pre-#12 ~1% floor or a Group runs away past ~16%.
    assert len(counts) == len(groups_with_categories), counts
    assert top_share < 0.16, shares
    assert floor_share >= 0.025, shares
    assert top_share / floor_share < 5.0, shares


def test_group_sampling_is_with_replacement() -> None:
    """A row Category and a column Category may come from the same Group when
    the pairing survives the filter - i.e. Groups are not forced distinct."""

    data = default_game_data()

    def has_repeated_group(seed: int) -> bool:
        grid = generate_grid(data, seed=seed)
        groups = [c.group for c in (*grid.row_categories, *grid.column_categories)]
        return len(set(groups)) < 6

    assert any(has_repeated_group(s) for s in range(60))


def test_no_generated_grid_uses_a_dead_category() -> None:
    """A Dead Category (CONTEXT.md) has fewer than ``MIN_VALID_PARTNERS`` Valid
    partners - Categories it could share a Cell with: non-empty intersection,
    neither playable set a subset of the other, pair not blocklisted. It cannot
    sit in any solvable Grid, so issue #12 drops it from the candidate pool
    before sampling (mirrors ``test_no_generated_grid_uses_a_trivial_category``).
    """

    data = default_game_data()
    roster_size = len(data.roster)
    pool = [c for c in data.categories if not is_trivial_category(c, roster_size)]

    def valid_partner_count(cat: LoadedCategory) -> int:
        count = 0
        for other in pool:
            if other.category.id == cat.category.id:
                continue
            if not (cat.characters & other.characters):
                continue
            if (
                cat.characters <= other.characters
                or other.characters <= cat.characters
            ):
                continue
            if is_degenerate_pair(cat.category.id, other.category.id):
                continue
            count += 1
        return count

    dead = {
        c.category.id for c in pool
        if valid_partner_count(c) < MIN_VALID_PARTNERS
    }
    assert dead, "expected some Category too sparsely connected to keep"

    for seed in range(300):
        grid = generate_grid(data, seed=seed)
        assert not (set(_grid_ids(grid)) & dead), (seed, sorted(dead))


# --- forced Grids -------------------------------------------------------


def test_explicit_category_ids_produce_exactly_that_grid() -> None:
    data = _crafted_data()

    grid = generate_grid(data, category_ids=_FORCED)

    assert [c.id for c in grid.row_categories] == _ROW_IDS
    assert [c.id for c in grid.column_categories] == _COL_IDS
    assert len(grid.cells) == 9
    assert all(cell.is_empty for cell in grid.cells)


def test_forced_grid_is_independent_of_seed() -> None:
    data = _crafted_data()

    a = generate_grid(data, category_ids=_FORCED, seed=1)
    b = generate_grid(data, category_ids=_FORCED, seed=999)

    assert _grid_ids(a) == _grid_ids(b) == tuple(_FORCED)


def test_forced_grid_with_an_unsolvable_cell_is_rejected() -> None:
    data = _crafted_data()
    # race_A (c1..c6) against race_far (c10..c12): empty intersection.
    forced = ["race_A", "bounty_hi", "haki_x", "race_far", "height_tall", "origin_eb"]

    with pytest.raises(InvalidForcedGridError):
        generate_grid(data, category_ids=forced)


def test_forced_grid_with_an_unknown_category_id_is_rejected() -> None:
    data = _crafted_data()
    forced = [*_ROW_IDS, "age_old", "height_tall", "no_such_id"]

    with pytest.raises(InvalidForcedGridError):
        generate_grid(data, category_ids=forced)


def test_forced_grid_needs_exactly_six_ids() -> None:
    data = _crafted_data()

    with pytest.raises(InvalidForcedGridError):
        generate_grid(data, category_ids=_ROW_IDS)


def test_forced_grid_rejects_a_blocklisted_pair_that_is_not_a_subset() -> None:
    # haki_any vs haki_arm overlap but neither contains the other; the pair is
    # on the degenerate-combo blocklist, so it must still be rejected.
    assert is_degenerate_pair("haki_any", "haki_arm")
    assert is_degenerate_pair("haki_arm", "haki_any")  # order-independent

    data = GameData(
        roster=_ROSTER,
        categories=(
            _cat("haki_any", CategoryGroup.HAKI, {"c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"}),
            _cat("haki_arm", CategoryGroup.HAKI, {"c5", "c6", "c7", "c8", "c9", "c10"}),
            _C["bounty_hi"], _C["age_old"], _C["height_tall"], _C["origin_eb"],
        ),
        report=DataQualityReport(),
    )
    forced = ["haki_any", "bounty_hi", "age_old", "haki_arm", "height_tall", "origin_eb"]

    with pytest.raises(InvalidForcedGridError):
        generate_grid(data, category_ids=forced)


# --- the "trivial Category" exclusion (issue #11) --------------------


def test_trivial_category_exclusion_is_enabled() -> None:
    # Flipped from None in issue #11. The value and its measurement live in
    # docs/adr/0002-trivial-category-exclusion.md and docs/measurements/.
    assert TRIVIAL_CATEGORY_MAX_ROSTER_FRACTION is not None
    assert 0 < TRIVIAL_CATEGORY_MAX_ROSTER_FRACTION <= 1


def test_trivial_category_predicate_uses_the_module_default_threshold() -> None:
    covers_everyone = _cat("misc_all", CategoryGroup.MISC, set(_ROSTER))
    small = _C["race_far"]  # 3 of 12

    # No explicit threshold: falls back to TRIVIAL_CATEGORY_MAX_ROSTER_FRACTION.
    assert is_trivial_category(covers_everyone, len(_ROSTER)) is True
    assert is_trivial_category(small, len(_ROSTER)) is False


def test_trivial_category_predicate_is_tunable_when_a_threshold_is_given() -> None:
    covers_everyone = _cat("misc_all", CategoryGroup.MISC, set(_ROSTER))
    small = _C["race_far"]  # 3 of 12

    assert is_trivial_category(covers_everyone, len(_ROSTER), threshold=0.4) is True
    assert is_trivial_category(small, len(_ROSTER), threshold=0.4) is False
    # An explicit None still turns the check off.
    assert is_trivial_category(covers_everyone, len(_ROSTER), threshold=None) is False


def test_no_generated_grid_uses_a_trivial_category() -> None:
    data = default_game_data()
    roster_size = len(data.roster)
    by_id = {c.category.id: c for c in data.categories}

    for seed in range(500):
        grid = generate_grid(data, seed=seed)
        for cat in _grid_ids(grid):
            assert not is_trivial_category(by_id[cat], roster_size), (seed, cat)


def test_generation_succeeds_for_every_seed_in_a_large_sample() -> None:
    # Enabling the exclusion thins the pool; every seed must still yield a Grid
    # (no GridGenerationError) well inside DEFAULT_MAX_ATTEMPTS.
    data = default_game_data()

    for seed in range(500):
        grid = generate_grid(data, seed=seed)
        assert len(set(_grid_ids(grid))) == 6


def test_forced_grid_may_use_a_trivial_category() -> None:
    # A forced Grid is an explicit override: it bypasses the trivial-Category
    # exclusion, so a Category well over the threshold is still allowed.
    big = _cat(  # 9 of 12 crafted Characters = 75%, over any sane threshold
        "misc_big", CategoryGroup.MISC, {f"c{i}" for i in range(1, 10)}
    )
    cats = (
        big,
        _cat("race_low", CategoryGroup.RACE, {"c1", "c2", "c3", "c10", "c11", "c12"}),
        _cat("bounty_mid", CategoryGroup.BOUNTY, {"c4", "c5", "c6", "c10", "c11", "c12"}),
        _cat("age_a", CategoryGroup.AGE, {"c1", "c4", "c7", "c10"}),
        _cat("height_b", CategoryGroup.HEIGHT, {"c2", "c5", "c8", "c11"}),
        _cat("origin_c", CategoryGroup.ORIGIN_SEA, {"c3", "c6", "c9", "c12"}),
    )
    data = GameData(roster=_ROSTER, categories=cats, report=DataQualityReport())
    forced = [c.category.id for c in cats]
    assert is_trivial_category(big, len(_ROSTER))

    grid = generate_grid(data, category_ids=forced)

    assert _grid_ids(grid) == tuple(forced)


# --- new_match --------------------------------------------------------


def test_new_match_is_in_progress_on_a_generated_grid() -> None:
    match = new_match(default_game_data(), seed=3, match_id="fixed", first_player=Player.P1)

    assert match.id == "fixed"
    assert match.active_player is Player.P1
    assert match.status is MatchStatus.IN_PROGRESS
    assert len(match.grid.cells) == 9
    assert {(c.row, c.column) for c in match.grid.cells} == {
        (r, c) for r in range(3) for c in range(3)
    }
    assert all(cell.is_empty for cell in match.grid.cells)


def test_new_match_generates_a_unique_id_when_none_given() -> None:
    data = default_game_data()
    assert new_match(data).id != new_match(data).id


def test_new_match_under_a_fixed_seed_is_fully_reproducible() -> None:
    data = default_game_data()

    a = new_match(data, seed=123, match_id="m")
    b = new_match(data, seed=123, match_id="m")

    assert a == b


def test_unsatisfiable_search_raises_grid_generation_error() -> None:
    # A dataset with a single Category cannot fill six distinct slots.
    data = GameData(
        roster=_ROSTER,
        categories=(_C["race_A"],),
        report=DataQualityReport(),
    )

    with pytest.raises(GridGenerationError):
        generate_grid(data, seed=1, max_attempts=50)
