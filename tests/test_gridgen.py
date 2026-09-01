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
# Twelve Characters ``c1``..``c12`` and a handful of Categories with hand-picked
# playable sets, spread across enough Groups that random generation has room to
# find a valid Grid.

_ROSTER = frozenset(f"c{i}" for i in range(1, 13))


def _cat(cid: str, group: CategoryGroup, members: set[str]) -> LoadedCategory:
    return LoadedCategory(
        category=Category(id=cid, label=cid.replace("_", " ").title(), group=group),
        count=len(members),
        characters=frozenset(members),
    )


_C = {c.category.id: c for c in (
    _cat("race_A", CategoryGroup.RACE, {"c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"}),
    _cat("bounty_hi", CategoryGroup.BOUNTY, {"c1", "c2", "c3", "c4", "c5", "c6"}),
    _cat("haki_x", CategoryGroup.HAKI, {"c2", "c3", "c4", "c5", "c6", "c7", "c8", "c9"}),
    _cat("age_old", CategoryGroup.AGE, {"c1", "c3", "c4", "c5", "c6", "c7", "c9"}),
    _cat("height_tall", CategoryGroup.HEIGHT, {"c3", "c4", "c5", "c6", "c7", "c8", "c9", "c10"}),
    _cat("df_zoan", CategoryGroup.DEVIL_FRUIT, {"c1", "c3", "c4", "c5", "c7", "c9", "c11"}),
    _cat("origin_eb", CategoryGroup.ORIGIN_SEA, {"c2", "c3", "c4", "c6", "c8", "c10", "c12"}),
    _cat("status_alive", CategoryGroup.STATUS, {"c1", "c2", "c3", "c4", "c5", "c6", "c7"}),
    _cat("visited_x", CategoryGroup.VISITED, {"c2", "c3", "c4", "c5", "c6", "c8", "c9"}),
    # deliberately disjoint from race_A - forces an unsolvable Cell if paired.
    _cat("race_far", CategoryGroup.RACE, {"c9", "c10", "c11"}),
)}


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

    # Tolerance-based: sampling is uniform-with-replacement before the
    # solvability filter, so shares are not equal, but no Group should
    # dominate and almost every Group should show up.
    top_share = max(counts.values()) / total
    assert top_share < 0.30, counts
    assert len(counts) >= len(groups_with_categories) - 2, counts


def test_group_sampling_is_with_replacement() -> None:
    """A row Category and a column Category may come from the same Group when
    the pairing survives the filter - i.e. Groups are not forced distinct."""

    data = default_game_data()

    def has_repeated_group(seed: int) -> bool:
        grid = generate_grid(data, seed=seed)
        groups = [c.group for c in (*grid.row_categories, *grid.column_categories)]
        return len(set(groups)) < 6

    assert any(has_repeated_group(s) for s in range(60))


# --- forced Grids -------------------------------------------------------


def test_explicit_category_ids_produce_exactly_that_grid() -> None:
    data = _crafted_data()

    forced = ["race_A", "bounty_hi", "haki_x", "age_old", "height_tall", "origin_eb"]
    grid = generate_grid(data, category_ids=forced)

    assert [c.id for c in grid.row_categories] == forced[:3]
    assert [c.id for c in grid.column_categories] == forced[3:]
    assert len(grid.cells) == 9
    assert all(cell.is_empty for cell in grid.cells)


def test_forced_grid_is_independent_of_seed() -> None:
    data = _crafted_data()
    forced = ["race_A", "bounty_hi", "haki_x", "age_old", "height_tall", "origin_eb"]

    a = generate_grid(data, category_ids=forced, seed=1)
    b = generate_grid(data, category_ids=forced, seed=999)

    assert _grid_ids(a) == _grid_ids(b) == tuple(forced)


def test_forced_grid_with_an_unsolvable_cell_is_rejected() -> None:
    data = _crafted_data()
    # race_A (c1..c8) against race_far (c9..c11): empty intersection.
    forced = ["race_A", "bounty_hi", "haki_x", "race_far", "height_tall", "origin_eb"]

    with pytest.raises(InvalidForcedGridError):
        generate_grid(data, category_ids=forced)


def test_forced_grid_with_an_unknown_category_id_is_rejected() -> None:
    data = _crafted_data()
    forced = ["race_A", "bounty_hi", "haki_x", "age_old", "height_tall", "no_such_id"]

    with pytest.raises(InvalidForcedGridError):
        generate_grid(data, category_ids=forced)


def test_forced_grid_needs_exactly_six_ids() -> None:
    data = _crafted_data()

    with pytest.raises(InvalidForcedGridError):
        generate_grid(data, category_ids=["race_A", "bounty_hi", "haki_x"])


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


# --- the deferred "trivial Category" predicate ------------------------


def test_trivial_category_predicate_is_currently_a_no_op() -> None:
    assert TRIVIAL_CATEGORY_MAX_ROSTER_FRACTION is None

    covers_everyone = _cat("misc_all", CategoryGroup.MISC, set(_ROSTER))
    # Disabled: even a Category matching the entire Roster is not "trivial".
    assert is_trivial_category(covers_everyone, len(_ROSTER)) is False


def test_trivial_category_predicate_is_tunable_when_a_threshold_is_given() -> None:
    covers_everyone = _cat("misc_all", CategoryGroup.MISC, set(_ROSTER))
    small = _C["race_far"]  # 3 of 12

    assert is_trivial_category(covers_everyone, len(_ROSTER), threshold=0.4) is True
    assert is_trivial_category(small, len(_ROSTER), threshold=0.4) is False


def test_generation_still_succeeds_with_the_trivial_predicate_disabled() -> None:
    # Nothing is filtered out today, so the repo dataset must still generate.
    grid = generate_grid(default_game_data(), seed=7)
    assert len(grid.cells) == 9


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
