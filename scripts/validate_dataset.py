"""Gate a candidate dataset against the committed baseline (ADR 0004).

A **Refresh** re-pulls the **Raw dataset** from **Upstream** and rebuilds the
derived files. Before a candidate can be accepted, :func:`validate_dataset`
compares it against the last committed :class:`~app.dataset.GameData` and returns
an ordered list of :class:`Finding` objects, each with a :class:`Severity`:

* **BLOCK** - the candidate is broken or unplayable. CI red, cannot merge.
* **REVIEW** - a Grid-generation invariant (ADR-0002 / ADR-0003) moved. CI stays
  green; a human decides whether to file a tuning issue. The validator never
  edits ``TRIVIAL_CATEGORY_MAX_ROSTER_FRACTION`` / ``MIN_VALID_PARTNERS`` /
  ``VALID_PARTNER_WEIGHT_EXPONENT`` - it only flags.
* **INFO** - the roster / count / join deltas a reviewer wants in the PR body.

"What the game sees" and "what the validator checks" cannot diverge: resolution
goes through :func:`app.dataset.GameData.from_raw` /
:func:`app.dataset.resolve_categories` and the Grid-generation knobs through
:func:`app.gridgen.generation_pool` / :func:`app.gridgen.generate_grid`, never a
re-implementation.

The numeric thresholds are pinned in
``docs/measurements/dataset-validation-thresholds.md``.

Run ``python -m scripts.validate_dataset`` to check the working-tree files
against ``HEAD``; it exits non-zero iff any finding is BLOCK.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from app.dataset import (
    CATEGORIES_PATH,
    CHARACTERS_PATH,
    VIABLE_THRESHOLD,
    GameData,
)
from app.domain import CategoryGroup
from app.gridgen import (
    GenerationPool,
    GridGenerationError,
    generate_grid,
    generation_pool,
)
from scripts.build_categories import build_categories

# Repo root: this file is ``<root>/scripts/validate_dataset.py``.
REPO_ROOT = Path(__file__).resolve().parent.parent
DEVIL_FRUITS_PATH = REPO_ROOT / "devil_fruits.json"
ISLANDS_PATH = REPO_ROOT / "islands.json"

#: The Trivial Category set ADR-0002 pins (CONTEXT.md: exactly these two).
EXPECTED_TRIVIAL_IDS: frozenset[str] = frozenset({"status_Alive", "race_Human"})


@dataclass(frozen=True)
class Thresholds:
    """The pinned numeric knobs. Defaults are pinned against the committed
    dataset in ``docs/measurements/dataset-validation-thresholds.md``; tests
    pass their own so a small fixture can trip one trigger at a time.
    """

    #: BLOCK when fewer than this many Categories survive resolution.
    #: Committed dataset: 195 playable -> floor 175 (~10% headroom).
    min_surviving_categories: int = 175
    #: BLOCK when the Grid-generation smoke test fails for any seed in
    #: ``range(smoke_test_seeds)``.
    smoke_test_seeds: int = 25
    #: REVIEW when a Category Group's share of the generation pool moves by more
    #: than this many percentage points versus the baseline.
    group_share_drift_pct: float = 5.0
    #: REVIEW when the count of unresolved Category-referenced names grows by
    #: more than this versus the baseline.
    new_unresolved_names: int = 10
    #: INFO line for any Category whose playable-set size moves by more than this
    #: versus the baseline.
    count_delta: int = 25


DEFAULT_THRESHOLDS = Thresholds()


class Severity(Enum):
    """A finding's severity, ordered most-serious first (:data:`_SEVERITY_RANK`)."""

    BLOCK = "BLOCK"
    REVIEW = "REVIEW"
    INFO = "INFO"


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.BLOCK: 0,
    Severity.REVIEW: 1,
    Severity.INFO: 2,
}


@dataclass(frozen=True)
class Finding:
    """One thing the validator noticed: a :class:`Severity`, a short kebab-case
    ``trigger`` slug (stable, for tests and dashboards), and a human-readable
    ``message``."""

    severity: Severity
    trigger: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.value}] {self.message}"


