"""Seam 2 - the Roster / Category loader, no HTTP.

Every test builds a tiny hand-made ``characters.json`` / ``categories.json``
shape so the assertions on the data-quality report are exact (see
``docs/agents/testing.md``).
"""

from __future__ import annotations

import logging
import unicodedata

import pytest

from app.dataset import (
    VIABLE_THRESHOLD,
    GameData,
    build_roster,
    canonical_name,
    group_for_id,
    log_data_quality,
    resolve_categories,
)
from app.domain import CategoryGroup


# --- canonical_name -------------------------------------------------------


def test_canonical_name_trims_and_collapses_whitespace() -> None:
    assert canonical_name("  Monkey   D.  Luffy \t") == "Monkey D. Luffy"


def test_canonical_name_applies_unicode_nfc() -> None:
    # "Nic" + "o" + COMBINING ACUTE ACCENT (U+0301) - decomposed form.
    decomposed = "Nic" + "o" + "́"
    composed = unicodedata.normalize("NFC", decomposed)

    assert decomposed != composed  # sanity: the two forms really differ
    assert canonical_name(decomposed) == composed
    assert canonical_name("  " + decomposed + " ") == composed


# --- build_roster -------------------------------------------------------


def test_build_roster_is_the_set_of_canonical_names() -> None:
    roster = build_roster([{"name": "Zoro"}, {"name": "Nami"}])

    assert roster == {"Zoro", "Nami"}


def test_build_roster_collapses_names_that_differ_only_by_whitespace() -> None:
    roster = build_roster([{"name": "Bjorn"}, {"name": "Bjorn "}])

    assert roster == {"Bjorn"}


# --- group_for_id -------------------------------------------------------


def test_group_for_id_maps_each_known_prefix() -> None:
    assert group_for_id("bounty_100000000") is CategoryGroup.BOUNTY
    assert group_for_id("race_Fish-man") is CategoryGroup.RACE
    assert group_for_id("status_Alive") is CategoryGroup.STATUS
    assert group_for_id("aff_Marine") is CategoryGroup.AFFILIATION
    assert group_for_id("origin_East Blue") is CategoryGroup.ORIGIN_SEA
    assert group_for_id("df_Zoan") is CategoryGroup.DEVIL_FRUIT
    assert group_for_id("haki_arm") is CategoryGroup.HAKI
    assert group_for_id("height_giant") is CategoryGroup.HEIGHT
    assert group_for_id("age_60_plus") is CategoryGroup.AGE
    assert group_for_id("debut_East Blue Saga") is CategoryGroup.DEBUT_CHAPTER
    assert group_for_id("visited_Water 7") is CategoryGroup.VISITED


def test_group_for_id_falls_back_to_misc_for_unmapped_prefixes() -> None:
    assert group_for_id("has_bounty") is CategoryGroup.MISC
    assert group_for_id("name_starts_with_A") is CategoryGroup.MISC
    assert group_for_id("rel_sibling") is CategoryGroup.MISC
    assert group_for_id("totally_unknown") is CategoryGroup.MISC
    assert group_for_id("noprefix") is CategoryGroup.MISC


# --- resolve_categories ------------------------------------------------


def _roster(*names: str) -> frozenset[str]:
    return frozenset(names)


def test_unresolved_names_are_dropped_and_listed_in_the_report() -> None:
    roster = _roster("Zoro", "Nami", "Usopp", "Sanji")
    raw = [
        {
            "id": "aff_Straw Hat Pirates",
            "label": "Affiliation: Straw Hat Pirates",
            "count": 6,
            "characters": ["Zoro", "Nami", "Ghost Guy", "Usopp", "Nobody", "Sanji"],
        }
    ]

    categories, report = resolve_categories(raw, roster)

    assert len(categories) == 1
    assert categories[0].characters == frozenset({"Zoro", "Nami", "Usopp", "Sanji"})
    assert report.unresolved == {"aff_Straw Hat Pirates": ("Ghost Guy", "Nobody")}
    assert report.excluded_categories == ()


def test_category_below_the_viable_threshold_is_excluded_from_play() -> None:
    roster = _roster("Zoro", "Nami")
    raw = [
        {
            "id": "aff_Tiny Crew",
            "label": "Affiliation: Tiny Crew",
            "count": 4,
            "characters": ["Zoro", "Nami", "Missing A", "Missing B"],
        }
    ]

    categories, report = resolve_categories(raw, roster)

    assert categories == ()
    assert report.excluded_categories == ("aff_Tiny Crew",)
    assert report.unresolved == {"aff_Tiny Crew": ("Missing A", "Missing B")}


