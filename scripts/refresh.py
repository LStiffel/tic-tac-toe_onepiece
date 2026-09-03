"""Fetch the Raw dataset from Upstream and orchestrate a Refresh (ADR 0004).

A **Refresh** re-pulls ``characters.json`` / ``devil_fruits.json`` /
``islands.json`` from **Upstream** (oparchive.com), rebuilds the derived files,
regenerates ``data/PROVENANCE.md``, and runs the validator. This module is the
fetch + orchestrate step; the weekly ``.github/workflows/refresh.yml`` runs it
and opens the rolling ``data-refresh`` pull request when the dataset changed.

The pieces, so each can be reasoned about on its own:

* :func:`http_fetch` - the default fetcher, one plain HTTPS GET. Every entry
  point takes a ``fetcher`` argument so a test (or a caller behind a proxy) can
  swap it out; there is no other network access in here.
* :func:`refresh` - the orchestration. Fetch -> Upstream **shape check** -> (only
  if the shape holds) write the Raw dataset -> rebuild ``categories.json`` /
  ``categories.txt`` -> regenerate ``data/PROVENANCE.md`` -> validate against
  ``HEAD``. On a shape BLOCK the fetched bytes are **not** written over the
  vendored copy and :attr:`RefreshOutcome.raw_written` is ``False``.
* :func:`render_provenance` / :func:`parse_changelog_version` /
  :func:`latest_changelog_heading` / :func:`changelog_entries_since` /
  :func:`format_findings_by_severity` - pure text helpers the workflow and the
  ``__main__`` entry share. These are the parts worth unit-testing; the
  three-URL fetch and the cron / PR wiring are verified once by hand
  (``docs/manual-checks/dataset-refresh-workflow.md``).

Run ``python -m scripts.refresh`` to do a full Refresh in place, or
``python -m scripts.refresh --provenance-only`` to just regenerate
``data/PROVENANCE.md`` from the files already on disk. Both exit non-zero iff the
fetch failed or the validator reported a BLOCK finding.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.dataset import GameData
from scripts import validate_dataset as vd
from scripts.build_categories import (
    build_categories,
    dump_categories_json,
    dump_categories_txt,
)
from scripts.validate_dataset import Finding, RawDataset, Severity

# Repo root: this file is ``<root>/scripts/refresh.py``.
REPO_ROOT = Path(__file__).resolve().parent.parent

#: Upstream serves the three files as plain static JSON under this path, and the
#: dated changelog as a JS file carrying ``CHANGELOG_VERSION`` (CONTEXT.md:
#: "Upstream"). No API, no auth.
UPSTREAM_ORIGIN = "https://oparchive.com"
DATA_URL = f"{UPSTREAM_ORIGIN}/data"
CHANGELOG_URL = f"{UPSTREAM_ORIGIN}/scripts/changelog.js"

#: The Raw dataset file stems, in the order they appear everywhere (counts
#: table, shape check, provenance).
RAW_STEMS: tuple[str, ...] = ("characters", "devil_fruits", "islands")

#: A fetcher maps an absolute URL to the response body. :func:`http_fetch` is the
#: default; a test passes its own.
Fetcher = Callable[[str], bytes]

_HTTP_TIMEOUT_SECONDS = 30


class RefreshError(RuntimeError):
    """A Refresh could not even be attempted - a fetch failed, or Upstream
    served something that is not JSON. Distinct from a validator BLOCK, which is
    a finding on a dataset that did parse."""


def http_fetch(url: str) -> bytes:
    """GET ``url`` and return the raw body. The default :data:`Fetcher`.

    Raises :class:`RefreshError` on any transport or HTTP error so the caller
    fails the run with one exception type.
    """

    request = urllib.request.Request(
        url, headers={"User-Agent": "tic-tac-toe-onepiece-refresh"}
    )
    try:
        with urllib.request.urlopen(
            request, timeout=_HTTP_TIMEOUT_SECONDS
        ) as response:
            body: bytes = response.read()
    except OSError as exc:  # URLError, HTTPError, socket timeout
        raise RefreshError(f"fetch failed for {url}: {exc}") from exc
    return body


# --- fetch -------------------------------------------------------------------


def fetch_raw_dataset(fetcher: Fetcher) -> dict[str, bytes]:
    """The three Raw dataset files as ``stem -> raw bytes``, fetched verbatim.

    The bytes are written to the repo unchanged (ADR 0004: the Raw dataset is
    vendored "verbatim"), so nothing is re-serialised here.
    """

    return {stem: fetcher(f"{DATA_URL}/{stem}.json") for stem in RAW_STEMS}


def _parse(stem: str, body: bytes) -> Any:
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RefreshError(
            f"{stem}.json from Upstream is not valid JSON: {exc}"
        ) from exc


# --- changelog helpers -----------------------------------------------------

_CHANGELOG_VERSION_RE = re.compile(r"CHANGELOG_VERSION\s*=\s*['\"]([^'\"]+)['\"]")
_CHANGELOG_ENTRY_RE = re.compile(
    r"<h3>(?P<heading>.*?)</h3>\s*<ul>(?P<body>.*?)</ul>", re.DOTALL
)
_LI_RE = re.compile(r"<li>(.*?)</li>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def parse_changelog_version(changelog_js: str) -> str | None:
    """The ``CHANGELOG_VERSION`` string constant from Upstream's
    ``scripts/changelog.js``, or ``None`` if it is not there (Upstream changed
    the file's shape - provenance then records "unknown", not a crash)."""

    match = _CHANGELOG_VERSION_RE.search(changelog_js)
    return match.group(1) if match else None


def _strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub("", html)).strip()


