"""Deterministic builder for the derived Category files (ADR 0004).

The **Raw dataset** — ``characters.json``, ``devil_fruits.json``,
``islands.json`` — is vendored verbatim. The files the game plays from,
``categories.json`` (195 **Categories** with their resolved **Character** lists)
and ``categories.txt`` (the human-readable listing), are *derived* and must be
reproducible from the Raw dataset alone.

This module holds:

* :data:`CATEGORY_SPECS` — the ~195 Category predicates and their **Category
  Group** assignment, reverse-engineered from the currently committed
  ``categories.json`` + ``categories.txt``. Each row carries an ``id``, a
  ``label``, a :class:`~app.domain.CategoryGroup`, and a *predicate* over a Raw
  Character. **Only the Status and Race rows carry a predicate in this slice**
  (issue #24 / #19a); every other row's predicate is ``None`` until the join
  (#19b) and field-parsing (#19c) slices land. A Status / Race predicate is a
  plain equality on the Character's ``status`` / ``race`` field — no join, no
  parsing.
* :func:`build_categories` — a pure, deterministic function from the three Raw
  structures to a :class:`BuildResult`: the ``categories.json`` payload, the
  ``categories.txt`` payload, and a :class:`BuildReport`, each covering the rows
  it can build.
* :func:`dump_categories_json` / :func:`dump_categories_txt` — serialisers that
  reproduce the committed files byte-for-byte from those payloads. The exact
  normalisation is recorded in ``docs/measurements/categories-serialisation.md``.
  :func:`to_txt_payload` turns a ``categories.json`` payload into a
  ``categories.txt`` one by attaching each Category's Group.

Run ``python -m scripts.build_categories`` to rebuild both files in place: the
Status / Race Categories are rebuilt from the Raw dataset, every other Category
is carried over from the committed ``categories.json`` unchanged (the builder is
not yet the source of the whole file), and both files are re-serialised through
the helpers above.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict, TypeVar

from app.domain import CategoryGroup

# Repo root: this file is ``<root>/scripts/build_categories.py``.
REPO_ROOT = Path(__file__).resolve().parent.parent
CHARACTERS_PATH = REPO_ROOT / "characters.json"
DEVIL_FRUITS_PATH = REPO_ROOT / "devil_fruits.json"
ISLANDS_PATH = REPO_ROOT / "islands.json"
CATEGORIES_JSON_PATH = REPO_ROOT / "categories.json"
CATEGORIES_TXT_PATH = REPO_ROOT / "categories.txt"

#: A Category is emitted only when at least this many Characters match it
#: ("Categories matched by at least 3 characters" — the ``categories.txt``
#: header). This is the builder's emission floor; it is distinct from
#: ``app.dataset.VIABLE_THRESHOLD`` (the load-time Viable threshold), which
#: happens to share the value 3.
MIN_CHARACTERS = 3

#: ``categories.txt`` layout constants (see the serialisation note): the group
#: rule is 70 ``=``, and the count column is as wide as the file's largest count
#: plus this minimum gap.
_RULE_WIDTH = 70
_COUNT_GAP = 2

#: A parsed Raw ``characters.json`` entry. Its fields are Upstream's and
#: deliberately untyped here.
RawCharacter = Mapping[str, Any]

#: A predicate over a Raw Character: ``True`` iff the Character is in the Category.
Predicate = Callable[[RawCharacter], bool]


class _CategoryHeader(TypedDict):
    """The fields both derived files share for a Category: enough to order it
    (:func:`_sort_key` uses ``count`` then ``id``) and to label it."""

    id: str
    label: str
    count: int


class CategoryEntry(_CategoryHeader):
    """One ``categories.json`` array element: a Category paired with its
    resolved Character list. ``count`` always equals ``len(characters)``."""

    characters: list[str]


class TxtCategory(_CategoryHeader):
    """One ``categories.txt`` line's data: a Category's **Category Group**,
    label and size. No Character list — the txt file shows only counts."""

    group: CategoryGroup


#: Bound to a concrete ``_CategoryHeader`` subclass so :func:`_merge_into_committed`
#: keeps the payload shape it is handed.
_Header = TypeVar("_Header", bound=_CategoryHeader)


def _match_field(field_name: str, value: str) -> Predicate:
    """A predicate that is true when the Character's ``field_name`` equals
    ``value`` exactly (the Status / Race shape: no join, no parsing)."""

    def predicate(character: RawCharacter) -> bool:
        return character.get(field_name) == value

    return predicate


@dataclass(frozen=True)
class CategorySpec:
    """One row of the reverse-engineered predicate table.

    ``predicate`` is ``None`` for Category Groups whose membership needs a join
    or field parsing that a later slice adds; those rows still pin the ``id`` →
    ``label`` / :class:`~app.domain.CategoryGroup` mapping used by
    :func:`dump_categories_txt`.
    """

    id: str
    label: str
    group: CategoryGroup
    predicate: Predicate | None


# The table below is ordered by Category Group (``CONTEXT.md`` / ``categories.txt``
# order), then by descending Category size — the same order ``categories.txt``
# prints. ``has_df`` sits under Devil Fruit even though its ``id`` prefix is
# ``has``: that is how ``categories.txt`` groups it, and this table reproduces
# that file.
CATEGORY_SPECS: tuple[CategorySpec, ...] = (
    # Bounty
    CategorySpec("bounty_1", "Has a known bounty", CategoryGroup.BOUNTY, None),
    CategorySpec("bounty_100000000", "Bounty ≥ 100,000,000", CategoryGroup.BOUNTY, None),
    CategorySpec("bounty_under_100m", "Bounty below 100,000,000 (but has one)", CategoryGroup.BOUNTY, None),
    CategorySpec("bounty_500000000", "Bounty ≥ 500,000,000", CategoryGroup.BOUNTY, None),
    CategorySpec("bounty_1000000000", "Bounty ≥ 1,000,000,000", CategoryGroup.BOUNTY, None),
    CategorySpec("bounty_1500000000", "Bounty ≥ 1,500,000,000", CategoryGroup.BOUNTY, None),
    CategorySpec("bounty_3000000000", "Bounty ≥ 3,000,000,000", CategoryGroup.BOUNTY, None),
    # Race
    CategorySpec("race_Human", "Race: Human", CategoryGroup.RACE, _match_field("race", "Human")),
    CategorySpec("race_Animal", "Race: Animal", CategoryGroup.RACE, _match_field("race", "Animal")),
    CategorySpec("race_Giant", "Race: Giant", CategoryGroup.RACE, _match_field("race", "Giant")),
    CategorySpec("race_Fish-man", "Race: Fish-man", CategoryGroup.RACE, _match_field("race", "Fish-man")),
    CategorySpec("race_Merfolk", "Race: Merfolk", CategoryGroup.RACE, _match_field("race", "Merfolk")),
    CategorySpec("race_Mink", "Race: Mink", CategoryGroup.RACE, _match_field("race", "Mink")),
    CategorySpec("race_Dwarf", "Race: Dwarf", CategoryGroup.RACE, _match_field("race", "Dwarf")),
    CategorySpec("race_Devil Fruit creation", "Race: Devil Fruit creation", CategoryGroup.RACE, _match_field("race", "Devil Fruit creation")),
    CategorySpec("race_Moon people - Shandian", "Race: Moon people - Shandian", CategoryGroup.RACE, _match_field("race", "Moon people - Shandian")),
    CategorySpec("race_Object", "Race: Object", CategoryGroup.RACE, _match_field("race", "Object")),
    CategorySpec("race_Robot", "Race: Robot", CategoryGroup.RACE, _match_field("race", "Robot")),
    CategorySpec("race_Artificial Giant", "Race: Artificial Giant", CategoryGroup.RACE, _match_field("race", "Artificial Giant")),
    CategorySpec("race_Moon people - Birkan", "Race: Moon people - Birkan", CategoryGroup.RACE, _match_field("race", "Moon people - Birkan")),
    CategorySpec("race_Moon people - Skypiean", "Race: Moon people - Skypiean", CategoryGroup.RACE, _match_field("race", "Moon people - Skypiean")),
    CategorySpec("race_Human-Snakeneck hybrid", "Race: Human-Snakeneck hybrid", CategoryGroup.RACE, _match_field("race", "Human-Snakeneck hybrid")),
    CategorySpec("race_Longarm", "Race: Longarm", CategoryGroup.RACE, _match_field("race", "Longarm")),
    CategorySpec("race_Human-Longarm hybrid", "Race: Human-Longarm hybrid", CategoryGroup.RACE, _match_field("race", "Human-Longarm hybrid")),
    CategorySpec("race_Human-Fish-man hybrid", "Race: Human-Fish-man hybrid", CategoryGroup.RACE, _match_field("race", "Human-Fish-man hybrid")),
    CategorySpec("race_Human-Longleg hybrid", "Race: Human-Longleg hybrid", CategoryGroup.RACE, _match_field("race", "Human-Longleg hybrid")),
    CategorySpec("race_Merfolk-Human hybrid", "Race: Merfolk-Human hybrid", CategoryGroup.RACE, _match_field("race", "Merfolk-Human hybrid")),
    # Status
    CategorySpec("status_Alive", "Status: Alive", CategoryGroup.STATUS, _match_field("status", "Alive")),
    CategorySpec("status_Unknown", "Status: Unknown", CategoryGroup.STATUS, _match_field("status", "Unknown")),
    CategorySpec("status_Deceased", "Status: Deceased", CategoryGroup.STATUS, _match_field("status", "Deceased")),
    # Affiliation
    CategorySpec("aff_Big Mom Pirates", "Affiliation: Big Mom Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Marines", "Affiliation: Marines", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Beasts Pirates", "Affiliation: Beasts Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Whitebeard Pirates", "Affiliation: Whitebeard Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Kouzuki Family", "Affiliation: Kouzuki Family", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Thriller Bark Pirates", "Affiliation: Thriller Bark Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Roger Pirates", "Affiliation: Roger Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Kuja", "Affiliation: Kuja", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Arabasta Kingdom", "Affiliation: Arabasta Kingdom", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Kid Pirates", "Affiliation: Kid Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Tontatta Kingdom", "Affiliation: Tontatta Kingdom", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Revolutionary Army", "Affiliation: Revolutionary Army", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Spade Pirates", "Affiliation: Spade Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Mokomo Dukedom", "Affiliation: Mokomo Dukedom", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_World Government", "Affiliation: World Government", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Baroque Works", "Affiliation: Baroque Works", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Blackbeard Pirates", "Affiliation: Blackbeard Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Donquixote Pirates", "Affiliation: Donquixote Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Walrus School", "Affiliation: Walrus School", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Foxy Pirates", "Affiliation: Foxy Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_CP0", "Affiliation: CP0", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Impel Down", "Affiliation: Impel Down", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Shandia", "Affiliation: Shandia", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Giant Warrior Pirates", "Affiliation: Giant Warrior Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Red Hair Pirates", "Affiliation: Red Hair Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Ryugu Kingdom", "Affiliation: Ryugu Kingdom", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Kurozumi Family", "Affiliation: Kurozumi Family", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Mermaid Café", "Affiliation: Mermaid Café", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Straw Hat Pirates", "Affiliation: Straw Hat Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Beasts Pirates (Numbers)", "Affiliation: Beasts Pirates (Numbers)", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Caesar Clown", "Affiliation: Caesar Clown", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Fake Straw Hat Crew", "Affiliation: Fake Straw Hat Crew", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Cross Guild", "Affiliation: Cross Guild", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Franky Family", "Affiliation: Franky Family", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Germa Kingdom", "Affiliation: Germa Kingdom", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Heart Pirates", "Affiliation: Heart Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_New Fish-Man Pirates", "Affiliation: New Fish-Man Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Ohara Archaeologists", "Affiliation: Ohara Archaeologists", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Shimotsuki Family", "Affiliation: Shimotsuki Family", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Arlong Pirates", "Affiliation: Arlong Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Bellamy Pirates", "Affiliation: Bellamy Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_God's Army", "Affiliation: God's Army", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_New Spiders Cafe", "Affiliation: New Spiders Cafe", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Beasts Pirates (Armored Division)", "Affiliation: Beasts Pirates (Armored Division)", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Five Elders", "Affiliation: Five Elders", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Knights of God", "Affiliation: Knights of God", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Krieg Pirates", "Affiliation: Krieg Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Marines (SSG)", "Affiliation: Marines (SSG)", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_New Giant Warrior Pirates", "Affiliation: New Giant Warrior Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Poseidon", "Affiliation: Poseidon", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Rocks Pirates", "Affiliation: Rocks Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Underworld", "Affiliation: Underworld", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Automata", "Affiliation: Automata", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Baroque Works (Millions)", "Affiliation: Baroque Works (Millions)", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Bonney Pirates", "Affiliation: Bonney Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Charlotte Family", "Affiliation: Charlotte Family", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Dressrosa Kingdom", "Affiliation: Dressrosa Kingdom", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Fire Tank Pirates", "Affiliation: Fire Tank Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Galley-La Company", "Affiliation: Galley-La Company", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Germ Pirates", "Affiliation: Germ Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Goa Kingdom", "Affiliation: Goa Kingdom", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Marines (SWORD)", "Affiliation: Marines (SWORD)", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Roshwan Kingdom", "Affiliation: Roshwan Kingdom", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Ukkari Hot-Spring Island", "Affiliation: Ukkari Hot-Spring Island", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Black Cat Pirates", "Affiliation: Black Cat Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_CP9", "Affiliation: CP9", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Drum Kingdom", "Affiliation: Drum Kingdom", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_God's Guards", "Affiliation: God's Guards", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Ideo Pirates", "Affiliation: Ideo Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Island of Rare Animals", "Affiliation: Island of Rare Animals", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Newkama Land", "Affiliation: Newkama Land", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Rebel Army", "Affiliation: Rebel Army", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Sun Pirates", "Affiliation: Sun Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Vegapunk", "Affiliation: Vegapunk", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Warland Kingdom", "Affiliation: Warland Kingdom", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Alvida Pirates (disbanded)", "Affiliation: Alvida Pirates (disbanded)", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Baratie", "Affiliation: Baratie", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Baroque Works (Billions)", "Affiliation: Baroque Works (Billions)", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Beasts Pirates (Tobiroppo)", "Affiliation: Beasts Pirates (Tobiroppo)", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Beautiful Pirates", "Affiliation: Beautiful Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Dadan Family", "Affiliation: Dadan Family", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Endurance Curry Pirates", "Affiliation: Endurance Curry Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Galley-La Company (Zambai's Company Union)", "Affiliation: Galley-La Company (Zambai's Company Union)", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Happo Navy", "Affiliation: Happo Navy", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Kyoshiro Family", "Affiliation: Kyoshiro Family", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Lvneel Kingdom", "Affiliation: Lvneel Kingdom", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Macro Pirates", "Affiliation: Macro Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Rumbar Pirates", "Affiliation: Rumbar Pirates", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Tom's Workers", "Affiliation: Tom's Workers", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Usopp Pirates (disbanded)", "Affiliation: Usopp Pirates (disbanded)", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Wagomuland", "Affiliation: Wagomuland", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_World Economy News Paper", "Affiliation: World Economy News Paper", CategoryGroup.AFFILIATION, None),
    CategorySpec("aff_Yes Pirates", "Affiliation: Yes Pirates", CategoryGroup.AFFILIATION, None),
    # Origin sea
    CategorySpec("origin_Grand Line", "Origin: Grand Line", CategoryGroup.ORIGIN_SEA, None),
    CategorySpec("origin_East Blue", "Origin: East Blue", CategoryGroup.ORIGIN_SEA, None),
    CategorySpec("origin_North Blue", "Origin: North Blue", CategoryGroup.ORIGIN_SEA, None),
    CategorySpec("origin_West Blue", "Origin: West Blue", CategoryGroup.ORIGIN_SEA, None),
    CategorySpec("origin_South Blue", "Origin: South Blue", CategoryGroup.ORIGIN_SEA, None),
    CategorySpec("origin_Calm Belt", "Origin: Calm Belt", CategoryGroup.ORIGIN_SEA, None),
    CategorySpec("origin_Sky Islands", "Origin: Sky Islands", CategoryGroup.ORIGIN_SEA, None),
    CategorySpec("origin_Red Line", "Origin: Red Line", CategoryGroup.ORIGIN_SEA, None),
    # Devil Fruit
    CategorySpec("has_df", "Has a Devil Fruit", CategoryGroup.DEVIL_FRUIT, None),
    CategorySpec("df_Zoan", "Devil Fruit type: Zoan", CategoryGroup.DEVIL_FRUIT, None),
    CategorySpec("df_Paramecia", "Devil Fruit type: Paramecia", CategoryGroup.DEVIL_FRUIT, None),
    CategorySpec("df_sub_Artificial", "Devil Fruit subtype: Artificial Zoan", CategoryGroup.DEVIL_FRUIT, None),
    CategorySpec("df_sub_Mythical", "Devil Fruit subtype: Mythical Zoan", CategoryGroup.DEVIL_FRUIT, None),
    CategorySpec("df_Logia", "Devil Fruit type: Logia", CategoryGroup.DEVIL_FRUIT, None),
    CategorySpec("df_sub_Ancient", "Devil Fruit subtype: Ancient Zoan", CategoryGroup.DEVIL_FRUIT, None),
    # Haki
    CategorySpec("haki_any", "Can use Haki", CategoryGroup.HAKI, None),
    CategorySpec("haki_arm", "Can use Armament Haki", CategoryGroup.HAKI, None),
    CategorySpec("haki_obs", "Can use Observation Haki", CategoryGroup.HAKI, None),
    CategorySpec("haki_conq", "Can use Conqueror's Haki", CategoryGroup.HAKI, None),
    CategorySpec("haki_all3", "Can use all three types of Haki", CategoryGroup.HAKI, None),
    # Height
    CategorySpec("height_150_200", "Height between 150 and 200 cm", CategoryGroup.HEIGHT, None),
    CategorySpec("height_giant", "Height over 500 cm", CategoryGroup.HEIGHT, None),
    CategorySpec("height_over_1000", "Height over 1,000 cm", CategoryGroup.HEIGHT, None),
    CategorySpec("height_under_100", "Height under 100 cm", CategoryGroup.HEIGHT, None),
    # Age
    CategorySpec("age_known", "Has a known age", CategoryGroup.AGE, None),
    CategorySpec("age_60_plus", "Age 60 or older", CategoryGroup.AGE, None),
    CategorySpec("age_under_18", "Age under 18", CategoryGroup.AGE, None),
    CategorySpec("age_over_100", "Age over 100", CategoryGroup.AGE, None),
    # Debut chapter
    CategorySpec("debut_598_9999", "Debuted after the timeskip (ch. ≥ 598)", CategoryGroup.DEBUT_CHAPTER, None),
    CategorySpec("debut_1_597", "Debuted before the timeskip (ch. ≤ 597)", CategoryGroup.DEBUT_CHAPTER, None),
    CategorySpec("debut_900_9999", "Debut chapter ≥ 900", CategoryGroup.DEBUT_CHAPTER, None),
    CategorySpec("debut_1_300", "Debut chapter 1–300", CategoryGroup.DEBUT_CHAPTER, None),
    CategorySpec("debut_1_100", "Debut chapter 1–100", CategoryGroup.DEBUT_CHAPTER, None),
    CategorySpec("debut_1000_9999", "Debut chapter ≥ 1000", CategoryGroup.DEBUT_CHAPTER, None),
    CategorySpec("debut_ch1", "Debuted in Chapter 1", CategoryGroup.DEBUT_CHAPTER, None),
    # Visited (journey)
    CategorySpec("visited_Wano Country's Island", "Visited Wano Country's Island", CategoryGroup.VISITED, None),
    CategorySpec("visited_Marineford", "Visited Marineford", CategoryGroup.VISITED, None),
    CategorySpec("visited_Totto Land", "Visited Totto Land", CategoryGroup.VISITED, None),
    CategorySpec("visited_Dressrosa", "Visited Dressrosa", CategoryGroup.VISITED, None),
    CategorySpec("visited_Mary Geoise", "Visited Mary Geoise", CategoryGroup.VISITED, None),
    CategorySpec("visited_Sabaody Archipelago", "Visited Sabaody Archipelago", CategoryGroup.VISITED, None),
    CategorySpec("visited_Fish-Man Island", "Visited Fish-Man Island", CategoryGroup.VISITED, None),
    CategorySpec("visited_Elbaph Island", "Visited Elbaph Island", CategoryGroup.VISITED, None),
    CategorySpec("visited_Water 7", "Visited Water 7", CategoryGroup.VISITED, None),
    CategorySpec("visited_Zou", "Visited Zou", CategoryGroup.VISITED, None),
    CategorySpec("visited_Sandy Island", "Visited Sandy Island", CategoryGroup.VISITED, None),
    CategorySpec("visited_Skypiea", "Visited Skypiea", CategoryGroup.VISITED, None),
    CategorySpec("visited_Impel Down", "Visited Impel Down", CategoryGroup.VISITED, None),
    CategorySpec("visited_Punk Hazard", "Visited Punk Hazard", CategoryGroup.VISITED, None),
    CategorySpec("visited_Hachinosu", "Visited Hachinosu", CategoryGroup.VISITED, None),
    CategorySpec("visited_Egghead", "Visited Egghead", CategoryGroup.VISITED, None),
    CategorySpec("visited_God Valley", "Visited God Valley", CategoryGroup.VISITED, None),
    CategorySpec("visited_Enies Lobby", "Visited Enies Lobby", CategoryGroup.VISITED, None),
    CategorySpec("visited_Jaya", "Visited Jaya", CategoryGroup.VISITED, None),
    CategorySpec("visited_Island of Women", "Visited Island of Women", CategoryGroup.VISITED, None),
    CategorySpec("visited_Thriller Bark", "Visited Thriller Bark", CategoryGroup.VISITED, None),
    CategorySpec("visited_Dawn Island", "Visited Dawn Island", CategoryGroup.VISITED, None),
    CategorySpec("visited_Little Garden", "Visited Little Garden", CategoryGroup.VISITED, None),
    CategorySpec("visited_Baratie", "Visited Baratie", CategoryGroup.VISITED, None),
    CategorySpec("visited_Drum Island", "Visited Drum Island", CategoryGroup.VISITED, None),
    CategorySpec("visited_Ohara", "Visited Ohara", CategoryGroup.VISITED, None),
    CategorySpec("visited_Baltigo", "Visited Baltigo", CategoryGroup.VISITED, None),
    CategorySpec("visited_Laugh Tale", "Visited Laugh Tale", CategoryGroup.VISITED, None),
    # Misc
    CategorySpec("rel_5plus", "Has 5 or more listed relationships", CategoryGroup.MISC, None),
    CategorySpec("has_epithet", "Has an epithet", CategoryGroup.MISC, None),
    CategorySpec("rel_10plus", "Has 10 or more listed relationships", CategoryGroup.MISC, None),
    CategorySpec("has_image_pre", "Has a transformation / alternate form image", CategoryGroup.MISC, None),
    CategorySpec("name_charlotte", "Member of the Charlotte family (by name)", CategoryGroup.MISC, None),
    CategorySpec("name_has_D", 'Carries the "D." in their name', CategoryGroup.MISC, None),
    CategorySpec("name_vinsmoke", "Vinsmoke family (by name)", CategoryGroup.MISC, None),
    CategorySpec("name_kouzuki", "Kouzuki family (by name)", CategoryGroup.MISC, None),
    CategorySpec("name_boa", "Boa family (by name)", CategoryGroup.MISC, None),
)

#: ``id`` → **Category Group**, from :data:`CATEGORY_SPECS`. Used by
#: :func:`to_txt_payload` to tag a ``categories.json`` entry with its Group.
_GROUP_BY_ID: dict[str, CategoryGroup] = {spec.id: spec.group for spec in CATEGORY_SPECS}

#: The ``id``s this builder owns — the rows with a predicate. A rebuild replaces
#: the committed entries for exactly these ids (dropping any that no longer meet
#: :data:`MIN_CHARACTERS`); every other id is carried over untouched.
_REBUILT_IDS: frozenset[str] = frozenset(
    spec.id for spec in CATEGORY_SPECS if spec.predicate is not None
)


@dataclass(frozen=True)
class BuildReport:
    """What the build could not join, per ADR 0004 ("reported, never silently
    dropped"). Both lists are necessarily empty in this slice — no Category
    Group with a predicate here needs a join."""

    unjoinable_devil_fruits: tuple[str, ...] = ()
    unjoinable_journey_locations: tuple[str, ...] = ()


@dataclass(frozen=True)
class BuildResult:
    """The output of :func:`build_categories`, each field covering only the rows
    the builder can currently produce (Status and Race):

    * :attr:`categories_json` — the ``categories.json`` payload, for
      :func:`dump_categories_json`.
    * :attr:`categories_txt` — the ``categories.txt`` payload (each Category's
      Group, label and count, no Character list), for :func:`dump_categories_txt`.
    * :attr:`report` — the :class:`BuildReport`.
    """

    categories_json: tuple[CategoryEntry, ...]
    categories_txt: tuple[TxtCategory, ...]
    report: BuildReport


def build_categories(
    raw_characters: Iterable[RawCharacter],
    raw_devil_fruits: Iterable[Mapping[str, Any]],
    raw_islands: Iterable[Mapping[str, Any]],
) -> BuildResult:
    """Build the ``categories.json`` and ``categories.txt`` payloads from the
    three Raw dataset structures.

    Pure and deterministic: the same Raw input always yields byte-identical
    output. Only :data:`CATEGORY_SPECS` rows that carry a predicate (Status,
    Race) are produced; a Category matched by fewer than :data:`MIN_CHARACTERS`
    Characters is omitted. ``raw_devil_fruits`` / ``raw_islands`` are accepted
    now so the signature is stable for the join (#19b) and parsing (#19c)
    slices; they are unused here.
    """

    del raw_devil_fruits, raw_islands  # join inputs for #19b / #19c; unused here

    characters = list(raw_characters)
    json_payload: list[CategoryEntry] = []
    txt_payload: list[TxtCategory] = []
    for spec in CATEGORY_SPECS:
        predicate = spec.predicate
        if predicate is None:
            continue
        names = sorted(str(c["name"]) for c in characters if predicate(c))
        if len(names) < MIN_CHARACTERS:
            continue
        json_payload.append(
            CategoryEntry(
                id=spec.id,
                label=spec.label,
                count=len(names),
                characters=names,
            )
        )
        txt_payload.append(
            TxtCategory(
                id=spec.id,
                label=spec.label,
                count=len(names),
                group=spec.group,
            )
        )

    return BuildResult(
        categories_json=tuple(json_payload),
        categories_txt=tuple(txt_payload),
        report=BuildReport(),
    )


def _sort_key(entry: _CategoryHeader) -> tuple[int, str]:
    """Categories sort by descending ``count``, then ``id`` ascending — the
    order both committed files use."""

    return (-entry["count"], entry["id"])


def dump_categories_json(payload: Iterable[CategoryEntry]) -> str:
    """Serialise a ``categories.json`` payload exactly as the committed file:
    entries sorted by :func:`_sort_key`, keys ``id`` / ``label`` / ``count`` /
    ``characters``, each ``characters`` list sorted, two-space indent,
    ``ensure_ascii=False``, no trailing newline."""

    normalised = [
        {
            "id": entry["id"],
            "label": entry["label"],
            "count": entry["count"],
            "characters": sorted(entry["characters"]),
        }
        for entry in sorted(payload, key=_sort_key)
    ]
    return json.dumps(normalised, indent=2, ensure_ascii=False)


def to_txt_payload(payload: Iterable[CategoryEntry]) -> list[TxtCategory]:
    """Turn a ``categories.json`` payload into a ``categories.txt`` one: drop
    the Character list and attach each Category's **Category Group** from
    :data:`CATEGORY_SPECS`."""

    return [
        TxtCategory(
            id=entry["id"],
            label=entry["label"],
            count=entry["count"],
            group=_GROUP_BY_ID[entry["id"]],
        )
        for entry in payload
    ]


def dump_categories_txt(payload: Iterable[TxtCategory]) -> str:
    """Serialise the human-readable ``categories.txt`` exactly as committed:
    the fixed four-line header, then one block per **Category Group** in
    ``CategoryGroup`` order — a 70-``=`` rule, ``<Group>  (N categories)``, the
    rule again, then ``  <label><count> characters`` with the label left-padded
    to the group's widest label and the count right-aligned in a column as wide
    as the file's largest count plus a two-space gap. Blocks are separated by a
    blank line; the file ends with a single newline."""

    entries = list(payload)
    count_width = (
        max((len(str(entry["count"])) for entry in entries), default=0) + _COUNT_GAP
    )

    header = "\n".join(
        [
            "ONE PIECE - CATEGORY LIST",
            "Categories matched by at least 3 characters. "
            "Count = number of matching characters.",
            "Source: characters.json (joined with devil_fruits.json and islands.json)",
            f"Total: {len(entries)} categories",
        ]
    )

    by_group: dict[CategoryGroup, list[TxtCategory]] = {}
    for entry in entries:
        by_group.setdefault(entry["group"], []).append(entry)

    blocks = [header]
    rule = "=" * _RULE_WIDTH
    for group in CategoryGroup:
        members = by_group.get(group)
        if not members:
            continue
        members = sorted(members, key=_sort_key)
        label_width = max(len(member["label"]) for member in members)
        lines = [rule, f"{group.value}  ({len(members)} categories)", rule]
        lines.extend(
            f"  {member['label']:<{label_width}}"
            f"{member['count']:>{count_width}} characters"
            for member in members
        )
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks) + "\n"


def _merge_into_committed(
    committed: Iterable[_Header], built: Iterable[_Header]
) -> list[_Header]:
    """Overlay the freshly built entries onto the committed payload (works on a
    ``categories.json`` or a ``categories.txt`` payload alike).

    Every id in :data:`_REBUILT_IDS` is dropped from the committed payload and
    replaced by whatever ``built`` produced for it — so a Status / Race Category
    that fell below :data:`MIN_CHARACTERS` is removed, not left stale. Ids the
    builder does not yet own are carried over untouched: the builder is not yet
    the source of the whole file (ADR 0004 rollout step 1).
    """

    carried_over = [entry for entry in committed if entry["id"] not in _REBUILT_IDS]
    return carried_over + list(built)


def read_json(path: Path) -> Any:
    """Parse a UTF-8 JSON file. Thin wrapper so the reads share one spelling."""

    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    """Rebuild ``categories.json`` and ``categories.txt`` in place from the
    committed Raw dataset."""

    result = build_categories(
        read_json(CHARACTERS_PATH),
        read_json(DEVIL_FRUITS_PATH),
        read_json(ISLANDS_PATH),
    )
    committed = read_json(CATEGORIES_JSON_PATH)
    json_payload = _merge_into_committed(committed, result.categories_json)
    txt_payload = _merge_into_committed(to_txt_payload(committed), result.categories_txt)

    CATEGORIES_JSON_PATH.write_text(
        dump_categories_json(json_payload), encoding="utf-8", newline="\n"
    )
    CATEGORIES_TXT_PATH.write_text(
        dump_categories_txt(txt_payload), encoding="utf-8", newline="\n"
    )

    built_ids = ", ".join(sorted(entry["id"] for entry in result.categories_json))
    print(
        f"Rebuilt {CATEGORIES_JSON_PATH.name} and {CATEGORIES_TXT_PATH.name} "
        f"({len(result.categories_json)} Categories rebuilt: {built_ids})."
    )
    for value in result.report.unjoinable_devil_fruits:
        print(f"  unjoinable devil_fruit: {value}")
    for value in result.report.unjoinable_journey_locations:
        print(f"  unjoinable journey location: {value}")


if __name__ == "__main__":
    main()