def test_category_exactly_at_the_threshold_stays_playable() -> None:
    roster = _roster("A", "B", "C")
    raw = [
        {
            "id": "misc_trio",
            "label": "Misc: trio",
            "count": 3,
            "characters": ["A", "B", "C"],
        }
    ]

    categories, report = resolve_categories(raw, roster)

    assert VIABLE_THRESHOLD == 3
    assert len(categories) == 1
    assert report.excluded_categories == ()


def test_loaded_category_carries_its_group_label_and_source_count() -> None:
    roster = _roster("A", "B", "C")
    raw = [
        {
            "id": "df_Paramecia",
            "label": "Devil Fruit type: Paramecia",
            "count": 42,
            "characters": ["A", "B", "C"],
        }
    ]

    (loaded,), _ = resolve_categories(raw, roster)

    assert loaded.category.id == "df_Paramecia"
    assert loaded.category.label == "Devil Fruit type: Paramecia"
    assert loaded.category.group is CategoryGroup.DEVIL_FRUIT
    assert loaded.count == 42  # the count declared in categories.json, verbatim


def test_category_name_references_are_resolved_by_canonical_name() -> None:
    roster = _roster("Monkey D. Luffy", "Roronoa Zoro", "Nami")
    raw = [
        {
            "id": "aff_Straw Hat Pirates",
            "label": "Affiliation: Straw Hat Pirates",
            "count": 3,
            "characters": ["  Monkey   D. Luffy ", "Roronoa Zoro", "Nami"],
        }
    ]

    categories, report = resolve_categories(raw, roster)

    assert len(categories) == 1
    assert categories[0].characters == frozenset(roster)
    assert report.unresolved == {}


def test_report_aggregates_unresolved_names_across_categories() -> None:
    roster = _roster("A", "B", "C", "D")
    raw = [
        {
            "id": "race_One",
            "label": "Race: One",
            "count": 4,
            "characters": ["A", "B", "C", "Gone"],
        },
        {
            "id": "race_Two",
            "label": "Race: Two",
            "count": 4,
            "characters": ["A", "B", "D", "Vanished"],
        },
    ]

    _, report = resolve_categories(raw, roster)

    assert report.unresolved == {
        "race_One": ("Gone",),
        "race_Two": ("Vanished",),
    }
    assert report.unresolved_name_count == 2


# --- GameData.from_raw -------------------------------------------------


def test_game_data_from_raw_wires_roster_categories_and_report() -> None:
    characters = [{"name": "A"}, {"name": "B"}, {"name": "C"}, {"name": "D"}]
    categories = [
        {
            "id": "aff_Playable",
            "label": "Affiliation: Playable",
            "count": 4,
            "characters": ["A", "B", "C", "Missing"],
        },
        {
            "id": "aff_TooSmall",
            "label": "Affiliation: TooSmall",
            "count": 2,
            "characters": ["A", "D"],
        },
    ]

    data = GameData.from_raw(characters, categories)

    assert data.roster == {"A", "B", "C", "D"}
    assert data.roster_names == ["A", "B", "C", "D"]
    assert [c.category.id for c in data.categories] == ["aff_Playable"]
    assert data.report.unresolved == {"aff_Playable": ("Missing",)}
    assert data.report.excluded_categories == ("aff_TooSmall",)


# --- log_data_quality -------------------------------------------------


def test_log_data_quality_emits_the_report(
    caplog: pytest.LogCaptureFixture,
) -> None:
    characters = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
    categories = [
        {
            "id": "race_One",
            "label": "Race: One",
            "count": 4,
            "characters": ["A", "B", "C", "Gone"],
        },
        {
            "id": "aff_TooSmall",
            "label": "Affiliation: TooSmall",
            "count": 2,
            "characters": ["A", "Nope"],
        },
    ]
    data = GameData.from_raw(characters, categories)

    with caplog.at_level(logging.INFO, logger="app.dataset"):
        log_data_quality(data)

    messages = "\n".join(record.message for record in caplog.records)
    assert "Dataset loaded" in messages
    assert "aff_TooSmall" in messages  # excluded category
    assert "Gone" in messages  # unresolved name
