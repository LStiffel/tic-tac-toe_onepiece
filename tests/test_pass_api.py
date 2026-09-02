"""Seam 1 - HTTP behaviour of Passing a turn.

Same deterministic crafted Grid as ``tests/test_claim_api.py``: six crafted
Categories forced onto every Match via ``category_ids`` (shared helpers live in
``tests/support.py``). A stuck Active player can Pass, and two Passes in
immediate succession end the Match as a draw (issue #7).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.dataset import GameData
from tests.support import (
    crafted_game_data,
    new_forced_match,
    other_player,
    post_guess,
    post_pass,
)


@pytest.fixture
def game_data() -> GameData:
    return crafted_game_data()


# --- a single Pass ---------------------------------------------------


def test_a_single_pass_passes_the_turn(client: TestClient) -> None:
    match_id, active = new_forced_match(client)

    body = post_pass(client, match_id, player=active)

    assert body["outcome"] == "passed"
    assert body["reason"] is None
    match = body["match"]
    assert match["active_player"] == other_player(active)
    assert match["status"] == "in-progress"


def test_the_passed_turn_survives_a_refetch(client: TestClient) -> None:
    match_id, active = new_forced_match(client)
    post_pass(client, match_id, player=active)

    match = client.get(f"/matches/{match_id}").json()

    assert match["active_player"] == other_player(active)
    assert match["status"] == "in-progress"


# --- double Pass -> draw ------------------------------------------


def test_two_passes_in_immediate_succession_end_the_match_as_a_draw(
    client: TestClient,
) -> None:
    match_id, active = new_forced_match(client)
    post_pass(client, match_id, player=active)

    body = post_pass(client, match_id, player=other_player(active))

    assert body["outcome"] == "passed"
    assert body["match"]["status"] == "draw"
    assert body["match"]["winner"] is None


def test_the_draw_from_a_double_pass_survives_a_refetch(
    client: TestClient,
) -> None:
    match_id, active = new_forced_match(client)
    post_pass(client, match_id, player=active)
    post_pass(client, match_id, player=other_player(active))

    match = client.get(f"/matches/{match_id}").json()

    assert match["status"] == "draw"
    assert match["winner"] is None


# --- a claim / wrong guess between two Passes resets the counter ----


def test_a_claim_between_two_passes_keeps_the_next_pass_from_drawing(
    client: TestClient,
) -> None:
    match_id, active = new_forced_match(client)
    other = other_player(active)
    post_pass(client, match_id, player=active)
    post_guess(client, match_id, player=other, row=0, column=0, character="Zoro")

    body = post_pass(client, match_id, player=active)

    assert body["outcome"] == "passed"
    assert body["match"]["status"] == "in-progress"


def test_a_wrong_guess_between_two_passes_keeps_the_next_pass_from_drawing(
    client: TestClient,
) -> None:
    match_id, active = new_forced_match(client)
    other = other_player(active)
    post_pass(client, match_id, player=active)
    # "Nami" is in race_a (row 0) but not haki_arm (column 0) - a wrong guess.
    post_guess(client, match_id, player=other, row=0, column=0, character="Nami")

    body = post_pass(client, match_id, player=active)

    assert body["outcome"] == "passed"
    assert body["match"]["status"] == "in-progress"


# --- rejected ------------------------------------------------------


def test_a_pass_out_of_turn_is_rejected_with_no_state_change(
    client: TestClient,
) -> None:
    match_id, active = new_forced_match(client)

    body = post_pass(client, match_id, player=other_player(active))

    assert body["outcome"] == "rejected"
    assert body["reason"] == "not-your-turn"
    match = body["match"]
    assert match["active_player"] == active
    assert match["status"] == "in-progress"


def test_a_pass_on_a_finished_match_is_rejected(client: TestClient) -> None:
    match_id, active = new_forced_match(client)
    other = other_player(active)
    post_pass(client, match_id, player=active)
    post_pass(client, match_id, player=other)  # draw

    body = post_pass(client, match_id, player=active)

    assert body["outcome"] == "rejected"
    assert body["reason"] == "match-over"
    assert body["match"]["status"] == "draw"


def test_pass_on_an_unknown_match_is_404(client: TestClient) -> None:
    response = client.post("/matches/nope/passes", json={"player": "P1"})

    assert response.status_code == 404


@pytest.mark.parametrize("payload", [{}, {"player": "P3"}, {"player": None}])
def test_malformed_pass_bodies_are_422(
    client: TestClient, payload: dict
) -> None:
    match_id, _ = new_forced_match(client)

    response = client.post(f"/matches/{match_id}/passes", json=payload)

    assert response.status_code == 422
