"""Seam 2 - the deterministic Category builder, no HTTP.

Covers the ADR 0004 / issue #24 contract: the serialisers reproduce the
committed ``categories.json`` / ``categories.txt`` byte-for-byte, and the
builder reproduces the Status and Race Categories from the Raw dataset. The
membership fixtures build a tiny Roster by hand so the assertions are exact
(``docs/agents/testing.md``).
"""

from __future__ import annotations

import json

from scripts.build_categories import (
    CATEGORIES_JSON_PATH,
    CATEGORIES_TXT_PATH,
    CHARACTERS_PATH,
    DEVIL_FRUITS_PATH,
    ISLANDS_PATH,
    MIN_CHARACTERS,
    BuildReport,
    BuildResult,
    CategoryEntry,
    _merge_into_committed,
    build_categories,
    dump_categories_json,
    dump_categories_txt,
    read_json,
)

# ``read_text`` translates the checkout's line endings to ``\n``, so the
# comparison is against the canonical form the builder writes (see the
# serialisation note).
_COMMITTED_JSON_TEXT = CATEGORIES_JSON_PATH.read_text(encoding="utf-8")
_COMMITTED_TXT_TEXT = CATEGORIES_TXT_PATH.read_text(encoding="utf-8")
_COMMITTED_CATEGORIES: list[CategoryEntry] = json.loads(_COMMITTED_JSON_TEXT)


def _character(name: str, **fields: str) -> dict[str, str]:
    return {"name": name, **fields}


def _build_from_repo_dataset() -> BuildResult:
    return build_categories(
        read_json(CHARACTERS_PATH), read_json(DEVIL_FRUITS_PATH), read_json(ISLANDS_PATH)
    )


def _committed_status_and_race() -> dict[str, CategoryEntry]:
    return {
        entry["id"]: entry
        for entry in _COMMITTED_CATEGORIES
        if entry["id"].startswith(("status_", "race_"))
    }


# --- serialisation round-trips --------------------------------------------


def test_dump_categories_json_reproduces_the_committed_file_byte_for_byte() -> None:
    assert dump_categories_json(_COMMITTED_CATEGORIES) == _COMMITTED_JSON_TEXT


def test_dump_categories_txt_reproduces_the_committed_file_byte_for_byte() -> None:
    assert dump_categories_txt(_COMMITTED_CATEGORIES) == _COMMITTED_TXT_TEXT


def test_dump_categories_json_is_independent_of_input_order() -> None:
    shuffled = list(reversed(_COMMITTED_CATEGORIES))

    assert dump_categories_json(shuffled) == _COMMITTED_JSON_TEXT


def test_dump_categories_json_sorts_each_characters_list() -> None:
    payload: list[CategoryEntry] = [
        {
            "id": "race_Human",
            "label": "Race: Human",
            "count": 3,
            "characters": ["Zoro", "Nami", "Luffy"],
        }
    ]

    dumped = json.loads(dump_categories_json(payload))

    assert dumped[0]["characters"] == ["Luffy", "Nami", "Zoro"]


# --- golden: the builder reproduces the committed files -----------------
#
# Merged with the committed payload (as ``python -m scripts.build_categories``
# does), a rebuild of the Status / Race Categories from the current Raw dataset
# leaves both committed files byte-for-byte unchanged.


def test_rebuild_leaves_categories_json_byte_for_byte_identical() -> None:
    merged = _merge_into_committed(
        _COMMITTED_CATEGORIES, _build_from_repo_dataset().categories
    )

    assert dump_categories_json(merged) == _COMMITTED_JSON_TEXT


def test_rebuild_leaves_categories_txt_byte_for_byte_identical() -> None:
    merged = _merge_into_committed(
        _COMMITTED_CATEGORIES, _build_from_repo_dataset().categories
    )

    assert dump_categories_txt(merged) == _COMMITTED_TXT_TEXT


def test_builder_reproduces_every_committed_status_and_race_category() -> None:
    built = {entry["id"]: entry for entry in _build_from_repo_dataset().categories}
    committed = _committed_status_and_race()

    assert set(built) == set(committed)
    for category_id, committed_entry in committed.items():
        assert built[category_id] == committed_entry


def test_builder_reports_nothing_unjoinable_in_this_slice() -> None:
    report = _build_from_repo_dataset().report

    assert report == BuildReport()
    assert report.unjoinable_devil_fruits == ()
    assert report.unjoinable_journey_locations == ()


# --- membership fixtures ------------------------------------------------


def test_status_predicate_is_plain_equality_on_the_status_field() -> None:
    roster = [
        _character("Zoro", status="Alive"),
        _character("Nami", status="Alive"),
        _character("Luffy", status="Alive"),
        _character("Pedro", status="Deceased"),
        _character("Oden", status="Deceased"),
        _character("Yorki", status="Deceased"),
        _character("Shanks", status="Unknown"),
    ]

    result = build_categories(roster, [], [])
    by_id = {entry["id"]: entry for entry in result.categories}

    assert by_id["status_Alive"]["characters"] == ["Luffy", "Nami", "Zoro"]
    assert by_id["status_Alive"]["count"] == 3
    assert by_id["status_Deceased"]["characters"] == ["Oden", "Pedro", "Yorki"]
    # A single "Unknown" Character - below the threshold - is not emitted.
    assert "status_Unknown" not in by_id


def test_race_predicate_is_plain_equality_on_the_race_field() -> None:
    roster = [
        _character("Arlong", race="Fish-man"),
        _character("Hachi", race="Fish-man"),
        _character("Jinbe", race="Fish-man"),
        _character("Luffy", race="Human"),
        _character("Nami", race="Human"),
        _character("Usopp", race="Human"),
        _character("Sanji", race="Human"),
        _character("Oimo", race="Giant"),
        _character("Kashii", race="Giant"),
    ]

    result = build_categories(roster, [], [])
    by_id = {entry["id"]: entry for entry in result.categories}

    assert by_id["race_Human"]["characters"] == ["Luffy", "Nami", "Sanji", "Usopp"]
    assert by_id["race_Fish-man"]["characters"] == ["Arlong", "Hachi", "Jinbe"]
    assert by_id["race_Fish-man"]["count"] == 3
    # Two Giants is below MIN_CHARACTERS.
    assert MIN_CHARACTERS == 3
    assert "race_Giant" not in by_id


def test_builder_lists_raw_names_verbatim_sorted_and_not_de_duplicated() -> None:
    roster = [
        _character("Bjorn ", status="Alive"),
        _character("Bjorn", status="Alive"),
        _character("Aphelandra", status="Alive"),
    ]

    result = build_categories(roster, [], [])
    (alive,) = result.categories

    assert alive["id"] == "status_Alive"
    assert alive["characters"] == ["Aphelandra", "Bjorn", "Bjorn "]
    assert alive["count"] == 3


# --- determinism ------------------------------------------------------


def test_build_is_deterministic_across_repeated_runs() -> None:
    first = _build_from_repo_dataset()
    second = _build_from_repo_dataset()

    assert first.categories == second.categories
    assert dump_categories_json(first.categories) == dump_categories_json(
        second.categories
    )


def test_build_output_order_is_independent_of_raw_character_order() -> None:
    roster = [
        _character("Zoro", race="Human"),
        _character("Luffy", race="Human"),
        _character("Nami", race="Human"),
    ]

    forward = build_categories(roster, [], [])
    reverse = build_categories(list(reversed(roster)), [], [])

    assert forward.categories == reverse.categories
    (human,) = forward.categories
    assert human["characters"] == ["Luffy", "Nami", "Zoro"]
