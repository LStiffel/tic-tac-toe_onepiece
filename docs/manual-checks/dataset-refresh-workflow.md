# Manual check — scheduled dataset Refresh workflow (issue #23)

`.github/workflows/refresh.yml` and its cron / PR wiring are not unit-tested
(ADR 0004; `docs/agents/testing.md`). The fetch + orchestrate logic in
`scripts/refresh.py` is covered by `tests/test_refresh.py`; the parts below need
a human to run the workflow once and confirm the pull request it opens.

## Prerequisite (one-time repo setting)

**Settings → Actions → General → Workflow permissions →** enable *"Allow GitHub
Actions to create and approve pull requests"*. Without it the workflow's
`GITHUB_TOKEN` cannot open the PR. Fallback: create a fine-grained PAT with
`contents:write` + `pull-requests:write`, store it as a secret, and pass it to
the `peter-evans/create-pull-request` step as `token:`.

## Steps

Each step maps to an acceptance criterion on the ticket.

1. **Dispatch the workflow.** Actions → *Weekly dataset Refresh* → *Run workflow*
   on `main`. It checks out, installs, and runs `python -m scripts.refresh`.

2. **A rolling `data-refresh` PR opens (or updates).** If Upstream has moved
   since the vendored copy, exactly one PR against `main` from branch
   `data-refresh` appears. Re-dispatching updates that same PR/branch — it does
   not open a second one. A run with no dataset change opens **no** PR: the
   `git diff` guard is scoped to the five dataset files (`characters.json`,
   `devil_fruits.json`, `islands.json`, `categories.json`, `categories.txt`), and
   the timestamp-only churn in `data/PROVENANCE.md` is reverted on a quiet week.
   Check the run log for "No dataset change this week".

3. **PR body content.** The description carries:
   - the Upstream changelog entries since the last Refresh (heading + bullet
     lines), under *"Upstream changelog since the last Refresh"* — keyed on the
     `Latest Upstream changelog entry` line the last merged `data/PROVENANCE.md`
     recorded;
   - the validator findings grouped under `### BLOCK` / `### REVIEW` / `### INFO`;
   - a one-line pointer that `data/PROVENANCE.md` is regenerated in the PR.

4. **`needs-review` label.** Applied to the PR iff any validator finding is
   REVIEW. A REVIEW run still shows green CI; the PR body carries the reviewer
   checklist. No REVIEW findings → the "Sync the needs-review label" step
   *removes* any stale `needs-review` from the rolling PR, and the body carries
   no checklist.

5. **`data/PROVENANCE.md` regenerated.** The PR's diff includes
   `data/PROVENANCE.md` with the fetch timestamp, `CHANGELOG_VERSION`, source
   URLs, and per-file entry counts for this fetch.

6. **Nothing auto-merges.** The PR sits open until a human merges it.

7. **Failure path.** A failed fetch or a BLOCK finding fails the job (red run,
   GitHub emails the repo owner) and opens no PR. Not easy to trigger on demand;
   confirm by reading the workflow (`if: steps.diff.outputs.changed == 'true'`
   guards the PR step, and the refresh step `sys.exit(1)`s on `outcome.blocked`).

## Expected on the first dispatch

The one-time catch-up Refresh (issue #22, commit `4ae8d0d`) already pulled the
dataset to the current chapter, so the first scheduled run should be quiet or
near-quiet:

- If Upstream has not moved since then: **no PR**.
- If a chapter or two landed since: a small PR — a handful of
  `characters-added` / `count-delta` INFO lines, no BLOCK.
- **Line endings:** `scripts/refresh.py` writes Upstream's bytes verbatim (LF).
  The vendored copies are stored LF in git (`core.autocrlf` only makes them CRLF
  in a local Windows working tree), so on the Ubuntu runner this is a no-op and
  the diff stays content-only.

## Status

- **Automated** (`tests/test_refresh.py`, part of `pytest`): the shape-check
  write gate, `render_provenance`, the changelog-excerpt helpers (including the
  read-before-write ordering), `format_findings_by_severity`, `build_pr_body`,
  the `main()` exit code, and a full `refresh()` over the committed dataset
  writing into a temp dir.
- **Steps 1–7 above:** pending a human dispatch (needs the workflow on the
  default branch and the repo setting from the *Prerequisite* section). Record
  the run URL, the PR link, and the outcome here afterwards.