def latest_changelog_heading(changelog_js: str) -> str | None:
    """The text of the newest ``<h3>`` changelog heading (entries are newest
    first), e.g. ``"v3.2 - Episode 1176 - 30/08/26"``. ``None`` if there are no
    entries. Recorded in provenance so the next Refresh can list what is new."""

    match = _CHANGELOG_ENTRY_RE.search(changelog_js)
    return _strip_tags(match.group("heading")) if match else None


def changelog_entries_since(
    changelog_js: str, since_heading: str | None, *, max_entries: int = 20
) -> str:
    """The Upstream changelog entries newer than ``since_heading``, as Markdown
    (`### heading` then `- item` lines).

    ``CHANGELOG_VERSION`` does not tag individual entries, so "since the last
    Refresh" keys on the heading text provenance stored last time. If
    ``since_heading`` is ``None`` or is not found (Upstream rewrote history), the
    newest ``max_entries`` entries are returned instead. Best-effort text for the
    PR body - not a parsed contract.
    """

    blocks: list[str] = []
    for match in _CHANGELOG_ENTRY_RE.finditer(changelog_js):
        heading = _strip_tags(match.group("heading"))
        if since_heading is not None and heading == since_heading:
            break
        items = [_strip_tags(item) for item in _LI_RE.findall(match.group("body"))]
        blocks.append(
            "\n".join([f"### {heading}", *(f"- {item}" for item in items if item)])
        )
        if len(blocks) >= max_entries:
            break
    if not blocks:
        return "_No new Upstream changelog entries since the last Refresh._"
    return "\n\n".join(blocks)


# --- provenance ------------------------------------------------------------


@dataclass(frozen=True)
class Provenance:
    """What ``data/PROVENANCE.md`` records about the current vendored copy."""

    fetched_at: datetime
    changelog_version: str | None
    latest_changelog_heading: str | None
    #: ``"characters.json"`` etc. -> entry count, plus ``"categories.json"`` for
    #: the derived file.
    entry_counts: dict[str, int]


#: The label on the provenance line that records the newest Upstream changelog
#: heading. :func:`render_provenance` emits it and
#: :func:`read_previous_changelog_heading` parses it back, so it lives in one
#: place.
_CHANGELOG_HEADING_LABEL = "Latest Upstream changelog entry:"
_CHANGELOG_HEADING_RE = re.compile(
    re.escape(_CHANGELOG_HEADING_LABEL) + r"\*\*\s*(.+)"
)