@dataclass(frozen=True)
class RawDataset:
    """Parsed Upstream JSON, before resolution.

    ``characters`` / ``categories`` are what :func:`GameData.from_raw` consumes;
    ``devil_fruits`` / ``islands`` back the Upstream shape check and the builder
    unjoinable-join report. A candidate that arrives as a :class:`RawDataset`
    goes through the shape check and the load before any comparison runs - and
    on a shape failure the fetched file must not be written over the vendored
    copy (ADR 0004).
    """

    characters: Any
    categories: Any
    devil_fruits: Any = None
    islands: Any = None


Candidate = GameData | RawDataset


# --- Upstream shape check (BLOCK) ----------------------------------------------


def _check_array_of_named_objects(value: Any, *, source: str) -> list[Finding]:
    """Every Upstream file is a JSON array of objects each carrying a string
    ``name``. Anything else is Upstream schema drift."""

    if not isinstance(value, list):
        return [
            Finding(
                Severity.BLOCK,
                "upstream-shape",
                f"{source}: top-level value is {type(value).__name__}, "
                f"expected a JSON array",
            )
        ]

    findings: list[Finding] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            findings.append(
                Finding(
                    Severity.BLOCK,
                    "upstream-shape",
                    f"{source}: entry {index} is {type(entry).__name__}, "
                    f"expected an object",
                )
            )
        elif "name" not in entry:
            findings.append(
                Finding(
                    Severity.BLOCK,
                    "upstream-shape",
                    f"{source}: entry {index} is missing the required "
                    f"'name' key",
                )
            )
        elif not isinstance(entry["name"], str):
            findings.append(
                Finding(
                    Severity.BLOCK,
                    "upstream-shape",
                    f"{source}: entry {index} has a non-string 'name' "
                    f"({type(entry['name']).__name__})",
                )
            )
    return findings


def check_upstream_shape(raw: RawDataset) -> list[Finding]:
    """BLOCK findings for any Upstream file that fails the array-of-named-objects
    shape. ``devil_fruits`` / ``islands`` are only checked when present."""

    findings = _check_array_of_named_objects(raw.characters, source="characters.json")
    if raw.devil_fruits is not None:
        findings += _check_array_of_named_objects(
            raw.devil_fruits, source="devil_fruits.json"
        )
    if raw.islands is not None:
        findings += _check_array_of_named_objects(raw.islands, source="islands.json")
    return findings


# --- load (BLOCK) ------------------------------------------------------------


def _load_candidate(candidate: Candidate) -> tuple[GameData | None, list[Finding]]:
    """The candidate as a :class:`GameData`, or ``None`` plus a BLOCK finding if
    it will not load. A :class:`GameData` candidate is already loaded."""

    if isinstance(candidate, GameData):
        return candidate, []
    try:
        data = GameData.from_raw(candidate.characters, candidate.categories)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return None, [
            Finding(
                Severity.BLOCK,
                "dataset-load-failed",
                f"candidate dataset failed to load: {type(exc).__name__}: {exc}",
            )
        ]
    return data, []


# --- BLOCK checks over the candidate alone ----------------------------------


def _check_surviving_category_floor(
    data: GameData, thresholds: Thresholds
) -> list[Finding]:
    surviving = len(data.categories)
    if surviving < thresholds.min_surviving_categories:
        return [
            Finding(
                Severity.BLOCK,
                "surviving-category-floor",
                f"only {surviving} Categories survive resolution, below the "
                f"pinned floor of {thresholds.min_surviving_categories}",
            )
        ]
    return []


def _check_grid_smoke_test(
    data: GameData, thresholds: Thresholds
) -> list[Finding]:
    failed: list[int] = []
    for seed in range(thresholds.smoke_test_seeds):
        try:
            generate_grid(data, seed=seed)
        except GridGenerationError:
            failed.append(seed)
    if failed:
        return [
            Finding(
                Severity.BLOCK,
                "grid-smoke-test",
                f"Grid generation produced no solvable Grid for "
                f"{len(failed)}/{thresholds.smoke_test_seeds} smoke-test seeds "
                f"(first: seed {failed[0]}) - the candidate pool is too thin",
            )
        ]
    return []


