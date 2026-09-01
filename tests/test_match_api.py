"""Seam 1 - HTTP behaviour of Match creation and retrieval."""

from __future__ import annotations

from fastapi.testclient import TestClient

VALID_PLAYERS = {"P1", "P2"}
VALID_GROUPS = {
    "Bounty",
    "Race",
    "Status",
    "Affiliation",
    "Origin sea",
    "Devil Fruit",
    "Haki",
    "Height",
    "Age",
    "Debut chapter",
    "Visited (journey)",
    "Misc",
}


def test_create_match_returns_wellformed_grid(client: TestClient) -> None:
    response = client.post("/matches")

    assert response.status_code == 201
    body = response.json()

    assert body["id"]
    assert body["status"] == "in-progress"
    assert body["active_player"] in VALID_PLAYERS

    grid = body["grid"]
    assert len(grid["row_categories"]) == 3
    assert len(grid["column_categories"]) == 3
    for category in grid["row_categories"] + grid["column_categories"]:
        assert category["label"]
        assert category["group"] in VALID_GROUPS

    assert len(grid["cells"]) == 9
    for cell in grid["cells"]:
        assert cell["claimed_by"] is None
        assert cell["character"] is None
    coordinates = {(cell["row"], cell["column"]) for cell in grid["cells"]}
    assert coordinates == {(r, c) for r in range(3) for c in range(3)}


def test_create_then_fetch_returns_same_match(client: TestClient) -> None:
    created = client.post("/matches").json()

    fetched = client.get(f"/matches/{created['id']}")

    assert fetched.status_code == 200
    body = fetched.json()
    assert body["id"] == created["id"]
    assert body["grid"] == created["grid"]
    assert body["active_player"] == created["active_player"]
    assert body["status"] == "in-progress"
    assert len(body["grid"]["cells"]) == 9
    assert all(cell["claimed_by"] is None for cell in body["grid"]["cells"])


def test_fetch_unknown_match_returns_404(client: TestClient) -> None:
    response = client.get("/matches/does-not-exist")

    assert response.status_code == 404


def test_matches_are_isolated_by_id(client: TestClient) -> None:
    first = client.post("/matches").json()
    second = client.post("/matches").json()

    assert first["id"] != second["id"]


def _grid_category_ids(grid: dict) -> list[str]:
    return [c["id"] for c in grid["row_categories"] + grid["column_categories"]]


def test_same_seed_returns_the_same_grid(client: TestClient) -> None:
    first = client.post("/matches", json={"seed": 20260901})
    second = client.post("/matches", json={"seed": 20260901})

    assert first.status_code == 201
    assert first.json()["grid"] == second.json()["grid"]


def test_explicit_category_ids_force_that_exact_grid(client: TestClient) -> None:
    # Take a known-good six from a seeded Grid, then pin it explicitly.
    seeded = client.post("/matches", json={"seed": 42}).json()["grid"]
    forced_ids = _grid_category_ids(seeded)

    response = client.post("/matches", json={"category_ids": forced_ids})

    assert response.status_code == 201
    assert _grid_category_ids(response.json()["grid"]) == forced_ids


def test_unsolvable_forced_grid_is_rejected_with_422(client: TestClient) -> None:
    # "Bounty >= 1,000,000,000" against "Bounty below 100,000,000": no Character
    # can sit in that Cell.
    forced_ids = [
        "bounty_1000000000",
        "haki_arm",
        "origin_East Blue",
        "bounty_under_100m",
        "df_Zoan",
        "age_60_plus",
    ]

    response = client.post("/matches", json={"category_ids": forced_ids})

    assert response.status_code == 422


def test_unknown_forced_category_id_is_rejected_with_422(client: TestClient) -> None:
    forced_ids = [
        "bounty_100000000",
        "haki_arm",
        "origin_East Blue",
        "df_Zoan",
        "age_60_plus",
        "not_a_real_category",
    ]

    response = client.post("/matches", json={"category_ids": forced_ids})

    assert response.status_code == 422
