# Research dashboards verification — 2026-09-09

## Delivered behavior

- Persistent question history and stable dashboard/revision URLs; fresh and reopened searches use the same 13-block scientific renderer.
- Durable local projects, runs, sources, exports and feedback; session recreation does not discard the workspace.
- Article Include/Background/Exclude/Reset events rebuild from retained sources into immutable revisions. Prior snapshots/downloads stay available; stale/failed jobs cannot overwrite newer decisions.
- Current finding-level evidence review retains optimistic version checks and is separate from article relevance. Historical-only finding records cannot be mutated.
- Scoped local and production scientific graph memory, validated source reuse, deferred publication, retryable projections, and contextual feedback records.
- Idempotent, explicit-owner legacy import with dry run and recovery after an interrupted import. Source files are preserved.
- Default-disabled contextual acquisition ranking with a synthetic comparison scorecard. Activation requires researcher-confirmed held-out evaluation; this run does not establish real-world ranking improvement.

## Verification evidence

Final command: `.venv/bin/python -m pytest --cov=sci_search --cov-report=term-missing -q`.
Result: **454 passed, 17 skipped, 2 subtests passed; 82.85% coverage** (required floor 80%).
The suite includes Chromium, PostgreSQL migration/rebuild/recovery, MinIO, Redis, project isolation,
local application restart, failed/stale rebuilds, finding review versions, imports, and memory ordering.

- Ruff lint: passed.
- Ruff formatting: 238 files already formatted.
- Pyright: 0 errors, 195 warnings. Warnings remain; no claim of warning-free typing.
- Secret scan and `git diff --check`: passed.
- Final isolated sdist/wheel build: passed.
- Locked dependency audit: no known vulnerabilities found.
- Synthetic evaluation: generated `/tmp/sci-search-feedback-scorecard.json`; release gate remains `pending_researcher_confirmed_held_out_labels`.
- Desktop/mobile dashboard screenshots inspected in `/tmp/sci-search-dashboard-desktop-viewport.png` and `/tmp/sci-search-dashboard-mobile-viewport.png`.

Temporary verification logs: `/tmp/sci-search-tests-final.txt`, `/tmp/sci-search-pyright-final.txt`,
`/tmp/sci-search-build-final.txt`. These logs and screenshots are local review artifacts, not committed research data.

## Reviewed implementation choices

Production snapshots use immutable JSON in `dashboard_revisions`, allowing atomic publication with
feedback sequence and current-revision state. Source archives/exports stay in the object store.
This replaces the proposed separate snapshot-object lookup with the existing database's transactional
read model. Local mode uses a SQLite catalog and content-addressed filesystem objects.

Graph memory reuses the established scientific-memory implementation through project-bound adapters.
Production checkpoints and normalized graph projections live in PostgreSQL; referenced sources live in
object storage. Recovery occurs before subsequent production searches and on local startup/next search;
there is no new periodic scheduler. Legacy snapshots without retained source archives are explicitly
unavailable for replay and cannot starve newer recoverable revisions.

Background papers remain visible as context but are excluded from primary evidence extraction.
Similarity feedback affects acquisition ordering only when the experimental configuration is enabled;
it never globally blacklists a publication or overrides a current explicit inclusion decision.

The feature branch is `codex/saved-research-dashboards`. No merge, push, deployment, or migration of a
user database was performed. Existing edits were retained. The plan documents track implementation;
production activation still requires ordinary deployment/migration and the ranking evaluation gate.

## Test-environment incident

During initial agent setup, `docker compose -f compose.integration.yml up -d postgres` reused the
existing `sci-search` project name and replaced its previous ephemeral test PostgreSQL container.
Inspection showed a test Compose configuration with ephemeral storage, not a persistent database volume.
The previous ephemeral database contents were lost. This was reported to the user during execution.
No persistent volume was deleted and no further recreation of the prior stack was attempted.

Subsequent MinIO/Redis test services were created under the separate `sci-search-ci` project and are
cleaned up after verification. The replacement PostgreSQL test container is left untouched to avoid
another alteration of the pre-existing stack. Future integration setup must use an isolated project name.

### Follow-up: question approval and dashboard redesign (2026-09-09)

Restored the existing question interpreter before web research execution. Users review
scope, assumptions, exclusions and clarification, edit the question to reinterpret,
and explicitly approve before a run is created. The authenticated CSRF-protected
interpretation endpoint uses run-management permissions. Approved briefs travel through
local metadata and production job input into the retained research state.

Reorganized all thirteen dashboard blocks into five reading views: Overview,
Literature review, Research landscape, Studies & evidence, and Methods & exports.
The overview has compact research counts, the qualified answer, findings and gaps.
The search composer opens via New search; version history is expandable. Evidence
links reveal the evidence view, and feedback refreshes preserve the selected view.

Verification: 392 tests passed, 17 skipped, 2 subtests passed using pytest with
`--ignore=tests/integration`; infrastructure integration tests were not rerun for this
follow-up. Ruff lint and formatting and git diff whitespace checks passed. Pyright:
0 errors, 195 existing warnings. Browser and API subset: 89 passed. The initial
confirmation regression failed against the missing UI before implementation.
Desktop and mobile screenshots were inspected against the existing saved energy-market
search without initiating new research; mobile had no horizontal overflow.
Artifacts: `/tmp/sci-search-redesign-live.png`,
`/tmp/sci-search-redesign-live-mobile.png`, `/tmp/sci-search-redesign-full-tests.txt`.
