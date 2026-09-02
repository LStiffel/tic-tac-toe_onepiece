"""Seam 2 - the deterministic Category builder, no HTTP.

Covers the ADR 0004 contract as it has grown across the #19 slices: the
serialisers reproduce the committed ``categories.json`` / ``categories.txt``
byte-for-byte, and the builder reproduces from the Raw dataset the Status / Race
Categories (issue #24), the Devil Fruit / Visited Categories the
``devil_fruits.json`` and ``islands.json`` joins populate (issue #25), and the
Bounty / Debut chapter Categories whose predicates parse a number out of a Raw
field (issue #26). The membership fixtures build a tiny Roster by hand so the
assertions are exact (``docs/agents/testing.md``).
"""

from __future__ import annotations

import json

from app.domain import CategoryGroup
from scripts.build_categories import (
    CATEGORIES_JSON_PATH,
    CATEGORIES_TXT_PATH,
    CHARACTERS_PATH,
    DEVIL_FRUITS_PATH,
    ISLANDS_PATH,
    MIN_CHARACTERS,
    BuildResult,
    CategoryEntry,
    _merge_into_committed,
    build_categories,
    dump_categories_json,
    dump_categories_txt,
    read_json,
    to_txt_payload,
)

# ``read_text`` translates the checkout's line endings to ``\n``, so the
# comparison is against the canonical form the builder writes (see the
# serialisation note).
_COMMITTED_JSON_TEXT = CATEGORIES_JSON_PATH.read_text(encoding="utf-8")
_COMMITTED_TXT_TEXT = CATEGORIES_TXT_PATH.read_text(encoding="utf-8")
_COMMITTED_CATEGORIES: list[CategoryEntry] = json.loads(_COMMITTED_JSON_TEXT)


def _character(name: str, **fields: object) -> dict[str, object]:
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
    txt_payload = to_txt_payload(_COMMITTED_CATEGORIES)

    assert dump_categories_txt(txt_payload) == _COMMITTED_TXT_TEXT


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
        _COMMITTED_CATEGORIES, _build_from_repo_dataset().categories_json
    )

    assert dump_categories_json(merged) == _COMMITTED_JSON_TEXT


def test_rebuild_leaves_categories_txt_byte_for_byte_identical() -> None:
    merged = _merge_into_committed(
        to_txt_payload(_COMMITTED_CATEGORIES), _build_from_repo_dataset().categories_txt
    )

    assert dump_categories_txt(merged) == _COMMITTED_TXT_TEXT


def test_builder_reproduces_every_committed_status_and_race_category() -> None:
    built = {entry["id"]: entry for entry in _build_from_repo_dataset().categories_json}
    committed = _committed_status_and_race()

    assert set(committed) <= set(built)
    for category_id, committed_entry in committed.items():
        assert built[category_id] == committed_entry


def test_builder_reproduces_every_committed_devil_fruit_and_visited_category() -> None:
    built = {entry["id"]: entry for entry in _build_from_repo_dataset().categories_json}
    committed = {
        entry["id"]: entry
        for entry in _COMMITTED_CATEGORIES
        if entry["id"] == "has_df" or entry["id"].startswith(("df_", "visited_"))
    }

    assert committed, "the fixture must cover the join-backed Categories"
    assert set(committed) <= set(built)
    for category_id, committed_entry in committed.items():
        assert built[category_id] == committed_entry


def test_builder_reproduces_every_committed_bounty_and_debut_chapter_category() -> None:
    # Golden: the field-predicate slice (issue #26). Parsing a bounty figure and
    # a debut chapter out of the Raw dataset reproduces each ``bounty_*`` /
    # ``debut_*`` Category's Character list and count byte-for-byte.
    built = {entry["id"]: entry for entry in _build_from_repo_dataset().categories_json}
    committed = {
        entry["id"]: entry
        for entry in _COMMITTED_CATEGORIES
        if entry["id"].startswith(("bounty_", "debut_"))
    }

    assert committed, "the fixture must cover the Bounty and Debut chapter Categories"
    assert set(committed) <= set(built)
    for category_id, committed_entry in committed.items():
        assert built[category_id] == committed_entry


def test_txt_payload_carries_the_group_and_drops_the_character_list() -> None:
    by_id = {entry["id"]: entry for entry in _build_from_repo_dataset().categories_txt}

    assert by_id["status_Alive"] == {
        "id": "status_Alive",
        "label": "Status: Alive",
        "count": 1211,
        "group": CategoryGroup.STATUS,
    }
    assert by_id["race_Fish-man"]["group"] is CategoryGroup.RACE


