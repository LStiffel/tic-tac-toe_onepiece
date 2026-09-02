"""Load the One Piece dataset into a Roster and a set of playable Categories.

At server startup the game reads ``characters.json`` and ``categories.json`` once
and keeps the result in memory (ADR 0001). The vocabulary is CONTEXT.md's:

* the **Roster** is every **Character**, taken solely from ``characters.json``;
  a Character's identity is its *canonical name* (:func:`canonical_name`).
* each **Category** from ``categories.json`` is assigned a **Category Group**
  (:func:`group_for_id`) and has its ``characters`` list resolved against the
  Roster. Names that do not resolve are a data defect: they are dropped from the
  Category's *playable set* and collected in the **data-quality report**.
* a Category whose playable set is below :data:`VIABLE_THRESHOLD` after
  resolution is excluded from play.

Only :attr:`GameData.roster_names` and :attr:`GameData.character_images` are
meant to reach the client (autocomplete and Character art); the
Category-to-Characters answer key stays server-side.
"""

from __future__ import annotations

import json
import logging
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.domain import Category, CategoryGroup

logger = logging.getLogger(__name__)

# Repo root: this file is ``<root>/app/dataset.py``.
REPO_ROOT = Path(__file__).resolve().parent.parent
CHARACTERS_PATH = REPO_ROOT / "characters.json"
CATEGORIES_PATH = REPO_ROOT / "categories.json"

#: Smallest playable set a Category may have after unresolved names are dropped.
#: A Category with fewer resolved Characters than this is excluded from play.
VIABLE_THRESHOLD = 3

#: Category Group for each ``id`` prefix (the substring before the first ``_``).
#: Prefixes not listed here - ``has``, ``name``, ``rel`` and anything else -
#: fall to :attr:`CategoryGroup.MISC`.
_GROUP_BY_PREFIX: dict[str, CategoryGroup] = {
    "bounty": CategoryGroup.BOUNTY,
    "race": CategoryGroup.RACE,
    "status": CategoryGroup.STATUS,
    "aff": CategoryGroup.AFFILIATION,
    "origin": CategoryGroup.ORIGIN_SEA,
    "df": CategoryGroup.DEVIL_FRUIT,
    "haki": CategoryGroup.HAKI,
    "height": CategoryGroup.HEIGHT,
    "age": CategoryGroup.AGE,
    "debut": CategoryGroup.DEBUT_CHAPTER,
    "visited": CategoryGroup.VISITED,
}


def canonical_name(raw: str) -> str:
    """Return the canonical form of a Character name: leading/trailing whitespace
    trimmed, internal whitespace runs collapsed to a single space, Unicode NFC.

    ``"Bjorn"`` and ``"Bjorn "`` both canonicalise to ``"Bjorn"``.
    """

    return unicodedata.normalize("NFC", " ".join(raw.split()))


def build_character_images(
    raw_characters: Iterable[Mapping[str, Any]],
) -> dict[str, str]:
    """Map each canonical Character name to its ``image`` path from
    ``characters.json`` (e.g. ``/images/characters/Nami.webp``).

    The first entry seen for a canonical name wins, matching
    :func:`build_roster`'s collapse of whitespace-only variants. An entry with no
    ``image`` maps to ``""`` - the frontend treats that the same as a missing
    file and shows its placeholder.
    """

    images: dict[str, str] = {}
    for entry in raw_characters:
        name = canonical_name(entry["name"])
        if name not in images:
            images[name] = str(entry.get("image") or "")
    return images


def group_for_id(category_id: str) -> CategoryGroup:
    """Derive a Category's :class:`CategoryGroup` from its ``id`` prefix.

    Unmapped prefixes (and ids with no ``_``) fall to :attr:`CategoryGroup.MISC`.
    """

    prefix = category_id.split("_", 1)[0]
    return _GROUP_BY_PREFIX.get(prefix, CategoryGroup.MISC)


def build_roster(raw_characters: Iterable[Mapping[str, Any]]) -> frozenset[str]:
    """Build the Roster - the set of canonical Character names - from the parsed
    contents of ``characters.json``. Entries whose names canonicalise to the same
    string collapse to one Character."""

    return frozenset(
        canonical_name(entry["name"]) for entry in raw_characters
    )


@dataclass(frozen=True)
class LoadedCategory:
    """A ``categories.json`` entry resolved against the Roster.

    Wraps the domain :class:`Category` (``id`` / ``label`` / ``group``) and adds
    the ``count`` declared in the source file and the resolved *playable set*.
    ``characters`` is the server-side answer key and is never shipped to the
    client.
    """

    category: Category
    count: int
    characters: frozenset[str]


