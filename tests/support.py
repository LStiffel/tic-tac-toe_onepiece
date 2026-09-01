"""Shared crafted dataset for the claim-a-cell tests (both seams).

Six Categories over six Characters, ordered three row Categories then three
column Categories, chosen so every Cell of the

    rows    = (race_a, race_b, aff_crew)
    columns = (haki_arm, df_para, origin_gl)

Grid has a known, small row-Category-intersect-column-Category set. Deliberately
tiny so every "does this Character fit this Cell" assertion is exact
(``docs/agents/testing.md``).
"""

from __future__ import annotations

from app.dataset import DataQualityReport, GameData, LoadedCategory
from app.domain import Category, CategoryGroup

ROSTER = frozenset({"Luffy", "Zoro", "Nami", "Robin", "Franky", "Brook"})


def loaded_category(
    category_id: str, group: CategoryGroup, members: set[str]
) -> LoadedCategory:
    return LoadedCategory(
        category=Category(
            id=category_id,
            label=category_id.replace("_", " ").title(),
            group=group,
        ),
        count=len(members),
        characters=frozenset(members),
    )


#: Three row Categories then three column Categories.
CRAFTED_CATEGORIES: tuple[LoadedCategory, ...] = (
    loaded_category("race_a", CategoryGroup.RACE, {"Luffy", "Zoro", "Nami"}),
    loaded_category("race_b", CategoryGroup.RACE, {"Robin", "Franky", "Brook"}),
    loaded_category(
        "aff_crew", CategoryGroup.AFFILIATION, {"Zoro", "Nami", "Robin"}
    ),
    loaded_category("haki_arm", CategoryGroup.HAKI, {"Luffy", "Zoro", "Robin"}),
    loaded_category(
        "df_para", CategoryGroup.DEVIL_FRUIT, {"Luffy", "Robin", "Brook"}
    ),
    loaded_category(
        "origin_gl", CategoryGroup.ORIGIN_SEA, {"Nami", "Franky", "Brook"}
    ),
)

#: The six ids in Grid order - pass as ``category_ids`` to force this exact Grid.
CRAFTED_CATEGORY_IDS: list[str] = [
    lc.category.id for lc in CRAFTED_CATEGORIES
]


def crafted_game_data() -> GameData:
    return GameData(
        roster=ROSTER,
        categories=CRAFTED_CATEGORIES,
        report=DataQualityReport(),
    )