def render_provenance(provenance: Provenance) -> str:
    """``data/PROVENANCE.md`` for ``provenance``. Pure; the only place the file's
    text is defined."""

    fetched = provenance.fetched_at.astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    version = provenance.changelog_version or "unknown"
    heading = provenance.latest_changelog_heading or "unknown"

    source_rows = "\n".join(
        f"| `{stem}.json` | <{DATA_URL}/{stem}.json> |" for stem in RAW_STEMS
    )
    count_rows = "\n".join(
        f"| `{name}` | {provenance.entry_counts[name]} |"
        for name in (*(f"{stem}.json" for stem in RAW_STEMS), "categories.json")
        if name in provenance.entry_counts
    )

    return f"""\
# Data provenance

The **Raw dataset** (`characters.json`, `devil_fruits.json`, `islands.json`) is
vendored from **Upstream** - [oparchive.com]({UPSTREAM_ORIGIN}), a fan project
that publishes the One Piece archive as static JSON with no API and no stated
licence. `categories.json` / `categories.txt` are derived from it by
`scripts/build_categories.py`. See
`docs/adr/0004-dataset-refresh-pipeline.md` for how a Refresh works.

This file is regenerated by `scripts/refresh.py` on every Refresh - do not edit
it by hand.

## Source

| File | URL |
| --- | --- |
{source_rows}

## Last fetch

- **Fetched (UTC):** {fetched}
- **Upstream `CHANGELOG_VERSION`:** {version}
- **{_CHANGELOG_HEADING_LABEL}** {heading}

## Entry counts

| File | Entries |
| --- | --- |
{count_rows}
"""


def provenance_path(root: Path) -> Path:
    return root / "data" / "PROVENANCE.md"


def read_previous_changelog_heading(root: Path) -> str | None:
    """The newest-changelog-heading recorded by the *last* Refresh, read from the
    ``data/PROVENANCE.md`` under ``root`` **before** this run overwrites it.
    ``None`` on the first Refresh or when the line is absent - then
    :func:`changelog_entries_since` falls back to the newest entries."""

    try:
        text = provenance_path(root).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    match = _CHANGELOG_HEADING_RE.search(text)
    if match is None:
        return None
    value = match.group(1).strip()
    return None if value in {"", "unknown"} else value


def write_provenance(
    root: Path, *, changelog_js: str, entry_counts: dict[str, int], fetched_at: datetime
) -> str:
    """Render ``data/PROVENANCE.md`` under ``root`` and write it (LF, trailing
    newline). Returns the text. The single writer, shared by :func:`refresh` and
    the ``--provenance-only`` path."""

    text = render_provenance(
        Provenance(
            fetched_at=fetched_at,
            changelog_version=parse_changelog_version(changelog_js),
            latest_changelog_heading=latest_changelog_heading(changelog_js),
            entry_counts=entry_counts,
        )
    )
    path = provenance_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return text


# --- orchestration -------------------------------------------------------


@dataclass(frozen=True)
class RefreshOutcome:
    """The result of :func:`refresh`.

    ``raw_written`` is ``False`` only when the Upstream shape check blocked the
    write; ``findings`` then holds just the shape BLOCK(s). ``provenance_text``
    and ``changelog_markdown`` are populated on a successful write for the PR
    body.
    """

    raw_written: bool
    findings: list[Finding]
    provenance_text: str
    changelog_markdown: str

    @property
    def blocked(self) -> bool:
        """Whether the run must fail: the write was gated, or a finding is
        BLOCK."""

        return not self.raw_written or any(
            f.severity is Severity.BLOCK for f in self.findings
        )

    @property
    def has_review(self) -> bool:
        """Whether any finding is REVIEW - the workflow adds ``needs-review``."""

        return any(f.severity is Severity.REVIEW for f in self.findings)


