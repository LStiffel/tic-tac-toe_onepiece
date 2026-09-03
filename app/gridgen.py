"""Real Grid generation for a Match.

Creating a Match builds a fresh, playable :class:`~app.domain.Grid`:

1. Sample **six Category Groups uniformly, with replacement**, then pick one
   Category within each - weighted, not uniform (see below). The first three
   label the rows, the last three the columns. Because Group sampling is with
   replacement, a row Category and a column Category may land in the same Group;
   step 2 is what throws out the pairings that do not work.
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

Two tunables shape the random-generation candidate pool; a forced Grid
(``category_ids``) is a deliberate override and bypasses both.

* The over-large **trivial Category** exclusion (issue #11):
  :func:`is_trivial_category` drops any Category whose playable set covers more
  than :data:`TRIVIAL_CATEGORY_MAX_ROSTER_FRACTION` of the Roster.
  ``docs/adr/0002-trivial-category-exclusion.md``,
  ``docs/measurements/trivial-category-threshold.md``.
* The **Category Group evening** (issue #12): a Category's count of *Valid
  partners* (CONTEXT.md; :func:`valid_partner_counts`) - other pool Categories it
  could sit opposite on a Grid and still make a playable Cell - drives both a
  prune of **Dead Categories** with fewer than :data:`MIN_VALID_PARTNERS` (they
  cannot sit in any solvable Grid) and a
  ``count ** VALID_PARTNER_WEIGHT_EXPONENT`` weight on the within-Group draw, so
  the better-connected Categories of a thin Group (Affiliation, Race) are
  proposed far more often than its long tail and the solvability filter rejects
  fewer candidates. ``docs/adr/0003-even-category-group-sampling.md``,
  ``docs/measurements/category-group-sampling.md``.
"""

from __future__ import annotations

import itertools
import random
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache

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
#: ``0.60`` drops the two Categories that are true for a clear majority of the
#: Roster - ``status_Alive`` (79%) and ``race_Human`` (73%) - while keeping the
#: chapter-debut buckets (``debut_598_9999`` at 52%, ``debut_1_597`` at 47%) as
#: legitimate trivia axes. Decision:
#: ``docs/adr/0002-trivial-category-exclusion.md``. Full measurement
#: (per-Category coverage, attempt counts, Group distribution):
#: ``docs/measurements/trivial-category-threshold.md``.
TRIVIAL_CATEGORY_MAX_ROSTER_FRACTION: float | None = 0.60

#: Issue #12 - even out the Category Group mix across generated Grids. Both knobs
#: below key on a Category's count of **Valid partners** (CONTEXT.md;
#: :func:`valid_partner_counts`): other pool Categories it could sit opposite on
#: a Grid and still make a playable Cell - non-empty intersection, neither
#: playable set a subset of the other, pair not on :data:`DEGENERATE_BLOCKLIST`.
#: That is exactly what the solvability re-roll filters on, so the count predicts
#: how often a Category survives to a finished Grid.
#:
#: A **Dead Category** with fewer than this many Valid partners cannot fill a row
#: or a column of any solvable Grid, so :func:`generate_grid` drops it from the
#: candidate pool up front. On the repo dataset this removes ~11 tiny Affiliation
#: / Race Categories. Set to ``0`` to disable the prune.
MIN_VALID_PARTNERS = 3

#: Within a Group, a Category is drawn with weight
#: ``valid_partner_count ** VALID_PARTNER_WEIGHT_EXPONENT``. ``2`` pulls the
#: post-filter Group shares from a ~1%-16% spread to ~3.5%-13% while *cutting*
#: re-roll attempts (thin Groups stop feeding the filter candidates it always
#: rejects). ``0`` recovers a uniform within-Group draw. Groups themselves stay
#: uniform. Decision: ``docs/adr/0003-even-category-group-sampling.md``; measured
#: effect: ``docs/measurements/category-group-sampling.md``.
VALID_PARTNER_WEIGHT_EXPONENT = 2

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


def _valid_partner(a: LoadedCategory, b: LoadedCategory) -> bool:
    """Whether ``a`` and ``b`` are Valid partners (CONTEXT.md): they could sit on
    opposite axes of a Grid and make a playable Cell - their playable sets
    intersect, neither contains the other, and the pair is not on
    :data:`DEGENERATE_BLOCKLIST`. Callers pass two distinct Categories."""

    if not (a.characters & b.characters):
        return False
    if _is_subset_related(a.characters, b.characters):
        return False
    return not is_degenerate_pair(a.category.id, b.category.id)


# maxsize: one entry per distinct candidate pool - the repo dataset in normal
# use, plus a few hand-built ones while tests run.
@lru_cache(maxsize=8)
def valid_partner_counts(pool: tuple[LoadedCategory, ...]) -> dict[str, int]:
    """Map each Category id in ``pool`` to its number of :func:`_valid_partner`
    Categories within ``pool``.

    This is O(len(pool)^2) frozenset intersections, so it is cached on the pool
    tuple - which :func:`generation_pool` rebuilds identically on every call for
    a given dataset. The returned dict must not be mutated by callers.
    """

    counts = {c.category.id: 0 for c in pool}
    for a, b in itertools.combinations(pool, 2):
        if _valid_partner(a, b):
            counts[a.category.id] += 1
            counts[b.category.id] += 1
    return counts


