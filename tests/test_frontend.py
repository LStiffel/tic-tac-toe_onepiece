"""Seam 1 - the single-screen frontend is served by the app (issue #9).

The frontend JS itself has no test harness - it is verified by the manual
browser check in ``docs/manual-checks/v1-frontend-grid-claim.md``. These tests
only guard that the static mount stays wired, so a broken asset path fails CI
rather than the browser.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_root_serves_the_frontend_html(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert '<div id="grid"' in body
    assert "/static/app.js" in body
    assert "/static/styles.css" in body


def test_frontend_static_assets_are_served(client: TestClient) -> None:
    for path, expected_type in (
        ("/static/app.js", "javascript"),
        ("/static/styles.css", "css"),
    ):
        response = client.get(path)

        assert response.status_code == 200, path
        assert expected_type in response.headers["content-type"], path
