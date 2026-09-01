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

    assert len(body["row_categories"]) == 3
    assert len(body["column_categories"]) == 3
    for category in body["row_categories"] + body["column_categories"]:
        assert category["label"]
        assert category["group"] in VALID_GROUPS

    assert len(body["cells"]) == 9
    for cell in body["cells"]:
        assert cell["claimed_by"] is None
        assert cell["character"] is None
    coordinates = {(cell["row"], cell["column"]) for cell in body["cells"]}
    assert coordinates == {(r, c) for r in range(3) for c in range(3)}


def test_create_then_fetch_returns_same_match(client: TestClient) -> None:
    created = client.post("/matches").json()

    fetched = client.get(f"/matches/{created['id']}")

    assert fetched.status_code == 200
    body = fetched.json()
    assert body["id"] == created["id"]
    assert body["row_categories"] == created["row_categories"]
    assert body["column_categories"] == created["column_categories"]
    assert body["active_player"] == created["active_player"]
    assert body["status"] == "in-progress"
    assert len(body["cells"]) == 9
    assert all(cell["claimed_by"] is None for cell in body["cells"])


def test_fetch_unknown_match_returns_404(client: TestClient) -> None:
    response = client.get("/matches/does-not-exist")

    assert response.status_code == 404


def test_matches_are_isolated_by_id(client: TestClient) -> None:
    first = client.post("/matches").json()
    second = client.post("/matches").json()

    assert first["id"] != second["id"]


def test_health_endpoint(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
