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
  ``label``, a :class:`~app.domain.CategoryGroup`, and an optional *predicate*
  over a Raw Character. Three kinds of row are built so far:
    - **Status / Race** (issue #24 / #19a) — the row carries a ``predicate``: a
      plain equality on the Character's ``status`` / ``race`` field, no join.
    - **Devil Fruit / Visited** (issue #25 / #19b) — the row's ``predicate`` is
      ``None``; membership comes from the ``devil_fruits.json`` /
      ``islands.json`` join (:func:`_fruit_category_ids`,
      :func:`_visited_category_ids`). Both sides of a join are compared on
      :func:`_join_key`.
    - **Bounty / Debut chapter** (issue #26 / #19c) — the row carries a
      ``predicate`` that first *parses* a number out of the Raw field
      (:func:`_parse_bounty` off ``bounty``, :func:`_parse_debut_chapter` off
      ``first_appearance_arc``) and then tests it against a threshold or range.
      No join.
  Every other row's predicate is ``None`` until a later slice fills it in.
* :func:`build_categories` — a pure, deterministic function from the three Raw
  structures to a :class:`BuildResult`: the ``categories.json`` payload, the
  ``categories.txt`` payload, and a :class:`BuildReport` of the values that would
  not join. Each payload covers only the rows the builder can build.
* :func:`dump_categories_json` / :func:`dump_categories_txt` — serialisers that
  reproduce the committed files byte-for-byte from those payloads. The exact
  normalisation is recorded in ``docs/measurements/categories-serialisation.md``.
  :func:`to_txt_payload` turns a ``categories.json`` payload into a
  ``categories.txt`` one by attaching each Category's Group.

Run ``python -m scripts.build_categories`` to rebuild both files in place: the
Status / Race / Bounty / Debut chapter / Devil Fruit / Visited Categories are
rebuilt from the Raw dataset, every other Category is carried over from the
committed ``categories.json`` unchanged (the builder is not yet the source of
the whole file), and both files are re-serialised through the helpers above.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict, TypeVar

from app.dataset import canonical_name
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


#: First run of digits (with thousands commas) in a prose ``bounty`` string.
_BOUNTY_FIGURE = re.compile(r"[0-9][0-9,]*")

#: First run of digits anywhere in a ``first_appearance_arc`` string.
_CHAPTER_NUMBER = re.compile(r"[0-9]+")


def _parse_bounty(value: object) -> int | None:
    """The Berry figure of a Raw ``bounty`` field, or ``None`` for "no known
    bounty".

    Upstream stores it as an ``int`` (``138000000``), as a prose ``str``
    (``"At least 100,000,000"``, ``"80,060,000 (former)"``,
    ``"500,000,000 [Cross Guild]"``, ``"Less than 15,000,000"``), or omits it
    entirely. From a string the first run of digits and thousands commas is taken
    and the commas dropped, so a qualifier like "At least" or "Less than" is
    ignored and the figure it modifies is used as-is — matching the committed
    ``categories.json``. A value with no digits yields ``None``.
    """

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    match = _BOUNTY_FIGURE.search(value)
    if match is None:
        return None
    return int(match.group(0).replace(",", ""))


def _parse_debut_chapter(value: object) -> int | None:
    """The chapter number a Character debuted in, parsed from a Raw
    ``first_appearance_arc`` value, or ``None`` when none can be read.

    The usual form is ``"Chapter 551"`` or ``"Chapter 487 (cover)"``; the parse
    takes the first run of digits anywhere in the string. This is deliberately
    the same naive parse that produced the committed ``categories.json`` (the
    golden test pins it byte-for-byte): a value with an incidental number such as
    ``"SBS Volume 105"`` or ``"One Piece novel A - Vol. 1"`` therefore resolves
    to a chapter as well, while a digit-free value (``"Monsters"``,
    ``"Loguetown Arc (Novel)"``) or a missing field resolves to no debut chapter
    and drops out of every Debut chapter Category. ``"Strong World: Chap. 0"``
    parses to ``0``, which sits below every Debut chapter Category's floor.
    """

    if not isinstance(value, str):
        return None
    match = _CHAPTER_NUMBER.search(value)
    if match is None:
        return None
    return int(match.group(0))


def _has_known_bounty(character: RawCharacter) -> bool:
    """True when ``bounty`` parses to any figure — the ``bounty_1`` Category."""

    return _parse_bounty(character.get("bounty")) is not None


def _number_field_in_band(
    parse: Callable[[object], int | None],
    field_name: str,
    low: int | None,
    high: int | None,
) -> Predicate:
    """A predicate true when ``parse`` reads a number out of ``field_name`` that
    lies in the half-open band ``[low, high)``. A ``None`` bound is open, so
    ``(None, None)`` is a bare "the field parses to a number" test. A Character
    whose field does not parse is never in it.

    The single shape behind both the Bounty thresholds (:func:`_bounty_in_berries`)
    and the Debut chapter ranges (:func:`_debut_chapter_in`).
    """

    def predicate(character: RawCharacter) -> bool:
        number = parse(character.get(field_name))
        if number is None:
            return False
        return (low is None or number >= low) and (high is None or number < high)

    return predicate


def _bounty_in_berries(low: int | None, high: int | None) -> Predicate:
    """A predicate over the ``bounty`` field for the half-open Berry band
    ``[low, high)`` — ``_bounty_in_berries(500_000_000, None)`` is "≥ 500,000,000",
    ``_bounty_in_berries(None, 100_000_000)`` is "below 100,000,000 (but has
    one)". The upper bound is exclusive so a figure of exactly ``high`` belongs to
    the next threshold up, not this band."""

    return _number_field_in_band(_parse_bounty, "bounty", low, high)


def _debut_chapter_in(low: int, high: int) -> Predicate:
    """A predicate true when the parsed debut chapter is within ``[low, high]``
    *inclusive* — the bounds read the same as the Category id (``debut_1_597`` is
    ``_debut_chapter_in(1, 597)``). A Character with no parseable chapter is never
    in it."""

    return _number_field_in_band(
        _parse_debut_chapter, "first_appearance_arc", low, high + 1
    )


def _join_key(raw: str) -> str:
    """The key both sides of the Devil Fruit and journey/island joins are
    compared on: the *canonical name* (:func:`app.dataset.canonical_name` -
    leading/trailing whitespace trimmed, internal runs collapsed, NFC) folded to
    lower case.

    The canonical step alone lets the leading space in Upstream fruit names
    (``" Bara Bara no Mi"``) join cleanly, so the notebook's ``" " + name`` hack
    is gone. The case fold absorbs the last of the noise: Blackbeard's second
    fruit is spelled ``" Gura Gura No Mi"`` on the Character but
    ``" Gura Gura no Mi"`` in ``devil_fruits.json``.
    """

    return canonical_name(raw).casefold()


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
    CategorySpec("bounty_1", "Has a known bounty", CategoryGroup.BOUNTY, _has_known_bounty),
    CategorySpec("bounty_100000000", "Bounty ≥ 100,000,000", CategoryGroup.BOUNTY, _bounty_in_berries(100_000_000, None)),
    CategorySpec("bounty_under_100m", "Bounty below 100,000,000 (but has one)", CategoryGroup.BOUNTY, _bounty_in_berries(None, 100_000_000)),
    CategorySpec("bounty_500000000", "Bounty ≥ 500,000,000", CategoryGroup.BOUNTY, _bounty_in_berries(500_000_000, None)),
    CategorySpec("bounty_1000000000", "Bounty ≥ 1,000,000,000", CategoryGroup.BOUNTY, _bounty_in_berries(1_000_000_000, None)),
    CategorySpec("bounty_1500000000", "Bounty ≥ 1,500,000,000", CategoryGroup.BOUNTY, _bounty_in_berries(1_500_000_000, None)),
    CategorySpec("bounty_3000000000", "Bounty ≥ 3,000,000,000", CategoryGroup.BOUNTY, _bounty_in_berries(3_000_000_000, None)),
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
    CategorySpec("debut_598_9999", "Debuted after the timeskip (ch. ≥ 598)", CategoryGroup.DEBUT_CHAPTER, _debut_chapter_in(598, 9999)),
    CategorySpec("debut_1_597", "Debuted before the timeskip (ch. ≤ 597)", CategoryGroup.DEBUT_CHAPTER, _debut_chapter_in(1, 597)),
    CategorySpec("debut_900_9999", "Debut chapter ≥ 900", CategoryGroup.DEBUT_CHAPTER, _debut_chapter_in(900, 9999)),
    CategorySpec("debut_1_300", "Debut chapter 1–300", CategoryGroup.DEBUT_CHAPTER, _debut_chapter_in(1, 300)),
    CategorySpec("debut_1_100", "Debut chapter 1–100", CategoryGroup.DEBUT_CHAPTER, _debut_chapter_in(1, 100)),
    CategorySpec("debut_1000_9999", "Debut chapter ≥ 1000", CategoryGroup.DEBUT_CHAPTER, _debut_chapter_in(1000, 9999)),
    CategorySpec("debut_ch1", "Debuted in Chapter 1", CategoryGroup.DEBUT_CHAPTER, _debut_chapter_in(1, 1)),
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

#: Category Groups this builder populates through a join rather than a per-field
#: predicate (issue #25). Every :data:`CATEGORY_SPECS` row in one of these Groups
#: is built from the ``devil_fruits.json`` / ``islands.json`` join below; its
#: ``predicate`` stays ``None``.
_JOIN_GROUPS: frozenset[CategoryGroup] = frozenset(
    {CategoryGroup.DEVIL_FRUIT, CategoryGroup.VISITED}
)


def _is_rebuilt(spec: CategorySpec) -> bool:
    """Whether the builder can build ``spec`` from the Raw dataset: any row that
    carries a ``predicate`` — the plain field equalities of Status / Race (issue
    #24) and the parse-then-compare predicates of Bounty / Debut chapter (issue
    #26) — or a join-backed Devil Fruit / Visited row (issue #25)."""

    return spec.predicate is not None or spec.group in _JOIN_GROUPS


#: The ``id``s this builder owns. A rebuild replaces the committed entries for
#: exactly these ids (dropping any that no longer meet :data:`MIN_CHARACTERS`);
#: every other id is carried over untouched.
_REBUILT_IDS: frozenset[str] = frozenset(
    spec.id for spec in CATEGORY_SPECS if _is_rebuilt(spec)
)

#: Devil Fruit ``type`` value → the ``df_*`` Category id. A fruit whose ``type``
#: is anything else (``"Unknown"``) still joins — it just adds no ``df_*``
#: membership.
_DF_TYPE_IDS: dict[str, str] = {
    "Zoan": "df_Zoan",
    "Paramecia": "df_Paramecia",
    "Logia": "df_Logia",
}

#: Devil Fruit ``subtype`` value → the ``df_sub_*`` Category id.
_DF_SUBTYPE_IDS: dict[str, str] = {
    "Artificial": "df_sub_Artificial",
    "Mythical": "df_sub_Mythical",
    "Ancient": "df_sub_Ancient",
}

#: The Category id every Character with a ``devil_fruit`` value joins — before
#: any lookup, so an unjoinable value never costs a Character this membership.
_HAS_DF_ID = "has_df"

#: ``visited_*`` Category id → the :func:`_join_key` of the journey ``location``
#: that places a Character in it. The id's suffix is that location verbatim, so
#: the same key derivation used everywhere else applies here too.
_VISITED_LOCATION_IDS: dict[str, str] = {
    spec.id: _join_key(spec.id[len("visited_") :])
    for spec in CATEGORY_SPECS
    if spec.group is CategoryGroup.VISITED
}


def _devil_fruit_index(
    raw_devil_fruits: Iterable[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    """``devil_fruits.json`` keyed by :func:`_join_key` of each fruit's
    ``name``."""

    return {_join_key(str(fruit["name"])): fruit for fruit in raw_devil_fruits}


def _devil_fruit_values(character: RawCharacter) -> tuple[str, ...]:
    """A Character's ``devil_fruit`` as a tuple of individual fruit names: ``()``
    when absent, one element for the common single-fruit case, and every element
    of the one multi-type value (Blackbeard's Logia + Paramecia pair)."""

    value = character.get("devil_fruit")
    if not value:
        return ()
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    return (str(value),)


def _fruit_category_ids(
    character: RawCharacter, fruit_index: Mapping[str, Mapping[str, Any]]
) -> frozenset[str]:
    """The Devil Fruit Category ids ``character`` belongs to. ``has_df`` for any
    ``devil_fruit`` value; plus the ``df_*`` / ``df_sub_*`` id of every value
    that joins. An unjoinable value is skipped here and surfaces in the build
    report instead — the Character keeps ``has_df`` and every non-join
    Category."""

    values = _devil_fruit_values(character)
    if not values:
        return frozenset()

    ids = {_HAS_DF_ID}
    for value in values:
        fruit = fruit_index.get(_join_key(value))
        if fruit is None:
            continue
        type_id = _DF_TYPE_IDS.get(str(fruit.get("type")))
        if type_id is not None:
            ids.add(type_id)
        subtype_id = _DF_SUBTYPE_IDS.get(str(fruit.get("subtype")))
        if subtype_id is not None:
            ids.add(subtype_id)
    return frozenset(ids)


def _journey_location_values(character: RawCharacter) -> tuple[str, ...]:
    """Every ``journey[].location`` value on a Character, verbatim, in order.
    The single spelling of the journey walk both the Visited join and the
    unresolved-location report go through."""

    return tuple(
        str(step["location"])
        for step in character.get("journey") or []
        if step.get("location")
    )


def _visited_category_ids(character: RawCharacter) -> frozenset[str]:
    """The ``visited_*`` Category ids ``character`` belongs to: one per journey
    ``location`` whose :func:`_join_key` matches a Visited Category."""

    location_keys = {_join_key(value) for value in _journey_location_values(character)}
    return frozenset(
        category_id
        for category_id, location_key in _VISITED_LOCATION_IDS.items()
        if location_key in location_keys
    )


def _unjoinable_devil_fruit_values(
    characters: Iterable[RawCharacter],
    fruit_index: Mapping[str, Mapping[str, Any]],
) -> tuple[str, ...]:
    """Every distinct ``devil_fruit`` value (verbatim) with no ``devil_fruits.json``
    row, sorted — the ADR 0004 "reported, never silently dropped" list."""

    return tuple(
        sorted(
            {
                value
                for character in characters
                for value in _devil_fruit_values(character)
                if _join_key(value) not in fruit_index
            }
        )
    )


def _is_unlocated(location: str) -> bool:
    """Whether ``location`` is Upstream's sentinel for a journey step it
    deliberately cannot place on a map — ``"Unknown island"`` on its own or
    ``"Unknown island - <what happened>"`` — rather than the name of a place
    that failed to join. The sentinel never names a real island, so it is not a
    join failure and is kept out of the build report."""

    key = _join_key(location)
    return key == "unknown island" or key.startswith("unknown island - ")


def _unresolved_journey_locations(
    characters: Iterable[RawCharacter], island_keys: frozenset[str]
) -> tuple[str, ...]:
    """Every distinct journey ``location`` (verbatim, sorted) that names a place
    with no matching island in ``islands.json``. Upstream's ``"Unknown island"``
    sentinel (:func:`_is_unlocated`) is excluded — it is intentionally unplaced,
    not a failed join."""

    return tuple(
        sorted(
            {
                value
                for character in characters
                for value in _journey_location_values(character)
                if not _is_unlocated(value) and _join_key(value) not in island_keys
            }
        )
    )


def _island_keys(raw_islands: Iterable[Mapping[str, Any]]) -> frozenset[str]:
    """Every island's :func:`_join_key` from ``islands.json`` — the set a
    journey ``location`` must hit to count as resolved."""

    return frozenset(_join_key(str(island["name"])) for island in raw_islands)


@dataclass(frozen=True)
class BuildReport:
    """What the build could not join, per ADR 0004 ("reported, never silently
    dropped"). Each list is the distinct offending values, verbatim and sorted;
    the Character keeps every Category that does not depend on the failed join.

    * :attr:`unjoinable_devil_fruits` — ``devil_fruit`` values with no
      ``devil_fruits.json`` row (so no ``df_*`` type/subtype membership; the
      Character still counts for ``has_df``).
    * :attr:`unjoinable_journey_locations` — journey ``location`` values that
      name a place with no matching island in ``islands.json``. Upstream's
      ``"Unknown island[ - …]"`` sentinel is intentionally unplaced, not a
      failed join, and is not listed.
    """

    unjoinable_devil_fruits: tuple[str, ...] = ()
    unjoinable_journey_locations: tuple[str, ...] = ()


@dataclass(frozen=True)
class BuildResult:
    """The output of :func:`build_categories`, each field covering the Category
    Groups this builder owns (Status, Race, Bounty, Debut chapter, Devil Fruit,
    Visited):

    * :attr:`categories_json` — the ``categories.json`` payload, for
      :func:`dump_categories_json`.
    * :attr:`categories_txt` — the ``categories.txt`` payload (each Category's
      Group, label and count, no Character list), for :func:`dump_categories_txt`.
    * :attr:`report` — the :class:`BuildReport`.
    """

    categories_json: tuple[CategoryEntry, ...]
    categories_txt: tuple[TxtCategory, ...]
    report: BuildReport


def _category_ids_for(
    character: RawCharacter, fruit_index: Mapping[str, Mapping[str, Any]]
) -> frozenset[str]:
    """Every Category id ``character`` belongs to across the Groups this builder
    owns: the field predicates (Status / Race equalities, Bounty / Debut chapter
    parse-and-compare) plus the Devil Fruit and journey/island joins."""

    predicate_ids = frozenset(
        spec.id
        for spec in CATEGORY_SPECS
        if spec.predicate is not None and spec.predicate(character)
    )
    return (
        predicate_ids
        | _fruit_category_ids(character, fruit_index)
        | _visited_category_ids(character)
    )


def _collect_member_names(
    characters: Iterable[RawCharacter],
    fruit_index: Mapping[str, Mapping[str, Any]],
) -> dict[str, list[str]]:
    """``id`` → the sorted Raw ``name`` of every Character in that Category, in
    one pass over the Roster.

    Names are kept verbatim and are *not* de-duplicated, so two Raw entries that
    share a name are both listed — matching the committed files.
    """

    names_by_id: dict[str, list[str]] = {}
    for character in characters:
        name = str(character["name"])
        for category_id in _category_ids_for(character, fruit_index):
            names_by_id.setdefault(category_id, []).append(name)
    for names in names_by_id.values():
        names.sort()
    return names_by_id


def build_categories(
    raw_characters: Iterable[RawCharacter],
    raw_devil_fruits: Iterable[Mapping[str, Any]],
    raw_islands: Iterable[Mapping[str, Any]],
) -> BuildResult:
    """Build the ``categories.json`` and ``categories.txt`` payloads from the
    three Raw dataset structures.

    Pure and deterministic: the same Raw input always yields byte-identical
    output. Produces every :data:`CATEGORY_SPECS` row this builder owns — the
    Status / Race field predicates (issue #24), the Bounty / Debut chapter
    parse-then-compare predicates (issue #26), and the Devil Fruit / Visited
    rows the ``devil_fruits.json`` and ``islands.json`` joins populate (issue
    #25). A Category matched by fewer than :data:`MIN_CHARACTERS` Characters is
    omitted. An unjoinable ``devil_fruit`` value or journey location is recorded
    in the :class:`BuildReport`, never silently dropped.
    """

    characters = list(raw_characters)
    fruit_index = _devil_fruit_index(raw_devil_fruits)
    island_keys = _island_keys(raw_islands)

    names_by_id = _collect_member_names(characters, fruit_index)

    json_payload: list[CategoryEntry] = []
    txt_payload: list[TxtCategory] = []
    for spec in CATEGORY_SPECS:
        names = names_by_id.get(spec.id)
        if names is None or len(names) < MIN_CHARACTERS:
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

    report = BuildReport(
        unjoinable_devil_fruits=_unjoinable_devil_fruit_values(
            characters, fruit_index
        ),
        unjoinable_journey_locations=_unresolved_journey_locations(
            characters, island_keys
        ),
    )
    return BuildResult(
        categories_json=tuple(json_payload),
        categories_txt=tuple(txt_payload),
        report=report,
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
    replaced by whatever ``built`` produced for it — so a builder-owned Category
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