def _check_category_groups_nonempty(
    candidate: GenerationPool, baseline: GenerationPool
) -> list[Finding]:
    # Baseline-relative: BLOCK a Group that *had* usable Categories and now has
    # none. An absolute "any Group with zero pool Categories" check would fire on
    # Groups that are legitimately all-trivial or all-tiny in a healthy dataset
    # (e.g. Status), so the Refresh gate keys on the regression, not the state.
    candidate_groups = {c.category.group for c in candidate.pool}
    baseline_groups = {c.category.group for c in baseline.pool}
    emptied = sorted(baseline_groups - candidate_groups, key=lambda g: g.value)
    return [
        Finding(
            Severity.BLOCK,
            "category-group-emptied",
            f"Category Group {group.value!r} has no usable Categories left "
            f"(every one excluded as trivial or Dead); it had some in the "
            f"baseline",
        )
        for group in emptied
    ]


# --- REVIEW checks (candidate vs baseline) ---------------------------------


def _check_trivial_set(candidate: GenerationPool) -> list[Finding]:
    trivial = frozenset(c.category.id for c in candidate.trivial)
    if trivial != EXPECTED_TRIVIAL_IDS:
        return [
            Finding(
                Severity.REVIEW,
                "trivial-set-changed",
                f"the Trivial Category set is now {sorted(trivial)}, no longer "
                f"exactly {sorted(EXPECTED_TRIVIAL_IDS)} (ADR-0002)",
            )
        ]
    return []


def _check_dead_category_count(
    candidate: GenerationPool, baseline: GenerationPool
) -> list[Finding]:
    now = len(candidate.dead)
    before = len(baseline.dead)
    if now != before:
        return [
            Finding(
                Severity.REVIEW,
                "dead-category-count-moved",
                f"the Dead Category count moved {before} -> {now} (ADR-0003)",
            )
        ]
    return []


def _check_viable_dropouts(
    data: GameData, baseline: GameData
) -> list[Finding]:
    """A Category that was playable in the baseline but is not in the candidate.
    ``report.excluded_categories`` - resolution's own list of Categories dropped
    for falling below the Viable threshold - separates a genuine sub-Viable drop
    from a predicate that was removed or renamed outright."""

    was_playable = {c.category.id for c in baseline.categories}
    still_playable = {c.category.id for c in data.categories}
    excluded_now = set(data.report.excluded_categories)

    sub_viable = sorted(was_playable & excluded_now)
    missing = sorted(was_playable - still_playable - excluded_now)
    if not sub_viable and not missing:
        return []

    parts: list[str] = []
    if sub_viable:
        parts.append(
            f"{len(sub_viable)} fell below the Viable threshold "
            f"({VIABLE_THRESHOLD}): {', '.join(sub_viable)}"
        )
    if missing:
        parts.append(
            f"{len(missing)} no longer resolve at all: {', '.join(missing)}"
        )
    return [
        Finding(
            Severity.REVIEW,
            "viable-dropout",
            "previously-playable Categories dropped - " + "; ".join(parts),
        )
    ]


def _group_share_pct(pool: GenerationPool) -> dict[CategoryGroup, float]:
    total = len(pool.pool)
    counts = Counter(c.category.group for c in pool.pool)
    return {
        group: (100.0 * counts.get(group, 0) / total if total else 0.0)
        for group in CategoryGroup
    }


def _check_group_share_drift(
    candidate_pool: GenerationPool,
    baseline_pool: GenerationPool,
    thresholds: Thresholds,
) -> list[Finding]:
    candidate = _group_share_pct(candidate_pool)
    base = _group_share_pct(baseline_pool)
    findings: list[Finding] = []
    for group in CategoryGroup:
        drift = candidate[group] - base[group]
        if abs(drift) > thresholds.group_share_drift_pct:
            findings.append(
                Finding(
                    Severity.REVIEW,
                    "group-share-drift",
                    f"Category Group {group.value!r} share of the generation "
                    f"pool moved {base[group]:.1f}% -> {candidate[group]:.1f}% "
                    f"({drift:+.1f} pts), past the "
                    f"{thresholds.group_share_drift_pct:g}-pt threshold",
                )
            )
    return findings