def refresh(
    *,
    fetcher: Fetcher = http_fetch,
    root: Path = REPO_ROOT,
    now: datetime | None = None,
) -> RefreshOutcome:
    """Do a Refresh: fetch, shape-check, (conditionally) write, rebuild,
    regenerate provenance, validate.

    ``root`` is where the files are written (the repo by default; a temp dir in
    tests). The validator baseline is always the real repo's ``HEAD``. No pull
    request, no ``git`` writes, no knob edits happen here.
    """

    fetched_at = now or datetime.now(timezone.utc)
    raw_bytes = fetch_raw_dataset(fetcher)
    parsed = {stem: _parse(stem, raw_bytes[stem]) for stem in RAW_STEMS}

    # Upstream shape check FIRST: a BLOCK here means Upstream drifted, and the
    # fetched bytes must not land on top of the vendored copy (ADR 0004).
    shape = vd.check_upstream_shape(
        RawDataset(
            characters=parsed["characters"],
            categories=None,
            devil_fruits=parsed["devil_fruits"],
            islands=parsed["islands"],
        )
    )
    if any(f.severity is Severity.BLOCK for f in shape):
        # ``check_upstream_shape`` only ever emits BLOCK findings, so no ordering
        # is needed.
        return RefreshOutcome(
            raw_written=False,
            findings=list(shape),
            provenance_text="",
            changelog_markdown="",
        )

    # The shape holds: vendor the Raw dataset verbatim, then rebuild the derived
    # files from it.
    for stem in RAW_STEMS:
        (root / f"{stem}.json").write_bytes(raw_bytes[stem])

    build = build_categories(
        parsed["characters"], parsed["devil_fruits"], parsed["islands"]
    )
    categories_json_text = dump_categories_json(build.categories_json)
    (root / "categories.json").write_text(
        categories_json_text, encoding="utf-8", newline="\n"
    )
    (root / "categories.txt").write_text(
        dump_categories_txt(build.categories_txt), encoding="utf-8", newline="\n"
    )

    # Provenance + changelog excerpt for the PR body. Read the heading the
    # PREVIOUS Refresh recorded before write_provenance() overwrites it below -
    # the excerpt is everything Upstream added since then.
    previous_changelog_heading = read_previous_changelog_heading(root)
    changelog_js = fetcher(CHANGELOG_URL).decode("utf-8", errors="replace")
    built_categories: list[dict[str, Any]] = json.loads(categories_json_text)
    provenance_text = write_provenance(
        root,
        changelog_js=changelog_js,
        entry_counts={
            **{f"{stem}.json": len(parsed[stem]) for stem in RAW_STEMS},
            "categories.json": len(built_categories),
        },
        fetched_at=fetched_at,
    )
    changelog_markdown = changelog_entries_since(
        changelog_js, previous_changelog_heading
    )

    # Validate the fetched candidate against the committed baseline (HEAD).
    baseline_raw = vd.committed_raw()
    baseline = GameData.from_raw(baseline_raw.characters, baseline_raw.categories)
    candidate = RawDataset(
        characters=parsed["characters"],
        categories=built_categories,
        devil_fruits=parsed["devil_fruits"],
        islands=parsed["islands"],
    )
    findings = vd.validate_dataset(candidate, baseline, baseline_raw=baseline_raw)

    return RefreshOutcome(
        raw_written=True,
        findings=findings,
        provenance_text=provenance_text,
        changelog_markdown=changelog_markdown,
    )


# --- reporting -----------------------------------------------------------