def test_repo_build_report_lists_the_known_unjoinable_values() -> None:
    report = _build_from_repo_dataset().report

    # The one Upstream ``devil_fruit`` value with no ``devil_fruits.json`` row.
    assert "Jiki Jiki no Mi" in report.unjoinable_devil_fruits
    # Blackbeard's two fruits DO join (canonical name + case-folded), so the
    # multi-type value is not reported as unjoinable.
    assert " Gura Gura No Mi" not in report.unjoinable_devil_fruits
    # A journey location that names a real place with no island in
    # ``islands.json`` (Mary Geoise sits on the Red Line; the Baratie is a ship).
    assert "Mary Geoise" in report.unjoinable_journey_locations
    assert "Baratie" in report.unjoinable_journey_locations
    # Upstream's "Unknown island" sentinel is intentionally unplaced, not a
    # failed join, so it is kept out of the report.
    assert not any(
        location.startswith("Unknown island")
        for location in report.unjoinable_journey_locations
    )
    # Both lists are sorted and de-duplicated.
    assert list(report.unjoinable_devil_fruits) == sorted(set(report.unjoinable_devil_fruits))
    assert list(report.unjoinable_journey_locations) == sorted(
        set(report.unjoinable_journey_locations)
    )


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
    by_id = {entry["id"]: entry for entry in result.categories_json}

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
    by_id = {entry["id"]: entry for entry in result.categories_json}

    assert by_id["race_Human"]["characters"] == ["Luffy", "Nami", "Sanji", "Usopp"]
    assert by_id["race_Fish-man"]["characters"] == ["Arlong", "Hachi", "Jinbe"]
    assert by_id["race_Fish-man"]["count"] == 3
    # Two Giants is below MIN_CHARACTERS.
    assert MIN_CHARACTERS == 3
    assert "race_Giant" not in by_id


# --- Devil Fruit + island joins (issue #25) ---------------------------


def test_devil_fruit_join_matches_across_surrounding_whitespace() -> None:
    # The Raw ``devil_fruits.json`` names each carry a leading space; the
    # Character values here carry none, one, or a trailing space. ``canonical_name``
    # on both sides joins them all - the notebook's ``" " + name`` hack is gone.
    roster = [
        _character("Buggy", devil_fruit="Bara Bara no Mi "),
        _character("Alvida", devil_fruit=" Sube Sube no Mi"),
        _character("Mr. 5", devil_fruit="Bomu Bomu no Mi"),
    ]
    devil_fruits = [
        {"name": " Bara Bara no Mi", "type": "Paramecia"},
        {"name": " Sube Sube no Mi", "type": "Paramecia"},
        {"name": " Bomu Bomu no Mi", "type": "Paramecia"},
    ]

    result = build_categories(roster, devil_fruits, [])
    by_id = {entry["id"]: entry for entry in result.categories_json}

    assert by_id["df_Paramecia"]["characters"] == ["Alvida", "Buggy", "Mr. 5"]
    assert by_id["has_df"]["characters"] == ["Alvida", "Buggy", "Mr. 5"]
    assert result.report.unjoinable_devil_fruits == ()


def test_multi_type_devil_fruit_value_joins_to_each_devil_fruit_category() -> None:
    # Blackbeard's ``devil_fruit`` is a two-element list spanning two types; the
    # second value (``" Gura Gura No Mi"``) differs from the Raw fruit name by a
    # leading space and a capital - it still joins, and he lands in BOTH the
    # Logia and the Paramecia Category.
    roster = [
        _character("Blackbeard", devil_fruit=["Yami Yami no Mi", " Gura Gura No Mi"]),
        _character("Ace", devil_fruit="Mera Mera no Mi"),
        _character("Aokiji", devil_fruit="Hie Hie no Mi"),
        _character("Luffy", devil_fruit="Gomu Gomu no Mi"),
        _character("Robin", devil_fruit="Hana Hana no Mi"),
    ]
    devil_fruits = [
        {"name": " Yami Yami no Mi", "type": "Logia"},
        {"name": " Gura Gura no Mi", "type": "Paramecia"},
        {"name": " Mera Mera no Mi", "type": "Logia"},
        {"name": " Hie Hie no Mi", "type": "Logia"},
        {"name": " Gomu Gomu no Mi", "type": "Paramecia"},
        {"name": " Hana Hana no Mi", "type": "Paramecia"},
    ]

    result = build_categories(roster, devil_fruits, [])
    by_id = {entry["id"]: entry for entry in result.categories_json}

    assert "Blackbeard" in by_id["df_Logia"]["characters"]
    assert "Blackbeard" in by_id["df_Paramecia"]["characters"]
    assert result.report.unjoinable_devil_fruits == ()