def _check_newly_unresolved_names(
    data: GameData, baseline: GameData, thresholds: Thresholds
) -> list[Finding]:
    candidate = data.report.unresolved_name_count
    base = baseline.report.unresolved_name_count
    grew_by = candidate - base
    if grew_by > thresholds.new_unresolved_names:
        return [
            Finding(
                Severity.REVIEW,
                "newly-unresolved-names",
                f"{grew_by} more Category-referenced names fail to resolve than "
                f"in the baseline ({base} -> {candidate}), past the threshold "
                f"of {thresholds.new_unresolved_names}",
            )
        ]
    return []


# --- INFO checks ---------------------------------------------------------------

#: The text inside a ``[...]`` / ``(...)`` segment of a name, e.g. ``Kouzuki Toki``
#: from ``Amatsuki Toki [Kouzuki Toki]`` - Upstream's rename shape keeps the old
#: name in brackets, so an old name that equals one of these segments is a rename.
_BRACKETED_SEGMENT = re.compile(r"[\[(]\s*([^\])]*?)\s*[\])]")


def _summarise(names: Iterable[str], *, limit: int = 20) -> str:
    ordered = sorted(names)
    if len(ordered) <= limit:
        return ", ".join(ordered)
    return ", ".join(ordered[:limit]) + f", and {len(ordered) - limit} more"


def _is_rename_of(old: str, new: str) -> bool:
    """Whether ``new`` looks like Upstream's rename of ``old``: either ``old`` is
    kept verbatim as a ``[...]`` / ``(...)`` segment of ``new``
    (``Kouzuki Toki`` -> ``Amatsuki Toki [Kouzuki Toki]``), or one is a
    whole-token prefix/suffix of the other (``Marco`` <-> ``Marco the Phoenix``).
    Case-folded; names under three characters are too ambiguous to pair."""

    lo, hi = old.casefold(), new.casefold()
    if len(lo) < 3 or len(hi) < 3:
        return False
    if lo in (m.casefold() for m in _BRACKETED_SEGMENT.findall(new)):
        return True
    short, long = sorted((lo, hi), key=len)
    return long.startswith(f"{short} ") or long.endswith(f" {short}")


def _rename_pairs(
    added: frozenset[str], removed: frozenset[str]
) -> tuple[list[tuple[str, str]], set[str], set[str]]:
    """Split the roster's added / removed names into ``(renames, still_added,
    still_removed)`` - a rename being a removed name that :func:`_is_rename_of`
    an added one. Each added name pairs at most once."""

    still_added = set(added)
    renames: list[tuple[str, str]] = []
    for old in sorted(removed):
        match = next(
            (new for new in sorted(still_added) if _is_rename_of(old, new)),
            None,
        )
        if match is not None:
            renames.append((old, match))
            still_added.discard(match)
    renamed_old = {old for old, _ in renames}
    return renames, still_added, set(removed) - renamed_old


def _character_roster_info(
    data: GameData, baseline: GameData
) -> list[Finding]:
    added = data.roster - baseline.roster
    removed = baseline.roster - data.roster
    if not added and not removed:
        return []

    renames, still_added, still_removed = _rename_pairs(added, removed)
    findings: list[Finding] = []
    if renames:
        shown = "; ".join(f"{old!r} -> {new!r}" for old, new in renames[:20])
        if len(renames) > 20:
            shown += f"; and {len(renames) - 20} more"
        findings.append(
            Finding(
                Severity.INFO,
                "characters-renamed",
                f"{len(renames)} Character(s) renamed since the baseline: {shown}",
            )
        )
    if still_added:
        findings.append(
            Finding(
                Severity.INFO,
                "characters-added",
                f"{len(still_added)} Character(s) added since the baseline: "
                f"{_summarise(still_added)}",
            )
        )
    if still_removed:
        findings.append(
            Finding(
                Severity.INFO,
                "characters-removed",
                f"{len(still_removed)} Character(s) removed since the baseline: "
                f"{_summarise(still_removed)}",
            )
        )
    return findings


