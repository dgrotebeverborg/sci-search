# Saved Dashboards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Save every search and reopen its complete interactive scientific dashboard from the left sidebar.

**Architecture:** Store immutable structured dashboard revisions behind an authorized application service. Production uses PostgreSQL metadata and object storage; local research uses a durable SQLite catalog and filesystem snapshots. Fresh and historical results share one renderer.

**Tech Stack:** Existing Python/FastAPI/SQLAlchemy stack, SQLite, Jinja, JavaScript, pytest, Playwright.

**Spec:** [Design](../specs/2026-09-09-research-dashboards-memory-design.md), required experience 1–5 and delivery/acceptance.

## Global Constraints

- Preserve exact source passages, deterministic validation, and explicit answer withholding.
- Opening a saved dashboard must not execute research or model analysis.
- Every protected read/write, graph traversal, feedback lookup, source link, and export must enforce project authorization.
- Preserve existing uncommitted work; never reset or stage unrelated changes.

All remaining design constraints also apply.

## Task 1.1: Contract and block inventory

**Files:** Create `sci_search/dashboard.py`, `tests/test_dashboard.py`, `docs/design/dashboard-blocks.md`, and `tests/fixtures/dashboard_v1.json`. Read `sci_search/literature_review.py`, `sci_search/research_landscape.py`, `sci_search/reporting.py`, and retained example HTML; do not copy promotional content into real results.

**Interfaces:** `build_dashboard(investigation: dict, *, run_id: str, revision: int) -> dict` produces a JSON-safe `research_dashboard_v1` snapshot. Application authorization supplies project identity separately. Snapshot keys are `schema_version`, `layout_version`, `run_id`, `revision`, `question`, and `blocks`. Each block has `id`, `status` (`ready`, `empty`, `unavailable`), `data`, and `explanation`.

- [ ] Add a synthetic completed investigation containing answer, review, landscape, study matrix, measurements, source offsets, and coverage limitations. Add an inadequate-evidence variant. Document the source field and UI interaction for every block in the design inventory.
- [ ] Add and run this contract assertion in `tests/test_dashboard.py`, using that fixture:

```python
dashboard = build_dashboard(investigation, run_id="run-a", revision=1)
assert dashboard["schema_version"] == "research_dashboard_v1"
assert {b["id"] for b in dashboard["blocks"]} == {
    "scope", "answer", "literature_review", "findings", "comparisons",
    "landscape", "studies", "gaps", "methods", "evidence", "validation",
    "references", "downloads",
}
assert dashboard["question"] == investigation["question"]
```

- [ ] Implement the pure mapper using the existing literature-review and landscape payloads. Preserve stable evidence/publication identifiers and exact quotations. Represent unavailable content explicitly; never synthesize new conclusions in the renderer. Add newly discovered existing blocks to both inventory and expected set.
- [ ] Run `uv run pytest tests/test_dashboard.py tests/test_literature_review.py tests/test_research_landscape.py -q`. Confirm source offsets and answer withholding survive mapping; review the focused diff.

## Task 1.2: Durable runs, revisions, and authorized APIs

**Files:** Create `sci_search/application/dashboards.py`, `sci_search/infrastructure/dashboard_repository.py`, `sci_search/infrastructure/local_workspace.py`, `sci_search/api/routes/dashboards.py`, `tests/api/test_dashboards.py`, and `tests/integration/test_dashboard_storage.py`. Modify `sci_search/infrastructure/tables.py`, `sci_search/api/app.py`, `sci_search/api/bootstrap.py`, `sci_search/infrastructure/local_research.py`, `sci_search/infrastructure/research_execution.py`, and `sci_search/infrastructure/production_services.py`. Add an Alembic revision after the actual current head; do not assume a migration number.

**Interfaces:** Authorized `DashboardService.list_runs(user_id: str, project_id: str, *, query: str, cursor: str | None, limit: int) -> dict`; `get_dashboard(user_id: str, project_id: str, run_id: str, *, revision: int | None = None) -> dict`. `publish_revision(project_id: str, run_id: str, *, parent_revision: int | None, feedback_sequence: int, snapshot: dict, artifact_ids: list[str]) -> int` is an internal repository operation inside the authorized worker transaction. Return the new revision number, rejecting stale parent publication.

- [ ] Create tests that persist A and B, dispose/recreate the database/service, list both, and reopen A. Another user requesting A receives the same not-found response as an unknown run. Unknown revision also returns not found.
- [ ] Add the additive schema and repository operations. Use this relational shape:

```text
research_runs: existing row + current_revision(nullable), feedback_sequence(default 0)
dashboard_revisions: project_id, run_id, revision, parent_revision, feedback_sequence,
  snapshot_blob_key, source_fingerprint, generator_version, created_at
  UNIQUE(run_id, revision); composite ownership constraints
revision_artifacts: project_id, run_id, revision, artifact_id
```