def test_unjoinable_devil_fruit_is_reported_and_join_free_categories_kept() -> None:
    roster = [
        _character("John", devil_fruit="Jiki Jiki no Mi", status="Alive"),
        _character("Buggy", devil_fruit="Bara Bara no Mi", status="Alive"),
        _character("Alvida", devil_fruit="Sube Sube no Mi", status="Alive"),
        _character("Cabaji", devil_fruit="Bara Bara no Mi", status="Alive"),
    ]
    devil_fruits = [
        {"name": " Bara Bara no Mi", "type": "Paramecia"},
        {"name": " Sube Sube no Mi", "type": "Paramecia"},
    ]

    result = build_categories(roster, devil_fruits, [])
    by_id = {entry["id"]: entry for entry in result.categories_json}

    assert result.report.unjoinable_devil_fruits == ("Jiki Jiki no Mi",)
    # John keeps every Category that does not depend on the fruit-type join:
    # the Status Category (no join) and ``has_df`` (join-free - he has a value).
    assert "John" in by_id["status_Alive"]["characters"]
    assert "John" in by_id["has_df"]["characters"]
    # Only the join-dependent ``df_*`` Category cannot place him.
    assert "John" not in by_id["df_Paramecia"]["characters"]


def test_devil_fruit_subtype_categories_are_populated_from_the_join() -> None:
    roster = [
        _character("Kaido", devil_fruit="Uo Uo no Mi, Model: Seiryu"),
        _character("Marco", devil_fruit="Tori Tori no Mi, Model: Phoenix"),
        _character("Yamato", devil_fruit="Inu Inu no Mi, Model: Okuchi no Makami"),
    ]
    devil_fruits = [
        {"name": " Uo Uo no Mi, Model: Seiryu", "type": "Zoan", "subtype": "Mythical"},
        {"name": " Tori Tori no Mi, Model: Phoenix", "type": "Zoan", "subtype": "Mythical"},
        {
            "name": " Inu Inu no Mi, Model: Okuchi no Makami",
            "type": "Zoan",
            "subtype": "Mythical",
        },
    ]

    result = build_categories(roster, devil_fruits, [])
    by_id = {entry["id"]: entry for entry in result.categories_json}

    assert by_id["df_sub_Mythical"]["characters"] == ["Kaido", "Marco", "Yamato"]
    assert by_id["df_Zoan"]["characters"] == ["Kaido", "Marco", "Yamato"]


def test_hand_built_journey_yields_expected_visited_membership() -> None:
    roster = [
        _character(
            "Luffy",
            journey=[
                {"location": "Marineford"},
                {"location": "Dressrosa"},
                {"location": "Zou"},
            ],
        ),
        _character(
            "Law", journey=[{"location": "Dressrosa"}, {"location": "Zou"}]
        ),
        _character(
            "Kin'emon",
            journey=[
                {"location": "Dressrosa"},
                {"location": "Zou"},
                {"location": "Wano Country's Island"},
            ],
        ),
    ]
    islands = [
        {"name": name}
        for name in ("Marineford", "Dressrosa", "Zou", "Wano Country's Island")
    ]

    result = build_categories(roster, [], islands)
    by_id = {entry["id"]: entry for entry in result.categories_json}

    assert by_id["visited_Dressrosa"]["characters"] == ["Kin'emon", "Law", "Luffy"]
    assert by_id["visited_Zou"]["characters"] == ["Kin'emon", "Law", "Luffy"]
    # One visitor each - below the threshold, so not emitted.
    assert "visited_Marineford" not in by_id
    assert "visited_Wano Country's Island" not in by_id
    assert result.report.unjoinable_journey_locations == ()


def test_unresolved_journey_location_is_reported_and_other_categories_kept() -> None:
    # Every Character also visited Dressrosa; Judge's second step is a place with
    # no island. The unresolved step is reported, and it costs Judge nothing -
    # he keeps his Status Category and his ``visited_Dressrosa`` membership.
    dressrosa = {"location": "Dressrosa"}
    roster = [
        _character(
            "Judge",
            status="Alive",
            journey=[dressrosa, {"location": "Atlantis"}],
        ),
        _character("Nami", status="Alive", journey=[dressrosa]),
        _character("Zoro", status="Alive", journey=[dressrosa]),
    ]
    islands = [{"name": "Dressrosa", "notable_locations": []}]

    result = build_categories(roster, [], islands)
    by_id = {entry["id"]: entry for entry in result.categories_json}

    assert result.report.unjoinable_journey_locations == ("Atlantis",)
    assert "Judge" in by_id["status_Alive"]["characters"]
    assert by_id["visited_Dressrosa"]["characters"] == ["Judge", "Nami", "Zoro"]


