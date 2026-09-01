"""Real Grid generation for a Match.

Creating a Match builds a fresh, playable :class:`~app.domain.Grid`:

1. Sample **six Category Groups uniformly, with replacement**, then pick one
   Category uniformly within each. The first three label the rows, the last
   three the columns. Because sampling is with replacement, a row Category and a
   column Category may land in the same Group; step 2 is what throws out the
   pairings that do not work.
2. Re-roll the whole Grid until **both** hold:

   * every one of the nine Cells has a non-empty
     *row-Category ∩ column-Category* set over the Roster, and
   * no row/column Category pair is subset-related (one playable set contained
     in the other) or on the :data:`DEGENERATE_BLOCKLIST`.

Match creation also accepts a ``seed`` (making generation reproducible) and/or an
explicit list of six Category ids (forcing a known Grid, or a clear rejection if
that Grid is unsolvable).

The over-large "trivial Category" exclusion is deferred (issue #4): it lives here
as :func:`is_trivial_category`, a single tunable predicate wired into the
generation path but currently disabled (:data:`TRIVIAL_CATEGORY_MAX_ROSTER_FRACTION`
is ``None``), so it passes every Category through.
"""

from __future__ import annotations

import random
import uuid
from collections import defaultdict
from collections.abc import Sequence

from app.dataset import GameData, LoadedCategory
from app.domain import Category, Cell, CategoryGroup, Grid, Match, MatchStatus, Player

#: A Grid is six Categories: three rows then three columns.
GRID_CATEGORY_COUNT = 6

#: Safety cap on the re-roll loop. With the repo dataset a valid Grid is found in
#: a few dozen tries; exhausting this many means the candidate pool is too thin.
DEFAULT_MAX_ATTEMPTS = 10_000

#: When set to a fraction in ``(0, 1]``, a Category whose playable set covers more
#: than that fraction of the Roster counts as "trivial" and is dropped before
#: sampling. Deferred (issue #4): kept as the one tunable knob, currently
#: disabled, so :func:`is_trivial_category` is a pass-through.
TRIVIAL_CATEGORY_MAX_ROSTER_FRACTION: float | None = None

#: Row/column Category pairings that are degenerate without one playable set
#: being a strict subset of the other: mutually exclusive or nested Bounty
#: thresholds, and the "any Haki" / "all three Haki" umbrellas against a specific
#: Haki type. Strict-subset and empty-intersection pairs are rejected
#: structurally and need not be listed here.
DEGENERATE_BLOCKLIST: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"haki_any", "haki_arm"}),
        frozenset({"haki_any", "haki_obs"}),
        frozenset({"haki_any", "haki_conq"}),
        frozenset({"haki_any", "haki_all3"}),
        frozenset({"haki_all3", "haki_arm"}),
        frozenset({"haki_all3", "haki_obs"}),
        frozenset({"haki_all3", "haki_conq"}),
        frozenset({"bounty_1", "bounty_under_100m"}),
        frozenset({"bounty_1", "bounty_100000000"}),
        frozenset({"bounty_1", "bounty_500000000"}),
        frozenset({"bounty_1", "bounty_1000000000"}),
        frozenset({"bounty_1", "bounty_1500000000"}),
        frozenset({"bounty_1", "bounty_3000000000"}),
        frozenset({"bounty_under_100m", "bounty_100000000"}),
        frozenset({"bounty_under_100m", "bounty_500000000"}),
        frozenset({"bounty_under_100m", "bounty_1000000000"}),
        frozenset({"bounty_under_100m", "bounty_1500000000"}),
        frozenset({"bounty_under_100m", "bounty_3000000000"}),
    }
)


class GridGenerationError(RuntimeError):
    """No valid Grid could be produced."""


class InvalidForcedGridError(GridGenerationError):
    """An explicit ``category_ids`` list cannot become a Grid: wrong number of
    ids, an id that is not a playable Category, or a Grid that is unsolvable or
    degenerate."""


def is_trivial_category(
    category: LoadedCategory,
    roster_size: int,
    *,
    threshold: float | None = TRIVIAL_CATEGORY_MAX_ROSTER_FRACTION,
) -> bool:
    """Whether ``category`` is too broad to be interesting - its playable set
    covers more than ``threshold`` of the Roster.

    Deferred for issue #4: ``threshold`` defaults to
    :data:`TRIVIAL_CATEGORY_MAX_ROSTER_FRACTION` (``None``), and while it is
    ``None`` this always returns ``False``. Pass an explicit ``threshold`` to
    turn the exclusion on (a later ticket flips the default).
    """

    if threshold is None:
        return False
    return len(category.characters) > threshold * roster_size


