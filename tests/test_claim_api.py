"""Seam 1 - HTTP behaviour of claiming a Cell.

These run on a deterministic Grid: a module-scoped :class:`GameData` override of
six crafted Categories, forced onto every Match via ``category_ids`` so each
Cell's playable Characters are known exactly (see ``docs/agents/testing.md``).

Grid (rows x columns), each Category a 3-Character set:

              haki_arm            df_para             origin_gl
              L, Zoro, Robin      L, Robin, Brook     Nami, Franky, Brook
    race_a    (0,0) L, Zoro       (0,1) Luffy         (0,2) Nami
    L,Zoro,Nami
    race_b    (1,0) Robin         (1,1) Robin, Brook  (1,2) Franky, Brook
    Robin,Franky,Brook
    aff_crew  (2,0) Zoro, Robin   (2,1) Robin         (2,2) Nami
    Zoro,Nami,Robin
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
)


@pytest.fixture
def game_data() -> GameData:
    return crafted_game_data()


# --- claimed ---------------------------------------------------------


def test_correct_guess_claims_the_cell_adds_to_used_pool_and_passes_turn(
    client: TestClient,
) -> None:
    match_id, active = new_forced_match(client)

    body = post_guess(
        client, match_id, player=active, row=0, column=0, character="Zoro"
    )

    assert body["outcome"] == "claimed"
    assert body["row"] == "pass"
    assert body["column"] == "pass"

    match = body["match"]
    assert match["active_player"] == other_player(active)
    assert match["status"] == "in-progress"
    assert match["used_pool"] == ["Zoro"]
    claimed = next(
        c for c in match["grid"]["cells"] if c["row"] == 0 and c["column"] == 0
    )
    assert claimed["claimed_by"] == active
    assert claimed["character"] == "Zoro"


def test_claimed_state_survives_a_refetch(client: TestClient) -> None:
    match_id, active = new_forced_match(client)
    post_guess(client, match_id, player=active, row=0, column=0, character="Zoro")

    match = client.get(f"/matches/{match_id}").json()

    assert match["active_player"] == other_player(active)
    assert match["used_pool"] == ["Zoro"]
    claimed = next(
        c for c in match["grid"]["cells"] if c["row"] == 0 and c["column"] == 0
    )
    assert claimed["claimed_by"] == active
    assert claimed["character"] == "Zoro"


# --- wrong ---------------------------------------------------------


def test_wrong_guess_reports_per_axis_forfeits_turn_and_spares_the_character(
    client: TestClient,
) -> None:
    match_id, active = new_forced_match(client)

    # "Nami" is in race_a (row 0 passes) but not haki_arm (column 0 fails).
    body = post_guess(
        client, match_id, player=active, row=0, column=0, character="Nami"
    )

    assert body["outcome"] == "wrong"
    assert body["row"] == "pass"
    assert body["column"] == "fail"

    match = body["match"]
    assert match["active_player"] == other_player(active)
    assert match["used_pool"] == []
    assert all(
        c["claimed_by"] is None for c in match["grid"]["cells"]
    )


# --- already-used -------------------------------------------------


def test_naming_an_already_used_character_is_distinct_and_keeps_the_turn(
    client: TestClient,
) -> None:
    match_id, active = new_forced_match(client)
    post_guess(client, match_id, player=active, row=0, column=0, character="Zoro")
    second = other_player(active)

    # "Zoro" would legitimately fit Cell (2, 0) (aff_crew INTERSECT haki_arm),
    # but it is spent.
    body = post_guess(
        client, match_id, player=second, row=2, column=0, character="Zoro"
    )

    assert body["outcome"] == "already-used"
    assert body["row"] is None and body["column"] is None
    match = body["match"]
    assert match["active_player"] == second  # turn not forfeited
    assert match["used_pool"] == ["Zoro"]
    assert (
        next(
            c
            for c in match["grid"]["cells"]
            if c["row"] == 2 and c["column"] == 0
        )["claimed_by"]
        is None
    )


# --- rejected ----------------------------------------------------


def test_acting_out_of_turn_is_rejected_with_no_state_change(
    client: TestClient,
) -> None:
    match_id, active = new_forced_match(client)

    body = post_guess(
        client,
        match_id,
        player=other_player(active),
        row=0,
        column=0,
        character="Zoro",
    )

    assert body["outcome"] == "rejected"
    assert body["reason"] == "not-your-turn"
    match = body["match"]
    assert match["active_player"] == active
    assert all(c["claimed_by"] is None for c in match["grid"]["cells"])


def test_claiming_a_taken_cell_is_rejected(client: TestClient) -> None:
    match_id, active = new_forced_match(client)
    post_guess(client, match_id, player=active, row=0, column=0, character="Zoro")

    body = post_guess(
        client,
        match_id,
        player=other_player(active),
        row=0,
        column=0,
        character="Luffy",
    )

    assert body["outcome"] == "rejected"
    assert body["reason"] == "cell-taken"


def test_naming_a_character_absent_from_the_roster_is_rejected(
    client: TestClient,
) -> None:
    match_id, active = new_forced_match(client)

    body = post_guess(
        client, match_id, player=active, row=0, column=0, character="Shanks"
    )

    assert body["outcome"] == "rejected"
    assert body["reason"] == "unknown-character"


def test_guess_on_an_unknown_match_is_404(client: TestClient) -> None:
    response = client.post(
        "/matches/nope/guesses",
        json={"player": "P1", "row": 0, "column": 0, "character": "Zoro"},
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"player": "P1", "row": 3, "column": 0, "character": "Zoro"},
        {"player": "P1", "row": 0, "column": -1, "character": "Zoro"},
        {"player": "P3", "row": 0, "column": 0, "character": "Zoro"},
        {"player": "P1", "row": 0, "column": 0},
    ],
)
def test_malformed_guess_bodies_are_422(
    client: TestClient, payload: dict
) -> None:
    match_id, _ = new_forced_match(client)

    response = client.post(f"/matches/{match_id}/guesses", json=payload)

    assert response.status_code == 422


# --- win / draw + match-over lock (issue #6) --------------------------


def _play_row_0(
    client: TestClient, match_id: str, active: str, other: str
) -> dict:
    """Alternate turns until ``active`` holds all of row 0; return the response
    to the winning claim."""

    post_guess(client, match_id, player=active, row=0, column=0, character="Zoro")
    post_guess(client, match_id, player=other, row=1, column=2, character="Franky")
    post_guess(client, match_id, player=active, row=0, column=1, character="Luffy")
    post_guess(client, match_id, player=other, row=2, column=0, character="Robin")
    return post_guess(
        client, match_id, player=active, row=0, column=2, character="Nami"
    )


def test_completing_a_line_ends_the_match_and_names_the_winner(
    client: TestClient,
) -> None:
    match_id, active = new_forced_match(client)

    body = _play_row_0(client, match_id, active, other_player(active))

    assert body["outcome"] == "claimed"
    assert body["match"]["status"] == "won"
    assert body["match"]["winner"] == active


def test_no_guess_is_accepted_once_the_match_is_over(client: TestClient) -> None:
    match_id, active = new_forced_match(client)
    other = other_player(active)
    _play_row_0(client, match_id, active, other)

    # A move that would otherwise be legal - empty Cell, correct turn.
    body = post_guess(
        client, match_id, player=other, row=1, column=1, character="Brook"
    )

    assert body["outcome"] == "rejected"
    assert body["reason"] == "match-over"
    assert body["match"]["status"] == "won"


def test_a_completed_match_reports_its_result_on_refetch(
    client: TestClient,
) -> None:
    match_id, active = new_forced_match(client)
    _play_row_0(client, match_id, active, other_player(active))

    match = client.get(f"/matches/{match_id}").json()

    assert match["status"] == "won"
    assert match["winner"] == active