def test_visited_join_matches_journey_location_regardless_of_case() -> None:
    # A journey location that differs from the Visited Category's location only
    # in case still lands the Character in the Category - the Visited join uses
    # the same case-folded key as every other join, so nothing is silently
    # dropped.
    roster = [
        _character("Luffy", journey=[{"location": "DRESSROSA"}]),
        _character("Law", journey=[{"location": "dressrosa"}]),
        _character("Kin'emon", journey=[{"location": "Dressrosa"}]),
    ]
    islands = [{"name": "Dressrosa"}]

    result = build_categories(roster, [], islands)
    by_id = {entry["id"]: entry for entry in result.categories_json}

    assert by_id["visited_Dressrosa"]["characters"] == ["Kin'emon", "Law", "Luffy"]
    assert result.report.unjoinable_journey_locations == ()


def test_unknown_island_sentinel_is_not_reported_as_unjoinable() -> None:
    roster = [
        _character("Roger", journey=[{"location": "Unknown island - met Rayleigh"}]),
        _character("Rayleigh", journey=[{"location": "Unknown island"}]),
    ]

    report = build_categories(roster, [], []).report

    assert report.unjoinable_journey_locations == ()


def test_builder_lists_raw_names_verbatim_sorted_and_not_de_duplicated() -> None:
    roster = [
        _character("Bjorn ", status="Alive"),
        _character("Bjorn", status="Alive"),
        _character("Aphelandra", status="Alive"),
    ]

    result = build_categories(roster, [], [])
    (alive,) = result.categories_json

    assert alive["id"] == "status_Alive"
    assert alive["characters"] == ["Aphelandra", "Bjorn", "Bjorn "]
    assert alive["count"] == 3


# --- Bounty + Debut chapter field predicates (issue #26) -------------


def test_bounty_predicate_parses_int_and_string_bounty_fields() -> None:
    # A representative Bounty predicate over a hand-built Roster. ``bounty`` is an
    # ``int`` for most Characters and a prose ``str`` for a few; the parse reads
    # the leading figure out of the string and drops the thousands commas, so
    # Buggy's "At least 3,189,000,000 [Cross Guild]" clears the 1,000,000,000
    # line. A Character with no ``bounty`` field is in no Bounty Category.
    roster = [
        _character("Luffy", bounty=3_000_000_000),
        _character("Zoro", bounty=1_111_000_000),
        _character("Sanji", bounty=1_032_000_000),
        _character("Buggy", bounty="At least 3,189,000,000 [Cross Guild]"),
        _character("Nami", bounty=66_000_000),
        _character("Usopp", bounty=30_000_000),
        _character("Chopper", bounty=1_000),
        _character("Vivi"),
    ]

    result = build_categories(roster, [], [])
    by_id = {entry["id"]: entry for entry in result.categories_json}

    # "Has a known bounty" is every Character with a parseable figure - the
    # no-bounty Vivi is excluded.
    assert by_id["bounty_1"]["characters"] == [
        "Buggy",
        "Chopper",
        "Luffy",
        "Nami",
        "Sanji",
        "Usopp",
        "Zoro",
    ]
    assert "Vivi" not in by_id["bounty_1"]["characters"]
    # Buggy's string bounty parses to 3,189,000,000, so he sits with the billions.
    assert by_id["bounty_1000000000"]["characters"] == ["Buggy", "Luffy", "Sanji", "Zoro"]
    # "has one, but below the line".
    assert by_id["bounty_under_100m"]["characters"] == ["Chopper", "Nami", "Usopp"]


