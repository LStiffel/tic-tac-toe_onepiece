"""Seam 2 - the Refresh-gate validator, no HTTP (issue #21, ADR 0004).

One test per BLOCK / REVIEW / INFO trigger. The dataset shapes are hand-built:
a small "healthy" :class:`GameData` (:func:`_healthy`) whose generation pool has
several Category Groups and whose Trivial Category set is exactly the ADR-0002
pair, then a one-line mutation per test so a single trigger fires. Assertions
are on the stable ``trigger`` slug and the finding's :class:`Severity`.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.dataset import DataQualityReport, GameData, LoadedCategory
from app.domain import Category, CategoryGroup
from scripts import validate_dataset as vd
from scripts.validate_dataset import (
    Finding,
    RawDataset,
    Severity,
    Thresholds,
    check_upstream_shape,
    exit_code,
    validate_dataset,
)

# Lenient floor / smoke count: the healthy fixture has only ~13 Categories, so
# the pinned defaults would raise the surviving-Category BLOCK in every test.
_LENIENT = Thresholds(min_surviving_categories=1, smoke_test_seeds=6)


def _roster() -> frozenset[str]:
    return frozenset(f"p{i:02d}" for i in range(1, 21))


def _members(*ids: int) -> frozenset[str]:
    return frozenset(f"p{i:02d}" for i in ids)


def _cat(cid: str, group: CategoryGroup, members: frozenset[str]) -> LoadedCategory:
    return LoadedCategory(
        category=Category(id=cid, label=cid, group=group),
        count=len(members),
        characters=members,
    )


_HEALTHY_CATEGORIES: tuple[LoadedCategory, ...] = (
    # Two Trivial Categories - exactly the ADR-0002 pair (> 60% of the 20-name
    # Roster).
    _cat("status_Alive", CategoryGroup.STATUS, _members(*range(1, 16))),
    _cat("race_Human", CategoryGroup.RACE, _members(*range(1, 14))),
    # A generation pool of 11 across five Groups, every Category with >= 3 Valid
    # partners (no Dead Categories). Bounty has three so a single drop still
    # leaves the Group in the pool.
    _cat("bounty_a", CategoryGroup.BOUNTY, _members(1, 2, 3, 4, 5, 6, 7)),
    _cat("bounty_b", CategoryGroup.BOUNTY, _members(5, 6, 7, 8, 9, 10, 11)),
    _cat("bounty_c", CategoryGroup.BOUNTY, _members(2, 3, 4, 9, 10, 11, 12)),
    _cat("haki_a", CategoryGroup.HAKI, _members(3, 4, 5, 6, 7, 8, 9)),
    _cat("haki_b", CategoryGroup.HAKI, _members(8, 9, 10, 11, 12, 13, 14)),
    _cat("age_a", CategoryGroup.AGE, _members(10, 11, 12, 13, 14, 15, 16)),
    _cat("age_b", CategoryGroup.AGE, _members(1, 2, 14, 15, 16, 17, 18)),
    _cat("df_a", CategoryGroup.DEVIL_FRUIT, _members(2, 4, 6, 8, 10, 12, 19)),
    _cat("df_b", CategoryGroup.DEVIL_FRUIT, _members(3, 6, 9, 12, 15, 18, 20)),
    _cat("visited_x", CategoryGroup.VISITED, _members(1, 5, 9, 13, 17, 19, 20)),
    _cat("visited_y", CategoryGroup.VISITED, _members(2, 7, 11, 14, 16, 18, 20)),
)


def _healthy() -> GameData:
    return GameData(
        roster=_roster(),
        categories=_HEALTHY_CATEGORIES,
        report=DataQualityReport(),
    )


def _without(data: GameData, *ids: str) -> GameData:
    kept = tuple(c for c in data.categories if c.category.id not in ids)
    return dataclasses.replace(data, categories=kept)


def _replace_members(
    data: GameData, cid: str, members: frozenset[str]
) -> GameData:
    kept = tuple(
        _cat(c.category.id, c.category.group, members)
        if c.category.id == cid
        else c
        for c in data.categories
    )
    return dataclasses.replace(data, categories=kept)


def _triggers(findings: list[Finding]) -> set[str]:
    return {f.trigger for f in findings}


def _one(findings: list[Finding], trigger: str) -> Finding:
    matched = [f for f in findings if f.trigger == trigger]
    assert len(matched) == 1, f"expected exactly one {trigger!r} in {findings}"
    return matched[0]


# --- BLOCK triggers ---------------------------------------------------------


def test_unloadable_candidate_is_block() -> None:
    # Passes the Upstream shape check (characters are well-formed) but a
    # Category row is missing its "characters" key, so resolution KeyErrors.
    candidate = RawDataset(
        characters=[{"name": "Nami"}, {"name": "Luffy"}],
        categories=[{"id": "race_Human", "label": "Race: Human"}],
    )

    findings = validate_dataset(candidate, _healthy(), thresholds=_LENIENT)

    finding = _one(findings, "dataset-load-failed")
    assert finding.severity is Severity.BLOCK
    assert "KeyError" in finding.message


def test_emptied_category_group_is_block() -> None:
    candidate = _without(_healthy(), "haki_a", "haki_b")

    findings = validate_dataset(candidate, _healthy(), thresholds=_LENIENT)

    finding = _one(findings, "category-group-emptied")
    assert finding.severity is Severity.BLOCK
    assert "Haki" in finding.message


def test_surviving_category_count_below_floor_is_block() -> None:
    findings = validate_dataset(
        _healthy(),
        _healthy(),
        thresholds=Thresholds(min_surviving_categories=100),
    )

    finding = _one(findings, "surviving-category-floor")
    assert finding.severity is Severity.BLOCK
    assert "13" in finding.message and "100" in finding.message


def test_smoke_test_finds_no_solvable_grid_is_block() -> None:
    # Six Categories over six Groups with pairwise-disjoint playable sets: every
    # pairing is an empty Cell, so no Grid is solvable.
    disjoint = tuple(
        _cat(f"g{i}", group, _members(i))
        for i, group in enumerate(list(CategoryGroup)[:6])
    )
    unsolvable = GameData(
        roster=_roster(), categories=disjoint, report=DataQualityReport()
    )

    findings = validate_dataset(unsolvable, unsolvable, thresholds=_LENIENT)

    finding = _one(findings, "grid-smoke-test")
    assert finding.severity is Severity.BLOCK


def test_upstream_shape_wrong_top_level_type_is_block() -> None:
    raw = RawDataset(characters={"characters": []}, categories=[])

    findings = check_upstream_shape(raw)

    assert [f.severity for f in findings] == [Severity.BLOCK]
    assert findings[0].trigger == "upstream-shape"
    assert "expected a JSON array" in findings[0].message


def test_upstream_shape_missing_required_key_is_block() -> None:
    raw = RawDataset(
        characters=[{"name": "Nami"}, {"race": "Human"}],  # entry 1 has no name
        categories=[],
        devil_fruits=[{"name": "Gomu Gomu no Mi"}],
        islands=[{"name": "Water 7"}],
    )

    findings = check_upstream_shape(raw)

    finding = _one(findings, "upstream-shape")
    assert finding.severity is Severity.BLOCK
    assert "entry 1 is missing the required 'name' key" in finding.message


def test_shape_block_short_circuits_before_the_comparison() -> None:
    raw = RawDataset(characters=42, categories=[])

    findings = validate_dataset(raw, _healthy())

    # Only the shape BLOCK: nothing downstream (load, pool checks) ran.
    assert _triggers(findings) == {"upstream-shape"}


# --- REVIEW triggers -------------------------------------------------------


def test_trivial_set_change_is_review() -> None:
    # race_Human drops to a handful, so it is no longer Trivial.
    candidate = _replace_members(_healthy(), "race_Human", _members(1, 2, 3))

    findings = validate_dataset(candidate, _healthy(), thresholds=_LENIENT)

    finding = _one(findings, "trivial-set-changed")
    assert finding.severity is Severity.REVIEW
    assert "race_Human" in finding.message


def test_dead_category_count_move_is_review() -> None:
    isolated = _cat("misc_island", CategoryGroup.MISC, frozenset({"z1", "z2", "z3"}))
    candidate = dataclasses.replace(
        _healthy(), categories=_HEALTHY_CATEGORIES + (isolated,)
    )

    findings = validate_dataset(candidate, _healthy(), thresholds=_LENIENT)

    finding = _one(findings, "dead-category-count-moved")
    assert finding.severity is Severity.REVIEW
    assert "0 -> 1" in finding.message


def test_category_below_viable_threshold_is_review() -> None:
    # df_b is gone from the playable set *and* named in the resolution report's
    # excluded list - a genuine sub-Viable drop, not a removed predicate.
    candidate = dataclasses.replace(
        _without(_healthy(), "df_b"),
        report=DataQualityReport(excluded_categories=("df_b",)),
    )

    findings = validate_dataset(candidate, _healthy(), thresholds=_LENIENT)

    finding = _one(findings, "viable-dropout")
    assert finding.severity is Severity.REVIEW
    assert "df_b" in finding.message
    assert "Viable threshold (3)" in finding.message


def test_group_pool_share_drift_is_review() -> None:
    candidate = _without(_healthy(), "bounty_c")  # Bounty 3 -> 2 of the pool

    findings = validate_dataset(candidate, _healthy(), thresholds=_LENIENT)

    finding = _one(findings, "group-share-drift")
    assert finding.severity is Severity.REVIEW
    assert "Bounty" in finding.message


def test_newly_unresolved_names_over_threshold_is_review() -> None:
    ghosts = tuple(f"Ghost {i}" for i in range(15))
    candidate = dataclasses.replace(
        _healthy(), report=DataQualityReport(unresolved={"bounty_a": ghosts})
    )

    findings = validate_dataset(candidate, _healthy(), thresholds=_LENIENT)

    finding = _one(findings, "newly-unresolved-names")
    assert finding.severity is Severity.REVIEW
    assert "0 -> 15" in finding.message


# --- INFO triggers -------------------------------------------------------


def test_character_added_removed_renamed_are_info() -> None:
    baseline = _healthy()
    roster = (baseline.roster - {"p19", "p20"}) | {
        "New Rookie",
        "Amatsuki p19 [p19]",  # keeps the old name in brackets -> a rename
    }
    candidate = dataclasses.replace(baseline, roster=roster)

    findings = validate_dataset(candidate, baseline, thresholds=_LENIENT)

    renamed = _one(findings, "characters-renamed")
    added = _one(findings, "characters-added")
    removed = _one(findings, "characters-removed")
    assert all(
        f.severity is Severity.INFO for f in (renamed, added, removed)
    )
    assert "'p19' -> 'Amatsuki p19 [p19]'" in renamed.message
    assert "New Rookie" in added.message and "New Rookie" not in removed.message
    assert "p20" in removed.message


def test_count_delta_summary_is_info() -> None:
    big = frozenset(f"x{i}" for i in range(50))
    candidate = _replace_members(_healthy(), "status_Alive", big)

    findings = validate_dataset(candidate, _healthy(), thresholds=_LENIENT)

    finding = _one(findings, "count-delta")
    assert finding.severity is Severity.INFO
    assert "status_Alive 15->50 (+35)" in finding.message


def test_new_devil_fruits_and_islands_are_info() -> None:
    chars = [{"name": "Nami"}, {"name": "Luffy"}, {"name": "Zoro"}]
    candidate = RawDataset(
        characters=chars,
        categories=[],
        devil_fruits=[{"name": "Gomu Gomu no Mi"}, {"name": "Ope Ope no Mi"}],
        islands=[{"name": "Water 7"}, {"name": "Egghead"}],
    )
    baseline_raw = RawDataset(
        characters=chars,
        categories=[],
        devil_fruits=[{"name": "Gomu Gomu no Mi"}],
        islands=[{"name": "Water 7"}],
    )

    findings = validate_dataset(
        candidate,
        GameData.from_raw(chars, []),
        thresholds=_LENIENT,
        baseline_raw=baseline_raw,
    )

    devil_fruits = _one(findings, "new-devil-fruits")
    islands = _one(findings, "new-islands")
    assert devil_fruits.severity is Severity.INFO
    assert "Ope Ope no Mi" in devil_fruits.message
    assert islands.severity is Severity.INFO
    assert "Egghead" in islands.message


def test_no_findings_when_candidate_equals_baseline() -> None:
    findings = validate_dataset(_healthy(), _healthy(), thresholds=_LENIENT)

    assert findings == []


# --- __main__ exit code --------------------------------------------------


def test_block_finding_makes_the_run_exit_non_zero() -> None:
    assert exit_code([Finding(Severity.BLOCK, "x", "boom")]) == 1


def test_review_and_info_only_run_exits_zero() -> None:
    findings = [
        Finding(Severity.REVIEW, "trivial-set-changed", "..."),
        Finding(Severity.INFO, "characters-added", "..."),
    ]

    assert exit_code(findings) == 0


def test_main_exits_zero_against_the_committed_dataset() -> None:
    assert vd.main() == 0


def test_main_exits_non_zero_when_validation_reports_a_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        vd,
        "validate_dataset",
        lambda *a, **k: [Finding(Severity.BLOCK, "grid-smoke-test", "thin pool")],
    )

    assert vd.main() == 1