def _count_delta_info(
    data: GameData, baseline: GameData, thresholds: Thresholds
) -> list[Finding]:
    base_size = {c.category.id: len(c.characters) for c in baseline.categories}
    moved: list[tuple[str, int, int]] = []
    for category in data.categories:
        before = base_size.get(category.category.id)
        if before is None:
            continue
        after = len(category.characters)
        if abs(after - before) > thresholds.count_delta:
            moved.append((category.category.id, before, after))
    if not moved:
        return []

    moved.sort(key=lambda row: abs(row[2] - row[1]), reverse=True)
    detail = "; ".join(
        f"{cid} {before}->{after} ({after - before:+d})"
        for cid, before, after in moved[:20]
    )
    if len(moved) > 20:
        detail += f"; and {len(moved) - 20} more"
    noun = "Category" if len(moved) == 1 else "Categories"
    return [
        Finding(
            Severity.INFO,
            "count-delta",
            f"{len(moved)} {noun} moved by more than {thresholds.count_delta} "
            f"resolved Characters: {detail}",
        )
    ]


def _named_rows(value: Any) -> set[str]:
    """The ``name`` of every object in a parsed Upstream array; ``set()`` for
    anything that is not such an array (the shape check reports that separately)."""

    if not isinstance(value, list):
        return set()
    return {
        entry["name"]
        for entry in value
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }


def _new_join_rows_info(
    candidate: Candidate, baseline_raw: RawDataset | None
) -> list[Finding]:
    """New ``devil_fruits.json`` / ``islands.json`` rows since the baseline -
    the ADR-0004 "new devil fruits / islands" INFO lines. Needs both the
    candidate and the baseline as :class:`RawDataset` (the derived
    :class:`GameData` carries neither file)."""

    if not isinstance(candidate, RawDataset) or baseline_raw is None:
        return []

    findings: list[Finding] = []
    for label, cand_value, base_value in (
        ("Devil Fruit", candidate.devil_fruits, baseline_raw.devil_fruits),
        ("island", candidate.islands, baseline_raw.islands),
    ):
        if cand_value is None or base_value is None:
            continue
        new = sorted(_named_rows(cand_value) - _named_rows(base_value))
        if new:
            findings.append(
                Finding(
                    Severity.INFO,
                    "new-devil-fruits" if label == "Devil Fruit" else "new-islands",
                    f"{len(new)} new {label}(s) since the baseline: "
                    f"{_summarise(new)}",
                )
            )
    return findings


def _builder_report_info(candidate: Candidate) -> list[Finding]:
    """The builder's unjoinable-join report, when the candidate carries the
    ``devil_fruits`` / ``islands`` files the join needs."""

    if not isinstance(candidate, RawDataset):
        return []
    if candidate.devil_fruits is None or candidate.islands is None:
        return []

    report = build_categories(
        candidate.characters, candidate.devil_fruits, candidate.islands
    ).report
    findings: list[Finding] = []
    if report.unjoinable_devil_fruits:
        findings.append(
            Finding(
                Severity.INFO,
                "unjoinable-devil-fruits",
                f"{len(report.unjoinable_devil_fruits)} devil_fruit value(s) do "
                f"not join devil_fruits.json: "
                f"{_summarise(report.unjoinable_devil_fruits)}",
            )
        )
    if report.unjoinable_journey_locations:
        findings.append(
            Finding(
                Severity.INFO,
                "unjoinable-journey-locations",
                f"{len(report.unjoinable_journey_locations)} journey location(s) "
                f"do not join islands.json: "
                f"{_summarise(report.unjoinable_journey_locations)}",
            )
        )
    return findings


# --- orchestration ---------------------------------------------------------


def _ordered(findings: Iterable[Finding]) -> list[Finding]:
    """Findings by severity (BLOCK, then REVIEW, then INFO); stable within a
    severity, so check order is preserved."""

    return sorted(findings, key=lambda f: _SEVERITY_RANK[f.severity])