def is_degenerate_pair(a_id: str, b_id: str) -> bool:
    """Whether the Categories ``a_id`` and ``b_id`` are on the
    :data:`DEGENERATE_BLOCKLIST` (order-independent)."""

    return frozenset({a_id, b_id}) in DEGENERATE_BLOCKLIST


def _is_subset_related(a: frozenset[str], b: frozenset[str]) -> bool:
    """Whether one playable set is contained in the other (equality counts)."""

    return a <= b or b <= a


def _pairing_is_valid(
    rows: Sequence[LoadedCategory], columns: Sequence[LoadedCategory]
) -> bool:
    """Whether every row/column Cell is solvable and no row/column pair is
    subset-related or blocklisted. Assumes the six Categories are distinct."""

    for row in rows:
        for column in columns:
            if not (row.characters & column.characters):
                return False
            if _is_subset_related(row.characters, column.characters):
                return False
            if is_degenerate_pair(row.category.id, column.category.id):
                return False
    return True


def _empty_cells() -> tuple[Cell, ...]:
    return tuple(Cell(row=r, column=c) for r in range(3) for c in range(3))


def _build_grid(
    rows: Sequence[LoadedCategory], columns: Sequence[LoadedCategory]
) -> Grid:
    return Grid(
        row_categories=(rows[0].category, rows[1].category, rows[2].category),
        column_categories=(
            columns[0].category,
            columns[1].category,
            columns[2].category,
        ),
        cells=_empty_cells(),
    )


def _forced_grid(data: GameData, category_ids: Sequence[str]) -> Grid:
    if len(category_ids) != GRID_CATEGORY_COUNT:
        raise InvalidForcedGridError(
            f"expected {GRID_CATEGORY_COUNT} Category ids, got {len(category_ids)}"
        )
    if len(set(category_ids)) != GRID_CATEGORY_COUNT:
        raise InvalidForcedGridError("the six Category ids must be distinct")

    by_id = {c.category.id: c for c in data.categories}
    missing = [cid for cid in category_ids if cid not in by_id]
    if missing:
        raise InvalidForcedGridError(
            f"unknown or non-playable Category id(s): {', '.join(missing)}"
        )

    chosen = [by_id[cid] for cid in category_ids]
    rows, columns = chosen[:3], chosen[3:]
    if not _pairing_is_valid(rows, columns):
        raise InvalidForcedGridError(
            "that Grid is unsolvable or degenerate: some Cell has no valid "
            "Character, or a row/column pair is subset-related or blocklisted"
        )
    return _build_grid(rows, columns)


def generate_grid(
    data: GameData,
    *,
    seed: int | str | None = None,
    category_ids: Sequence[str] | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> Grid:
    """Generate a playable :class:`~app.domain.Grid` from ``data``.

    ``seed`` makes the search reproducible. ``category_ids`` (six ids: three rows
    then three columns) forces a specific Grid, raising
    :class:`InvalidForcedGridError` if it cannot stand. Raises
    :class:`GridGenerationError` if no valid Grid turns up within
    ``max_attempts`` re-rolls.
    """

    if category_ids is not None:
        return _forced_grid(data, category_ids)

    roster_size = len(data.roster)
    pool = [
        c for c in data.categories if not is_trivial_category(c, roster_size)
    ]
    by_group: dict[CategoryGroup, list[LoadedCategory]] = defaultdict(list)
    for category in pool:
        by_group[category.category.group].append(category)
    groups = sorted(by_group, key=lambda g: g.value)

    if not groups:
        raise GridGenerationError("no Categories available to generate a Grid")

    rng = random.Random(seed)
    for _ in range(max_attempts):
        sampled_groups = [rng.choice(groups) for _ in range(GRID_CATEGORY_COUNT)]
        chosen = [rng.choice(by_group[group]) for group in sampled_groups]
        if len({c.category.id for c in chosen}) != GRID_CATEGORY_COUNT:
            continue
        rows, columns = chosen[:3], chosen[3:]
        if _pairing_is_valid(rows, columns):
            return _build_grid(rows, columns)

    raise GridGenerationError(
        f"no solvable Grid found in {max_attempts} attempts"
    )


def new_match(
    data: GameData,
    *,
    seed: int | str | None = None,
    category_ids: Sequence[str] | None = None,
    match_id: str | None = None,
    first_player: Player | None = None,
) -> Match:
    """Create a fresh in-progress Match on a newly generated Grid.

    A match id and the first Player are chosen when not supplied. Under a fixed
    ``seed`` (and without an explicit ``match_id``/``first_player``) everything
    but the generated id is reproducible.
    """

    grid = generate_grid(data, seed=seed, category_ids=category_ids)
    player_rng = random.Random(seed)
    return Match(
        id=match_id or uuid.uuid4().hex,
        grid=grid,
        active_player=first_player or player_rng.choice((Player.P1, Player.P2)),
        status=MatchStatus.IN_PROGRESS,
    )