- [ ] Persist every submitted run before execution. Write immutable snapshot/export objects first; then transactionally publish their associations and current revision. Failures keep the previous current revision. Evidence, validation, documents, and exports resolve through run/revision associations; remove latest-run-only selection from local mode.
- [ ] Expose `GET /api/v1/projects/{project_id}/runs?query=&cursor=&limit=`, `GET .../runs/{run_id}/dashboard?revision=`, and `GET .../runs/{run_id}/revisions`. Use `(created_at, id)` descending cursor ordering, limit default 30/max 100, and a query tied to cursor state. Update OpenAPI schemas and route dependencies. Enforce existing project policy on all reads.
- [ ] Implement local SQLite transactions for stable development owner/project membership, run state, revision metadata, and pending execution. Keep source artifacts under the configured local root. Startup reuses that catalog; login sessions can be renewed. Plain workspace-preview retains its explicit temporary behavior. Mark interrupted initial local jobs as interrupted with retry; do not silently lose them or invent completion.
- [ ] Run `uv run pytest tests/api/test_dashboards.py tests/api/test_local_research.py tests/integration/test_dashboard_storage.py tests/security/test_project_isolation.py -q`. On isolated test storage only, rehearse additive upgrade, rollback, and upgrade. Verify snapshots persist and incomplete artifact publication stays invisible.

## Task 1.3: Sidebar and complete interactive rendering

**Files:** Create `sci_search/frontend/static/history.js`, `sci_search/frontend/static/dashboard.js`, `sci_search/frontend/static/landscape.js`, and `tests/browser/test_saved_dashboards.py`. Modify `frontend/templates/app.html` and `frontend/static/{app.js,app.css,projects.js,runs.js,evidence.js,validation.js,exports.js,documents.js}` under `sci_search/`.

**Interfaces:** `openDashboard(projectId, runId, revision = null)` fetches the contract from task 1.2; `renderDashboard(snapshot)` renders task 1.1 blocks; `loadHistory(projectId, {query, cursor})` loads sidebar pages. Stable URL: `/app?project=<id>&run=<id>&revision=<optional number>`.

- [ ] Add browser coverage for two saved searches, refresh, direct-link login, project switch, browser back/forward, and pagination. Assert opening A makes no POST to `/runs`. Start from deterministic fixture API results, then also exercise the real test service.
- [ ] Implement history loading and URL restoration after authentication. Track a request generation and abort old fetches so A's delayed response cannot overwrite B. A newly queued search immediately appears in history. Keep failed/cancelled entries selectable with their status.
- [ ] Render the complete block inventory using reusable DOM components. Use textContent for source text; avoid untrusted raw HTML. Literature review citations open evidence; evidence opens authorized originals. Landscape chart selection filters papers and can switch between discovered/included populations. Provide readable tables and keyboard controls alongside charts. Preserve server-defined missing-data explanations.
- [ ] Route fresh completion through the exact same `openDashboard` call used by the sidebar. Scope downloads and reviews to selected run/revision. On a narrow screen make the history panel collapsible while retaining navigation access.
- [ ] Use this behavior as a browser acceptance assertion:

```python
page.get_by_role("link", name="Question A", exact=True).click()
before = page.locator("[data-dashboard-block]").all_text_contents()
page.reload()
expect(page.locator("[data-dashboard-block]").first).to_be_visible()
assert page.locator("[data-dashboard-block]").all_text_contents() == before
```

- [ ] Run `uv run pytest tests/browser/test_saved_dashboards.py tests/browser/test_research_workflow.py tests/browser/test_role_workflow.py -q`. Inspect desktop and narrow-screen screenshots for all blocks, long citations, empty results, and a long history list. Fix clipping, unreadable charts, and broken focus order before release.

## Task 1.4: Recovery, restart proof, and documentation

**Files:** Create `scripts/import_saved_dashboards.py`, `tests/integration/test_dashboard_import.py`, `tests/system/test_dashboard_restart.py`. Modify `README.md`, `docs/runbooks/BACKUP_RESTORE.md`, and `docs/runbooks/ROLLBACK.md`.

**Interfaces:** CLI `uv run python scripts/import_saved_dashboards.py --source <path> --project-id <id> --dry-run`; remove `--dry-run` for a validated import. Target catalog/database comes from existing runtime configuration. A unique source fingerprint makes re-import a no-op.

- [ ] Test importing two retained synthetic run directories, repeated import, missing report, unknown schema version, and absent ownership. Ownership must be supplied/verified; no directory-name guessing. Preserve source files and emit a per-run recovery report.
- [ ] Implement import through the same snapshot publisher. Map validated old schemas; retain incomplete entries with explicit missing-block explanations. Do not call providers or models. Keep legacy files intact and avoid writing acquired content into Git.
- [ ] Run `uv run pytest tests/integration/test_dashboard_import.py tests/system/test_dashboard_restart.py -q`. Restart actual local and production test services, log in again, and compare dashboard payload hashes, source bytes, and download revision identifiers for A/B.
- [ ] Document persistent local versus temporary preview behavior and catalog/source backup as one recoverable unit. Record an application rollback that disables new UI/routes while retaining additive data. Stage 1 release requires task 1.1–1.4 evidence, not screenshots alone.