@dataclass(frozen=True)
class DataQualityReport:
    """What the dataset load could not make sense of.

    * ``unresolved`` maps a Category id to the tuple of canonical names it
      referenced that do not resolve to any Roster Character (sorted,
      de-duplicated).
    * ``excluded_categories`` is the ids of Categories dropped from play because
      their playable set fell below :data:`VIABLE_THRESHOLD` after resolution.
    """

    unresolved: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    excluded_categories: tuple[str, ...] = ()

    @property
    def unresolved_name_count(self) -> int:
        """Total count of unresolved Category-referenced names across all
        Categories."""

        return sum(len(names) for names in self.unresolved.values())


def resolve_categories(
    raw_categories: Iterable[Mapping[str, Any]],
    roster: frozenset[str],
) -> tuple[tuple[LoadedCategory, ...], DataQualityReport]:
    """Resolve every Category's ``characters`` list against ``roster``.

    Returns the playable Categories (those with at least :data:`VIABLE_THRESHOLD`
    resolved Characters) and a :class:`DataQualityReport` covering the rest.
    """

    playable: list[LoadedCategory] = []
    unresolved: dict[str, tuple[str, ...]] = {}
    excluded: list[str] = []

    for raw in raw_categories:
        category_id = raw["id"]
        referenced = [canonical_name(name) for name in raw["characters"]]

        resolved = frozenset(name for name in referenced if name in roster)
        missing = tuple(sorted({name for name in referenced if name not in roster}))
        if missing:
            unresolved[category_id] = missing

        if len(resolved) < VIABLE_THRESHOLD:
            excluded.append(category_id)
            continue

        playable.append(
            LoadedCategory(
                category=Category(
                    id=category_id,
                    label=raw["label"],
                    group=group_for_id(category_id),
                ),
                count=raw["count"],
                characters=resolved,
            )
        )

    report = DataQualityReport(
        unresolved=unresolved,
        excluded_categories=tuple(excluded),
    )
    return tuple(playable), report


@dataclass(frozen=True)
class GameData:
    """The in-memory dataset: the Roster, the playable Categories, the
    data-quality report from the load, and each Character's art path."""

    roster: frozenset[str]
    categories: tuple[LoadedCategory, ...]
    report: DataQualityReport
    # Defaulted (unlike its siblings) so Grid-generation tests can build a
    # GameData from a hand-made Roster without also supplying art paths.
    character_images: Mapping[str, str] = field(default_factory=dict)

    @property
    def roster_names(self) -> list[str]:
        """The Roster as a sorted flat list of canonical names - given to the
        client for autocomplete."""

        return sorted(self.roster)

    @property
    def character_art(self) -> list[tuple[str, str]]:
        """Every Roster Character as ``(name, image path)``, sorted by name.
        ``image`` is ``""`` when the dataset carries no art for that Character.
        Shipped to the client for the Cell / detail-area ``<img>`` tags."""

        return [
            (name, self.character_images.get(name, "")) for name in self.roster_names
        ]

    @classmethod
    def from_raw(
        cls,
        raw_characters: Iterable[Mapping[str, Any]],
        raw_categories: Iterable[Mapping[str, Any]],
    ) -> GameData:
        """Build :class:`GameData` from already-parsed JSON structures."""

        characters = list(raw_characters)  # read twice: roster and art paths
        roster = build_roster(characters)
        categories, report = resolve_categories(raw_categories, roster)
        return cls(
            roster=roster,
            categories=categories,
            report=report,
            character_images=build_character_images(characters),
        )


def load_game_data(
    characters_path: Path = CHARACTERS_PATH,
    categories_path: Path = CATEGORIES_PATH,
) -> GameData:
    """Read the dataset files from disk and build :class:`GameData`."""

    raw_characters = json.loads(characters_path.read_text(encoding="utf-8"))
    raw_categories = json.loads(categories_path.read_text(encoding="utf-8"))
    return GameData.from_raw(raw_characters, raw_categories)


@lru_cache(maxsize=1)
def default_game_data() -> GameData:
    """The dataset loaded from the repo's ``characters.json`` /
    ``categories.json``, cached for the process lifetime."""

    return load_game_data()


def log_data_quality(data: GameData) -> None:
    """Log the data-quality report. Called once from the app's startup hook
    (issue #3: "the report is also logged at startup")."""

    report = data.report
    logger.info(
        "Dataset loaded: %d Characters in the Roster, %d playable Categories, "
        "%d Categories excluded below the viable threshold (%d), "
        "%d unresolved Category-referenced names across %d Categories.",
        len(data.roster),
        len(data.categories),
        len(report.excluded_categories),
        VIABLE_THRESHOLD,
        report.unresolved_name_count,
        len(report.unresolved),
    )
    if report.excluded_categories:
        logger.info(
            "Excluded Categories: %s", ", ".join(report.excluded_categories)
        )
    for category_id, names in report.unresolved.items():
        logger.info(
            "Category %s references %d unresolved name(s): %s",
            category_id,
            len(names),
            ", ".join(names),
        )
