"""Seam 1 - the single-screen frontend is served by the app (issues #9, #10).

The frontend JS itself has no test harness - it is verified by the manual
browser checks in ``docs/manual-checks/v1-frontend-grid-claim.md`` (issue #9)
and ``docs/manual-checks/v1-frontend-complete-match.md`` (issue #10). These
tests only guard that the static mount stays wired and that the ids the script
binds to are present, so a broken asset path or a rename fails CI rather than
the browser.
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


def test_frontend_html_carries_the_issue_10_binding_points(
    client: TestClient,
) -> None:
    """The issue #10 script binds by id to the banner, the Pass and Rematch
    buttons, the Used-pool list and the Character-art figure. Guard those ids so
    a rename in ``index.html`` fails here rather than silently in the browser."""

    body = client.get("/").text

    for hook in (
        'id="banner"',
        'id="pass-btn"',
        'id="rematch-btn"',
        'id="used-pool-list"',
        'id="art"',
    ):
        assert hook in body, hook


def test_frontend_static_assets_are_served(client: TestClient) -> None:
    for path, expected_type in (
        ("/static/app.js", "javascript"),
        ("/static/styles.css", "css"),
    ):
        response = client.get(path)

        assert response.status_code == 200, path
        assert expected_type in response.headers["content-type"], path


def test_frontend_assets_send_no_cache(client: TestClient) -> None:
    """Issue #13: a browser holding an earlier screen kept running a stale
    ``app.js`` with no Pass / Rematch wiring. ``GET /`` and every ``/static``
    asset send ``Cache-Control: no-cache`` so the browser rechecks each load."""

    for path in ("/", "/static/app.js", "/static/styles.css"):
        response = client.get(path)

        assert response.headers.get("cache-control") == "no-cache", path


def test_frontend_static_assets_still_answer_304_when_unchanged(
    client: TestClient,
) -> None:
    """``no-cache`` is revalidate, not refetch: with the ETag Starlette sends,
    an unchanged ``/static`` asset is a cheap conditional 304 that still
    carries the header."""

    first = client.get("/static/app.js")
    revalidated = client.get(
        "/static/app.js", headers={"If-None-Match": first.headers["etag"]}
    )

    assert revalidated.status_code == 304
    assert revalidated.headers.get("cache-control") == "no-cache"