def validate_dataset(
    candidate: Candidate,
    baseline: GameData,
    *,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
    baseline_raw: RawDataset | None = None,
) -> list[Finding]:
    """Validate ``candidate`` (a :class:`GameData` or a :class:`RawDataset`)
    against ``baseline``. Pure: no file writes, no knob edits. Returns the
    findings ordered by :class:`Severity`.

    A :class:`RawDataset` is shape-checked first; a BLOCK there stops the run
    (the fetched file must not overwrite the vendored copy, ADR 0004). Then the
    candidate is loaded - a failure is its own BLOCK - and the comparison runs.

    ``baseline_raw`` is the baseline's :class:`RawDataset` when the caller has
    it; only the "new Devil Fruits / islands" INFO lines need it, since the
    derived ``baseline`` :class:`GameData` carries neither file.
    """

    findings: list[Finding] = []

    if isinstance(candidate, RawDataset):
        shape = check_upstream_shape(candidate)
        if any(f.severity is Severity.BLOCK for f in shape):
            return _ordered(shape)
        findings += shape

    data, load_findings = _load_candidate(candidate)
    findings += load_findings
    if data is None:
        return _ordered(findings)

    # The trivial / Dead-Category split (:func:`app.gridgen.generation_pool`) is
    # the same derivation generate_grid samples from; compute it once per side
    # and thread it into every check that needs it.
    candidate_pool = generation_pool(data)
    baseline_pool = generation_pool(baseline)

    findings += _check_surviving_category_floor(data, thresholds)
    findings += _check_grid_smoke_test(data, thresholds)
    findings += _check_category_groups_nonempty(candidate_pool, baseline_pool)

    findings += _check_trivial_set(candidate_pool)
    findings += _check_dead_category_count(candidate_pool, baseline_pool)
    findings += _check_viable_dropouts(data, baseline)
    findings += _check_group_share_drift(candidate_pool, baseline_pool, thresholds)
    findings += _check_newly_unresolved_names(data, baseline, thresholds)

    findings += _character_roster_info(data, baseline)
    findings += _count_delta_info(data, baseline, thresholds)
    findings += _new_join_rows_info(candidate, baseline_raw)
    findings += _builder_report_info(candidate)

    return _ordered(findings)


# --- __main__ ------------------------------------------------------------------


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _git_show_json(path_from_root: str) -> Any:
    """The ``HEAD`` version of a repo file, parsed. Raises
    :class:`subprocess.CalledProcessError` when the path is not committed."""

    completed = subprocess.run(
        ["git", "show", f"HEAD:{path_from_root}"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout.decode("utf-8"))


def _committed_raw() -> RawDataset:
    """The ``HEAD`` version of all four dataset files - the baseline side."""

    return RawDataset(
        characters=_git_show_json("characters.json"),
        categories=_git_show_json("categories.json"),
        devil_fruits=_git_show_json("devil_fruits.json"),
        islands=_git_show_json("islands.json"),
    )


def exit_code(findings: Iterable[Finding]) -> int:
    """The ``__main__`` exit code for a run: 1 iff any finding is BLOCK, else 0.
    REVIEW and INFO never fail the run (ADR 0004: REVIEW is a human checkpoint on
    a green build)."""

    return 1 if any(f.severity is Severity.BLOCK for f in findings) else 0


def main() -> int:
    """Validate the working-tree dataset against ``HEAD``. Prints the findings;
    returns 1 iff any is BLOCK."""

    candidate = RawDataset(
        characters=_read_json(CHARACTERS_PATH),
        categories=_read_json(CATEGORIES_PATH),
        devil_fruits=_read_json(DEVIL_FRUITS_PATH),
        islands=_read_json(ISLANDS_PATH),
    )
    baseline_raw = _committed_raw()
    baseline = GameData.from_raw(baseline_raw.characters, baseline_raw.categories)

    findings = validate_dataset(candidate, baseline, baseline_raw=baseline_raw)
    for finding in findings:
        print(finding)

    tally = Counter(f.severity for f in findings)
    print(
        f"\n{tally[Severity.BLOCK]} BLOCK, "
        f"{tally[Severity.REVIEW]} REVIEW, "
        f"{tally[Severity.INFO]} INFO"
    )
    return exit_code(findings)


if __name__ == "__main__":
    sys.exit(main())
