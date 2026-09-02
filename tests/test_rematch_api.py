"""Seam 1 - HTTP behaviour of starting a Rematch (issue #8).

``POST /matches/{match_id}/rematch`` creates a brand-new Match off the back of a
finished (or any) one: a freshly generated Grid, an empty Used pool, a zeroed
consecutive-Pass counter, ``in-progress`` status and a randomly chosen first
player. The new Match gets its own id; the previous Match is left untouched.

The same crafted six-Category Grid as ``tests/test_claim_api.py`` is forced onto
both the source Match and the Rematch (shared helpers in ``tests/support.py``) so
every "does this Character fit this Cell" assertion is exact.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.dataset import GameData
from tests.support import (
    CRAFTED_CATEGORY_IDS,
    crafted_game_data,
    new_forced_match,
    other_player,
    post_guess,
    post_pass,
)

VALID_PLAYERS = {"P1", "P2"}


@pytest.fixture
def game_data() -> GameData:
    return crafted_game_data()


def _rematch(client: TestClient, match_id: str, **body: object) -> dict:
    response = client.post(
        f"/matches/{match_id}/rematch", json=body or None
    )
    assert response.status_code == 201, response.text
    return response.json()


# --- a fresh Match with a new id ------------------------------------


def test_rematch_returns_a_new_in_progress_match_with_its_own_id(
    client: TestClient,
) -> None:
    source_id, _ = new_forced_match(client)

    body = _rematch(client, source_id, category_ids=CRAFTED_CATEGORY_IDS)

    assert body["id"]
    assert body["id"] != source_id
    assert body["status"] == "in-progress"
    assert body["active_player"] in VALID_PLAYERS
    assert body["winner"] is None
    assert body["used_pool"] == []
    assert all(
        cell["claimed_by"] is None and cell["character"] is None
        for cell in body["grid"]["cells"]
    )


def test_the_rematch_is_stored_and_fetchable_under_its_new_id(
    client: TestClient,
) -> None:
    source_id, _ = new_forced_match(client)
    rematch_id = _rematch(client, source_id, category_ids=CRAFTED_CATEGORY_IDS)[
        "id"
    ]

    fetched = client.get(f"/matches/{rematch_id}")

    assert fetched.status_code == 200
    assert fetched.json()["id"] == rematch_id
    assert fetched.json()["status"] == "in-progress"


def test_the_previous_match_is_left_untouched_by_the_rematch(
    client: TestClient,
) -> None:
    source_id, active = new_forced_match(client)
    post_guess(
        client, source_id, player=active, row=0, column=0, character="Zoro"
    )

    _rematch(client, source_id, category_ids=CRAFTED_CATEGORY_IDS)

    source = client.get(f"/matches/{source_id}").json()
    assert source["used_pool"] == ["Zoro"]
    claimed = next(
        c for c in source["grid"]["cells"] if c["row"] == 0 and c["column"] == 0
    )
    assert claimed["claimed_by"] == active


# --- counters and Used pool reset ---------------------------------


def test_the_rematch_has_an_empty_used_pool(client: TestClient) -> None:
    source_id, active = new_forced_match(client)
    other = other_player(active)
    post_guess(
        client, source_id, player=active, row=0, column=0, character="Zoro"
    )
    post_guess(
        client, source_id, player=other, row=1, column=2, character="Franky"
    )

    body = _rematch(client, source_id, category_ids=CRAFTED_CATEGORY_IDS)

    assert body["used_pool"] == []


def test_the_consecutive_pass_counter_is_zeroed_in_the_rematch(
    client: TestClient,
) -> None:
    # One Pass in the source Match leaves its counter at 1. If that carried into
    # the Rematch, a single Pass there would immediately draw it.
    source_id, active = new_forced_match(client)
    post_pass(client, source_id, player=active)

    rematch_id = _rematch(client, source_id, category_ids=CRAFTED_CATEGORY_IDS)[
        "id"
    ]
    rematch_active = client.get(f"/matches/{rematch_id}").json()["active_player"]
    body = post_pass(client, rematch_id, player=rematch_active)

    assert body["outcome"] == "passed"
    assert body["match"]["status"] == "in-progress"


def test_a_character_used_in_the_previous_match_can_be_named_again(
    client: TestClient,
) -> None:
    source_id, active = new_forced_match(client)
    post_guess(
        client, source_id, player=active, row=0, column=0, character="Zoro"
    )

    rematch_id = _rematch(client, source_id, category_ids=CRAFTED_CATEGORY_IDS)[
        "id"
    ]
    rematch_active = client.get(f"/matches/{rematch_id}").json()["active_player"]
    body = post_guess(
        client,
        rematch_id,
        player=rematch_active,
        row=0,
        column=0,
        character="Zoro",
    )

    assert body["outcome"] == "claimed"
    assert body["match"]["used_pool"] == ["Zoro"]


# --- a fresh first player, a fresh Grid --------------------------


def test_the_first_player_is_chosen_at_random_not_carried_over(
    client: TestClient,
) -> None:
    source_id, _ = new_forced_match(client)

    first_players = {
        _rematch(client, source_id, category_ids=CRAFTED_CATEGORY_IDS)[
            "active_player"
        ]
        for _ in range(40)
    }

    assert first_players == VALID_PLAYERS


def test_a_seeded_rematch_grid_matches_a_fresh_seeded_generation(
    client: TestClient,
) -> None:
    # The Rematch Grid is produced the very same way a fresh Match's is, so under
    # a shared seed the two Grids are identical - "distinct only by chance".
    source_id, _ = new_forced_match(client)

    fresh = client.post("/matches", json={"seed": 987654}).json()
    rematch = _rematch(client, source_id, seed=987654)

    assert rematch["grid"] == fresh["grid"]


# --- rejected ----------------------------------------------------


def test_rematch_of_an_unknown_match_is_404(client: TestClient) -> None:
    response = client.post("/matches/does-not-exist/rematch")

    assert response.status_code == 404


def test_rematch_onto_an_invalid_forced_grid_is_422(
    client: TestClient,
) -> None:
    source_id, _ = new_forced_match(client)
    # Five ids where a Grid needs six.
    forced_ids = CRAFTED_CATEGORY_IDS[:-1]

    response = client.post(
        f"/matches/{source_id}/rematch", json={"category_ids": forced_ids}
    )

    assert response.status_code == 422
