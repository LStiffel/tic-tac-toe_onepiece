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

from fastapi.testclient import TestClient

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


# --- HTTP-seam helpers (shared by the claim and Pass API tests) -------
#
# Both API test modules override the ``game_data`` fixture with
# :func:`crafted_game_data` and force this exact Grid via ``category_ids``.


def new_forced_match(client: TestClient) -> tuple[str, str]:
    """Create a Match forced onto the crafted Grid; return
    ``(match_id, active_player)``."""

    body = client.post(
        "/matches", json={"category_ids": CRAFTED_CATEGORY_IDS}
    ).json()
    return body["id"], body["active_player"]


def other_player(player: str) -> str:
    """The other player id - ``"P1"`` <-> ``"P2"``."""

    return "P2" if player == "P1" else "P1"


def post_guess(
    client: TestClient,
    match_id: str,
    *,
    player: str,
    row: int,
    column: int,
    character: str,
) -> dict:
    """POST a Guess and return the decoded body, asserting a 200 response."""

    response = client.post(
        f"/matches/{match_id}/guesses",
        json={
            "player": player,
            "row": row,
            "column": column,
            "character": character,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()
