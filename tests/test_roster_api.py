"""Seam 1 - HTTP behaviour of the dataset surface: ``/roster`` and the
data-quality diagnostic. The app is built on a tiny crafted dataset (the
``game_data`` fixture below overrides the one in ``conftest.py``) so the
responses are exact."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.dataset import GameData
from app.main import create_app
from app.storage import InMemoryMatchStore

CHARACTERS = [
    {"name": "Monkey D. Luffy"},
    {"name": "Roronoa Zoro"},
    {"name": "Nami"},
    {"name": "Usopp"},
    {"name": "Bjorn"},
    {"name": "Bjorn "},  # collapses onto "Bjorn"
]

CATEGORIES = [
    {
        "id": "aff_Straw Hat Pirates",
        "label": "Affiliation: Straw Hat Pirates",
        "count": 5,
        "characters": ["Monkey D. Luffy", "Roronoa Zoro", "Nami", "Usopp", "Ghost"],
    },
    {
        "id": "aff_Tiny Crew",
        "label": "Affiliation: Tiny Crew",
        "count": 3,
        "characters": ["Monkey D. Luffy", "Missing A", "Missing B"],
    },
]


@pytest.fixture
def game_data() -> GameData:
    return GameData.from_raw(CHARACTERS, CATEGORIES)


def test_roster_is_a_flat_sorted_list_of_canonical_names(client: TestClient) -> None:
    response = client.get("/roster")

    assert response.status_code == 200
    assert response.json() == [
        "Bjorn",
        "Monkey D. Luffy",
        "Nami",
        "Roronoa Zoro",
        "Usopp",
    ]


def test_roster_does_not_expose_the_category_answer_key(client: TestClient) -> None:
    body = client.get("/roster").text

    # No Category id, label, or the Category-to-Characters mapping.
    assert "aff_Straw Hat Pirates" not in body
    assert "Affiliation" not in body
    assert "characters" not in body
    assert "count" not in body


def test_data_quality_endpoint_reports_unresolved_names_and_exclusions(
    client: TestClient,
) -> None:
    response = client.get("/diagnostics/data-quality")

    assert response.status_code == 200
    assert response.json() == {
        "unresolved": {
            "aff_Straw Hat Pirates": ["Ghost"],
            "aff_Tiny Crew": ["Missing A", "Missing B"],
        },
        "excluded_categories": ["aff_Tiny Crew"],
        "unresolved_name_count": 3,
    }


def test_data_quality_report_is_logged_when_the_app_starts(
    game_data: GameData, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.dataset"):
        # Entering the TestClient context runs the app's startup (lifespan) hook.
        with TestClient(create_app(InMemoryMatchStore(), game_data)):
            pass

    messages = "\n".join(record.message for record in caplog.records)
    assert "Dataset loaded" in messages
    assert "aff_Tiny Crew" in messages
