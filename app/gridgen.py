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
   * no pair among the six Categories is subset-related (one playable set
     contained in the other) or on the :data:`DEGENERATE_BLOCKLIST` - so no
     Cell, and no row against another row or column against another column,
     is a gimme.

Match creation also accepts a ``seed`` (making generation reproducible) and/or an
explicit list of six Category ids (forcing a known Grid, or a clear rejection if
that Grid is unsolvable).

The over-large "trivial Category" exclusion (issue #11) lives here as
:func:`is_trivial_category`, a single tunable predicate wired into the random
generation path: a Category whose playable set covers more than
:data:`TRIVIAL_CATEGORY_MAX_ROSTER_FRACTION` of the Roster is dropped before
sampling. A forced Grid (``category_ids``) is a deliberate override and bypasses
it. The threshold and the forced-Grid carve-out are decided in
``docs/adr/0002-trivial-category-exclusion.md``, backed by
``docs/measurements/trivial-category-threshold.md``.
"""

from __future__ import annotations

import itertools
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

#: A Category whose playable set covers more than this fraction of the Roster
#: counts as "trivial" - true for almost everyone, so a poor trivia clue - and is
#: dropped before sampling in :func:`generate_grid`. Setting it to ``None``
#: disables the exclusion (:func:`is_trivial_category` becomes a pass-through).
#:
#: ``0.40`` drops four Categories on the repo dataset - ``status_Alive`` (79%),
#: ``race_Human`` (73%), ``debut_598_9999`` (52%), ``debut_1_597`` (47%) - and
#: sits in a wide gap: the next-broadest survivor, ``age_known``, covers 33%.
#: Decision: ``docs/adr/0002-trivial-category-exclusion.md``. Full measurement
#: (per-Category coverage, attempt counts, Group distribution):
#: ``docs/measurements/trivial-category-threshold.md``.
TRIVIAL_CATEGORY_MAX_ROSTER_FRACTION: float | None = 0.40

#: Category pairings that are degenerate even though neither playable set is a
#: strict subset of the other. Kept small on purpose: strict-subset pairs (e.g.
#: "Can use Haki" vs "Can use Armament Haki") and empty-intersection pairs (e.g.
#: "Bounty >= 1B" vs "Bounty < 100M") are already rejected structurally by
#: :func:`_pairing_is_valid`; this list is for combos that slip past both checks
#: yet still make a Cell a gimme. A later ticket can grow it as such cases turn
#: up in play.
DEGENERATE_BLOCKLIST: frozenset[frozenset[str]] = frozenset(
    {
        # The two examples issue #4 calls out, pinned explicitly so the rule
        # survives any future data change that breaks the structural relation.
        frozenset({"haki_any", "haki_arm"}),
        frozenset({"bounty_1000000000", "bounty_under_100m"}),
        # "All three Haki" against a single specific type: technically an
        # overlap, always a gimme.
        frozenset({"haki_all3", "haki_arm"}),
        frozenset({"haki_all3", "haki_obs"}),
        frozenset({"haki_all3", "haki_conq"}),
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

    ``threshold`` defaults to :data:`TRIVIAL_CATEGORY_MAX_ROSTER_FRACTION`.
    A ``None`` threshold disables the check and this always returns ``False``.
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
    """Whether the six Categories form a playable Grid: no pair among them is
    subset-related or blocklisted, and every row/column Cell has at least one
    Character. Assumes the six Categories are already distinct by id."""

    for a, b in itertools.combinations((*rows, *columns), 2):
        if _is_subset_related(a.characters, b.characters):
            return False
        if is_degenerate_pair(a.category.id, b.category.id):
            return False

    for row in rows:
        for column in columns:
            if not (row.characters & column.characters):
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

    # A forced Grid is a deliberate override, so it deliberately bypasses the
    # trivial-Category filter (:func:`is_trivial_category`) - callers pinning a
    # known Grid (tests, replays, a hand-picked board) get exactly the Categories
    # they name, over-large ones included. It still has to be playable: an
    # unsolvable or degenerate pairing is rejected below.
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
    seed: int | None = None,
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
    seed: int | None = None,
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