def test_debut_chapter_predicate_parses_first_appearance_arc() -> None:
    # A representative Debut chapter predicate over a hand-built Roster. The
    # chapter is read from a value that opens with "Chapter <n>" (a trailing
    # note like "(cover)" or "(flashback)" is fine); a value with no chapter
    # reference ("Monsters") and a missing field both resolve to no debut
    # chapter, so those Characters fall out of every Debut chapter Category.
    roster = [
        _character("Luffy", first_appearance_arc="Chapter 1"),
        _character("Shanks", first_appearance_arc="Chapter 1"),
        _character("Coby", first_appearance_arc="Chapter 1"),
        _character("Zoro", first_appearance_arc="Chapter 3"),
        _character("Nami", first_appearance_arc="Chapter 8"),
        _character("Kid", first_appearance_arc="Chapter 98"),
        _character("Law", first_appearance_arc="Chapter 498 (cover)"),
        _character("Jinbe", first_appearance_arc="Chapter 528"),
        _character("Carrot", first_appearance_arc="Chapter 804"),
        _character("Yamato", first_appearance_arc="Chapter 984"),
        _character("Momonosuke", first_appearance_arc="Chapter 685 (flashback)"),
        _character("Ryuma", first_appearance_arc="Monsters"),
        _character("Imu"),
    ]

    result = build_categories(roster, [], [])
    by_id = {entry["id"]: entry for entry in result.categories_json}

    assert by_id["debut_ch1"]["characters"] == ["Coby", "Luffy", "Shanks"]
    assert by_id["debut_1_100"]["characters"] == [
        "Coby",
        "Kid",
        "Luffy",
        "Nami",
        "Shanks",
        "Zoro",
    ]
    assert by_id["debut_598_9999"]["characters"] == ["Carrot", "Momonosuke", "Yamato"]
    # No parseable chapter -> in no Debut chapter Category.
    for entry in result.categories_json:
        if entry["id"].startswith("debut_"):
            assert "Ryuma" not in entry["characters"]
            assert "Imu" not in entry["characters"]


def test_non_chapter_first_appearance_values_yield_no_debut_chapter() -> None:
    # Only a value that opens with "Chapter <n>" is a chapter debut. A value that
    # merely contains a number - an SBS Q&A volume, a spin-off novel or magazine
    # volume, a movie / special credit - is not, so the Character joins no Debut
    # chapter Category. Every Character here also has a real chapter debut, which
    # is the only thing that places them.
    roster = [
        _character("Roronoa Arashi", first_appearance_arc="SBS Volume 105 (mentioned)", status="Alive"),
        _character("Draw", first_appearance_arc="One Piece novel A - Vol. 1", status="Alive"),
        _character("Charlotte Gala", first_appearance_arc="One Piece Magazine Vol.5", status="Alive"),
        _character("Shiki", first_appearance_arc="Strong World: Chap. 0", status="Alive"),
        _character("Ryuma", first_appearance_arc="Monsters", status="Alive"),
    ]

    result = build_categories(roster, [], [])
    by_id = {entry["id"]: entry for entry in result.categories_json}

    # The Roster still loads (they keep every Category that does not need a
    # chapter)...
    assert by_id["status_Alive"]["count"] == 5
    # ...but no Debut chapter Category is emitted at all.
    assert not any(entry["id"].startswith("debut_") for entry in result.categories_json)


def test_new_field_predicate_groups_keep_the_build_order_deterministic() -> None:
    # With the Bounty and Debut chapter Groups now populated, the builder output
    # is still independent of Raw Character order and still sorted by descending
    # count.
    roster = [
        _character("Luffy", bounty=3_000_000_000, first_appearance_arc="Chapter 1"),
        _character("Zoro", bounty=1_111_000_000, first_appearance_arc="Chapter 3"),
        _character("Sanji", bounty=1_032_000_000, first_appearance_arc="Chapter 43"),
        _character("Jinbe", bounty=1_100_000_000, first_appearance_arc="Chapter 528"),
    ]

    forward = build_categories(roster, [], [])
    reverse = build_categories(list(reversed(roster)), [], [])

    assert forward.categories_json == reverse.categories_json
    assert forward.categories_txt == reverse.categories_txt
    assert dump_categories_json(forward.categories_json) == dump_categories_json(
        reverse.categories_json
    )
    # Serialised, the entries are ordered by descending count then id ascending.
    serialised = json.loads(dump_categories_json(forward.categories_json))
    keys = [(-entry["count"], entry["id"]) for entry in serialised]
    assert keys == sorted(keys)
    # Both new Groups landed rows in the output.
    groups = {entry["group"] for entry in forward.categories_txt}
    assert CategoryGroup.BOUNTY in groups
    assert CategoryGroup.DEBUT_CHAPTER in groups


# --- determinism ------------------------------------------------------


def test_build_is_deterministic_across_repeated_runs() -> None:
    first = _build_from_repo_dataset()
    second = _build_from_repo_dataset()

    assert first.categories_json == second.categories_json
    assert first.categories_txt == second.categories_txt
    assert dump_categories_json(first.categories_json) == dump_categories_json(
        second.categories_json
    )


def test_build_output_order_is_independent_of_raw_character_order() -> None:
    roster = [
        _character("Zoro", race="Human"),
        _character("Luffy", race="Human"),
        _character("Nami", race="Human"),
    ]

    forward = build_categories(roster, [], [])
    reverse = build_categories(list(reversed(roster)), [], [])

    assert forward.categories_json == reverse.categories_json
    (human,) = forward.categories_json
    assert human["characters"] == ["Luffy", "Nami", "Zoro"]