def format_findings_by_severity(findings: list[Finding]) -> str:
    """The validator findings grouped under BLOCK / REVIEW / INFO headings, for
    the PR body and stdout. An empty list renders as a single reassuring line."""

    if not findings:
        return (
            "_No findings - the dataset is unchanged or the deltas are below "
            "every threshold._"
        )

    sections: list[str] = []
    for severity in Severity:
        matched = [f for f in findings if f.severity is severity]
        if not matched:
            continue
        lines = [f"### {severity.value} ({len(matched)})"]
        lines += [f"- {f.message}" for f in matched]
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def build_pr_body(outcome: RefreshOutcome) -> str:
    """The rolling ``data-refresh`` PR description: the Upstream changelog since
    the last Refresh, the validator findings grouped by severity, and the merge
    rule that applies. Pure - the workflow only writes it to a file."""

    if outcome.has_review:
        rule = (
            "**A REVIEW finding fired.** This PR carries the `needs-review` label "
            "and merges only after a human ticks the checklist below. CI still "
            "goes green."
        )
    else:
        rule = (
            "No REVIEW findings - a green CI is enough to merge. Nothing "
            "auto-merges."
        )

    checklist = (
        "\n\n## Reviewer checklist\n\n"
        "- [ ] Skim the roster / count deltas above - nothing looks like an "
        "Upstream schema break.\n"
        "- [ ] Each REVIEW finding is either accepted or has a follow-up "
        "tuning issue (ADR-0002 / ADR-0003 knobs are **not** touched here).\n"
        "- [ ] The golden test in `tests/test_build_categories.py` is updated "
        "by hand if `categories.json` legitimately changed.\n"
        if outcome.has_review
        else ""
    )

    return "\n".join(
        [
            "Automated weekly **Refresh** of the vendored Raw dataset from "
            "Upstream (oparchive.com). See "
            "`docs/adr/0004-dataset-refresh-pipeline.md`. "
            "`data/PROVENANCE.md` is regenerated in this PR.",
            "",
            rule,
            "",
            "## Validator findings",
            "",
            format_findings_by_severity(outcome.findings),
            "",
            "## Upstream changelog since the last Refresh",
            "",
            outcome.changelog_markdown,
            checklist,
        ]
    )


# --- __main__ ----------------------------------------------------------------


def _provenance_only(fetcher: Fetcher) -> int:
    """Regenerate ``data/PROVENANCE.md`` from the files already on disk - the
    bootstrap path and a cheap way to refresh just the changelog version. No
    dataset fetch, no validation."""

    def _count(name: str) -> int:
        return len(json.loads((REPO_ROOT / name).read_text(encoding="utf-8")))

    counts = {f"{stem}.json": _count(f"{stem}.json") for stem in RAW_STEMS}
    counts["categories.json"] = _count("categories.json")
    try:
        changelog_js = fetcher(CHANGELOG_URL).decode("utf-8", errors="replace")
    except RefreshError as exc:
        print(f"warning: could not fetch the changelog ({exc}); recording 'unknown'")
        changelog_js = ""

    write_provenance(
        REPO_ROOT,
        changelog_js=changelog_js,
        entry_counts=counts,
        fetched_at=datetime.now(timezone.utc),
    )
    print(f"Wrote {provenance_path(REPO_ROOT).relative_to(REPO_ROOT)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run a Refresh in place. Prints the findings and the provenance; returns 1
    iff the fetch failed or any finding is BLOCK (so a scheduled run that fails
    emails the repo owner)."""

    parser = argparse.ArgumentParser(
        description="Refresh the vendored Raw dataset from Upstream."
    )
    parser.add_argument(
        "--provenance-only",
        action="store_true",
        help="just regenerate data/PROVENANCE.md from the files on disk",
    )
    args = parser.parse_args(argv)

    if args.provenance_only:
        return _provenance_only(http_fetch)

    try:
        outcome = refresh()
    except RefreshError as exc:
        print(f"Refresh failed: {exc}")
        return 1

    if not outcome.raw_written:
        print(
            "Upstream shape check FAILED - the vendored Raw dataset was left "
            "untouched.\n"
        )
    print(format_findings_by_severity(outcome.findings))
    if outcome.raw_written:
        print("\n--- data/PROVENANCE.md ---")
        print(outcome.provenance_text)

    return 1 if outcome.blocked else 0


if __name__ == "__main__":
    sys.exit(main())
