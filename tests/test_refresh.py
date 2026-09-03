"""Seam 2 - the Refresh fetch + orchestrate step, no real HTTP (issue #23).

The three-URL fetch and the ``refresh.yml`` cron / PR wiring are not unit-tested
(ADR 0004: verified once by hand, ``docs/manual-checks/dataset-refresh-workflow.md``).
What is worth pinning lives here: the pure text helpers (provenance, changelog
excerpt, findings formatting) and the one behaviour with teeth - a failed
Upstream shape check must leave the vendored Raw dataset untouched.

The fetcher is injectable, so every test passes its own: either a canned
byte-string or a URL-dispatching stub that serves the committed repo files.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import refresh as rf
from scripts.refresh import (
    Provenance,
    RefreshOutcome,
    build_pr_body,
    changelog_entries_since,
    format_findings_by_severity,
    latest_changelog_heading,
    parse_changelog_version,
    read_previous_changelog_heading,
    render_provenance,
)
from scripts.validate_dataset import Finding, Severity, exit_code

REPO_ROOT = Path(__file__).resolve().parent.parent

_CHANGELOG_JS = """\
const CHANGELOG_VERSION = '3.41';
function setupChangelogModal() {
    const modalHTML = `
    <h3>v3.2 - Episode 1176 - 30/08/26</h3>
    <ul>
        <li>Updated images for <strong>Achao</strong></li>
        <li>Added the <strong>Killkhan</strong> entry</li>
    </ul>
    <h3>v3.2 - Episode 1175 - 23/08/26</h3>
    <ul>
        <li>Updated image for <strong>Aro Aro No Mi</strong></li>
    </ul>
    <h3>v3.2 - Episode 1173 - 09/08/26</h3>
    <ul>
        <li>Added <strong>Jericho</strong> and <strong>Hogan</strong></li>
    </ul>
    `;
}
"""


# --- changelog helpers ---------------------------------------------------


def test_parse_changelog_version_reads_the_constant() -> None:
    assert parse_changelog_version(_CHANGELOG_JS) == "3.41"


def test_parse_changelog_version_is_none_when_absent() -> None:
    assert parse_changelog_version("no version constant here") is None


def test_latest_changelog_heading_is_the_newest_entry() -> None:
    assert latest_changelog_heading(_CHANGELOG_JS) == "v3.2 - Episode 1176 - 30/08/26"


def test_changelog_entries_since_stops_at_the_recorded_heading() -> None:
    markdown = changelog_entries_since(
        _CHANGELOG_JS, since_heading="v3.2 - Episode 1175 - 23/08/26"
    )

    # Only the one entry newer than the recorded heading, with its items.
    assert "### v3.2 - Episode 1176 - 30/08/26" in markdown
    assert "- Added the Killkhan entry" in markdown
    assert "Episode 1175" not in markdown
    assert "Episode 1173" not in markdown


def test_changelog_entries_since_falls_back_to_newest_when_heading_missing() -> None:
    markdown = changelog_entries_since(
        _CHANGELOG_JS, since_heading="v9.9 - never happened", max_entries=1
    )

    assert markdown.count("### ") == 1
    assert "Episode 1176" in markdown


def test_changelog_entries_since_reports_nothing_new() -> None:
    markdown = changelog_entries_since(
        _CHANGELOG_JS, since_heading="v3.2 - Episode 1176 - 30/08/26"
    )

    assert "No new Upstream changelog entries" in markdown


# --- provenance rendering ---------------------------------------------------


def _provenance(**overrides: object) -> Provenance:
    base: dict[str, object] = dict(
        fetched_at=datetime(2026, 9, 3, 6, 5, 0, tzinfo=timezone.utc),
        changelog_version="3.41",
        latest_changelog_heading="v3.2 - Episode 1176 - 30/08/26",
        entry_counts={
            "characters.json": 1550,
            "devil_fruits.json": 214,
            "islands.json": 164,
            "categories.json": 195,
        },
    )
    base.update(overrides)
    return Provenance(**base)  # type: ignore[arg-type]


def test_render_provenance_lists_sources_counts_and_version() -> None:
    text = render_provenance(_provenance())

    assert "<https://oparchive.com/data/characters.json>" in text
    assert "<https://oparchive.com/data/islands.json>" in text
    assert "**Fetched (UTC):** 2026-09-03T06:05:00Z" in text
    assert "**Upstream `CHANGELOG_VERSION`:** 3.41" in text
    assert "Latest Upstream changelog entry:** v3.2 - Episode 1176 - 30/08/26" in text
    assert "| `characters.json` | 1550 |" in text
    assert "| `categories.json` | 195 |" in text
    assert "docs/adr/0004-dataset-refresh-pipeline.md" in text


def test_render_provenance_says_unknown_when_the_version_is_missing() -> None:
    text = render_provenance(
        _provenance(changelog_version=None, latest_changelog_heading=None)
    )

    assert "**Upstream `CHANGELOG_VERSION`:** unknown" in text
    assert "Latest Upstream changelog entry:** unknown" in text


# --- findings formatting -------------------------------------------------


def test_format_findings_by_severity_groups_under_headings() -> None:
    findings = [
        Finding(Severity.INFO, "characters-added", "3 Characters added"),
        Finding(Severity.BLOCK, "grid-smoke-test", "thin pool"),
        Finding(Severity.REVIEW, "dead-category-count-moved", "11 -> 13"),
    ]

    text = format_findings_by_severity(findings)

    assert text.index("### BLOCK") < text.index("### REVIEW") < text.index("### INFO")
    assert "- thin pool" in text
    assert "- 11 -> 13" in text
    assert "- 3 Characters added" in text


def test_format_findings_by_severity_handles_an_empty_list() -> None:
    assert "No findings" in format_findings_by_severity([])


def _outcome(**overrides: object) -> RefreshOutcome:
    base: dict[str, object] = dict(
        raw_written=True,
        findings=[Finding(Severity.INFO, "characters-added", "3 Characters added")],
        provenance_text="# Data provenance\n\ncounts here",
        changelog_markdown="### v3.2 - Episode 1176\n- Added Killkhan",
    )
    base.update(overrides)
    return RefreshOutcome(**base)  # type: ignore[arg-type]


def test_build_pr_body_carries_changelog_findings_and_provenance_pointer() -> None:
    body = build_pr_body(_outcome())

    assert "## Upstream changelog since the last Refresh" in body
    assert "Added Killkhan" in body
    assert "## Validator findings" in body
    assert "3 Characters added" in body
    assert "`data/PROVENANCE.md` is regenerated in this PR." in body
    assert "green CI is enough to merge" in body
    assert "Reviewer checklist" not in body


def test_build_pr_body_adds_the_checklist_when_a_review_finding_fired() -> None:
    body = build_pr_body(
        _outcome(
            findings=[Finding(Severity.REVIEW, "dead-category-count-moved", "11 -> 13")]
        )
    )

    assert "needs-review" in body
    assert "## Reviewer checklist" in body


# --- outcome flags -----------------------------------------------------


def test_outcome_blocked_when_write_was_gated() -> None:
    outcome = RefreshOutcome(
        raw_written=False, findings=[], provenance_text="", changelog_markdown=""
    )

    assert outcome.blocked is True
    assert outcome.has_review is False


def test_outcome_blocked_and_review_track_the_findings() -> None:
    outcome = RefreshOutcome(
        raw_written=True,
        findings=[
            Finding(Severity.BLOCK, "grid-smoke-test", "x"),
            Finding(Severity.REVIEW, "trivial-set-changed", "y"),
        ],
        provenance_text="",
        changelog_markdown="",
    )

    assert outcome.blocked is True
    assert outcome.has_review is True


# --- orchestration ------------------------------------------------------


def _repo_bytes(stem: str) -> bytes:
    return (REPO_ROOT / f"{stem}.json").read_bytes()


def _fetcher_serving_repo_files(
    *, characters: bytes | None = None
) -> Callable[[str], bytes]:
    """A fetcher that answers the data URLs from the committed repo files (or a
    supplied override) and the changelog URL from the fixture JS."""

    def fetch(url: str) -> bytes:
        if url == rf.CHANGELOG_URL:
            return _CHANGELOG_JS.encode("utf-8")
        stem = url.rsplit("/", 1)[-1].removesuffix(".json")
        if stem == "characters" and characters is not None:
            return characters
        return _repo_bytes(stem)

    return fetch


def test_refresh_gates_the_write_on_the_upstream_shape_check(tmp_path: Path) -> None:
    # characters.json arrives as an object, not the expected array.
    fetcher = _fetcher_serving_repo_files(characters=b'{"not": "an array"}')

    outcome = rf.refresh(fetcher=fetcher, root=tmp_path)

    assert outcome.raw_written is False
    assert outcome.blocked is True
    assert {f.trigger for f in outcome.findings} == {"upstream-shape"}
    # The fetched bytes were NOT written over the vendored copy.
    assert not (tmp_path / "characters.json").exists()
    assert not (tmp_path / "categories.json").exists()
    assert not (tmp_path / "data" / "PROVENANCE.md").exists()


def test_refresh_writes_rebuilds_and_validates_a_clean_candidate(
    tmp_path: Path,
) -> None:
    outcome = rf.refresh(
        fetcher=_fetcher_serving_repo_files(),
        root=tmp_path,
        now=datetime(2026, 9, 3, 6, 0, 0, tzinfo=timezone.utc),
    )

    assert outcome.raw_written is True
    # Candidate == the committed dataset, so nothing is BLOCK.
    assert exit_code(outcome.findings) == 0
    assert outcome.blocked is False

    for name in ("characters.json", "devil_fruits.json", "islands.json",
                 "categories.json", "categories.txt"):
        assert (tmp_path / name).read_bytes(), f"{name} not written"
    provenance = (tmp_path / "data" / "PROVENANCE.md").read_text(encoding="utf-8")
    assert "**Upstream `CHANGELOG_VERSION`:** 3.41" in provenance
    assert "**Fetched (UTC):** 2026-09-03T06:00:00Z" in provenance

    # The rebuilt categories.json is the builder's canonical (LF) form.
    assert b"\r\n" not in (tmp_path / "categories.json").read_bytes()


def test_refresh_writes_the_raw_dataset_verbatim(tmp_path: Path) -> None:
    outcome = rf.refresh(fetcher=_fetcher_serving_repo_files(), root=tmp_path)

    assert outcome.raw_written is True
    for stem in ("characters", "devil_fruits", "islands"):
        assert (tmp_path / f"{stem}.json").read_bytes() == _repo_bytes(stem)


def test_refresh_raises_refresh_error_on_a_fetch_failure(tmp_path: Path) -> None:
    def boom(url: str) -> bytes:
        raise rf.RefreshError(f"fetch failed for {url}: boom")

    with pytest.raises(rf.RefreshError):
        rf.refresh(fetcher=boom, root=tmp_path)


def test_refresh_reads_the_previous_changelog_heading_before_overwriting_it(
    tmp_path: Path,
) -> None:
    # A prior Refresh left a PROVENANCE.md whose recorded heading is two entries
    # behind the fixture changelog's newest.
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "PROVENANCE.md").write_text(
        render_provenance(_provenance(
            latest_changelog_heading="v3.2 - Episode 1173 - 09/08/26"
        )),
        encoding="utf-8",
    )

    outcome = rf.refresh(fetcher=_fetcher_serving_repo_files(), root=tmp_path)

    # The excerpt is the two entries Upstream added since — not "nothing new",
    # which is what a read-after-write bug produces.
    assert "### v3.2 - Episode 1176 - 30/08/26" in outcome.changelog_markdown
    assert "### v3.2 - Episode 1175 - 23/08/26" in outcome.changelog_markdown
    assert "Episode 1173" not in outcome.changelog_markdown
    assert "No new Upstream changelog entries" not in outcome.changelog_markdown
    # ...and PROVENANCE.md now records the new newest heading.
    assert read_previous_changelog_heading(tmp_path) == "v3.2 - Episode 1176 - 30/08/26"


def test_main_returns_one_when_the_shape_check_gates_the_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gated = RefreshOutcome(
        raw_written=False,
        findings=[Finding(Severity.BLOCK, "upstream-shape", "characters.json: ...")],
        provenance_text="",
        changelog_markdown="",
    )
    monkeypatch.setattr(rf, "refresh", lambda **_: gated)

    assert rf.main([]) == 1


def test_main_returns_zero_on_a_clean_run(monkeypatch: pytest.MonkeyPatch) -> None:
    clean = RefreshOutcome(
        raw_written=True,
        findings=[Finding(Severity.INFO, "characters-added", "1 added")],
        provenance_text="# Data provenance\n",
        changelog_markdown="_nothing_",
    )
    monkeypatch.setattr(rf, "refresh", lambda **_: clean)

    assert rf.main([]) == 0