@dataclass(frozen=True)
class GenerationPool:
    """The candidate pool :func:`generate_grid`'s random path draws from, and the
    two sets it excludes on the way - laid out so a caller that must reason about
    *what the game sees* (e.g. ``scripts/validate_dataset.py``) reuses this
    derivation instead of repeating it.

    * :attr:`pool` - the playable Categories that survive both exclusions, in
      ``data.categories`` order.
    * :attr:`trivial` - Categories dropped by :func:`is_trivial_category`
      (issue #11).
    * :attr:`dead` - **Dead Categories** (CONTEXT.md): non-trivial Categories
      with fewer than :data:`MIN_VALID_PARTNERS` Valid partners (issue #12).
    * :attr:`partner_counts` - :func:`valid_partner_counts` over the *non-trivial*
      Categories (trivial ones excluded first), the map both the prune and the
      within-Group weighting key on.
    """

    pool: tuple[LoadedCategory, ...]
    trivial: tuple[LoadedCategory, ...]
    dead: tuple[LoadedCategory, ...]
    partner_counts: Mapping[str, int]


def generation_pool(data: GameData) -> GenerationPool:
    """Split ``data``'s playable Categories the way :func:`generate_grid` does:
    drop the trivial ones, then the Dead ones, and keep the rest as the sampling
    pool. See :class:`GenerationPool`."""

    roster_size = len(data.roster)
    trivial: list[LoadedCategory] = []
    non_trivial: list[LoadedCategory] = []
    for category in data.categories:
        target = (
            trivial
            if is_trivial_category(category, roster_size)
            else non_trivial
        )
        target.append(category)

    partner_counts = valid_partner_counts(tuple(non_trivial))
    dead: list[LoadedCategory] = []
    pool: list[LoadedCategory] = []
    for category in non_trivial:
        target = (
            pool
            if partner_counts[category.category.id] >= MIN_VALID_PARTNERS
            else dead
        )
        target.append(category)

    return GenerationPool(
        pool=tuple(pool),
        trivial=tuple(trivial),
        dead=tuple(dead),
        partner_counts=partner_counts,
    )


def _pairing_is_valid(
    rows: Sequence[LoadedCategory], columns: Sequence[LoadedCategory]
) -> bool:
    """Whether the six Categories form a playable Grid: every row/column Cell has
    at least one Character and no such pair is subset-related or blocklisted
    (:func:`_valid_partner`), and no two Categories on the *same* axis are
    subset-related or blocklisted either. Assumes the six are distinct by id."""

    for row in rows:
        for column in columns:
            if not _valid_partner(row, column):
                return False

    for axis in (rows, columns):
        for a, b in itertools.combinations(axis, 2):
            if _is_subset_related(a.characters, b.characters):
                return False
            if is_degenerate_pair(a.category.id, b.category.id):
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

    The random path drops trivial Categories (:func:`is_trivial_category`, issue
    #11) and Dead Categories with fewer than :data:`MIN_VALID_PARTNERS` Valid
    partners (issue #12), then draws six Groups uniformly and one Category per
    Group weighted by ``valid-partner count ** VALID_PARTNER_WEIGHT_EXPONENT``.
    """

    if category_ids is not None:
        return _forced_grid(data, category_ids)

    # The trivial + Dead-Category split (:func:`generation_pool`). partner_counts
    # is over the non-trivial Categories and is reused for the within-Group
    # weights below: the pruned Dead Categories have < MIN_VALID_PARTNERS
    # partners each, so re-counting on the survivors would move no weight worth
    # the second O(n^2) pass; docs/measurements/category-group-sampling.md uses
    # these same counts.
    gen_pool = generation_pool(data)
    pool = gen_pool.pool
    partner_counts = gen_pool.partner_counts

    by_group: dict[CategoryGroup, list[LoadedCategory]] = defaultdict(list)
    for category in pool:
        by_group[category.category.group].append(category)
    groups = sorted(by_group, key=lambda g: g.value)

    if not groups:
        raise GridGenerationError("no Categories available to generate a Grid")

    # Per-Category weights for the within-Group draw; the Group draw itself stays
    # uniform. Rationale on VALID_PARTNER_WEIGHT_EXPONENT.
    weights = {
        group: [
            partner_counts[c.category.id] ** VALID_PARTNER_WEIGHT_EXPONENT
            for c in members
        ]
        for group, members in by_group.items()
    }

    rng = random.Random(seed)
    for _ in range(max_attempts):
        sampled_groups = rng.choices(groups, k=GRID_CATEGORY_COUNT)
        chosen = [
            rng.choices(by_group[group], weights=weights[group], k=1)[0]
            for group in sampled_groups
        ]
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
