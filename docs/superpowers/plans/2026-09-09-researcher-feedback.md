# Researcher Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Article relevance decisions automatically regenerate a consistent dashboard revision and remain available as contextual long-term feedback.

**Architecture:** Append immutable relevance events and schedule a durable rebuild in the same database transaction. Rebuild from retained inputs and publish through the stage-1 revision contract. Separate article inclusion decisions from evidence-validity review.

**Tech Stack:** Existing application policies, PostgreSQL/SQLite repositories, Dramatiq/local persistent jobs, research pipeline, JavaScript, pytest and Playwright.

**Spec:** [Design](../specs/2026-09-09-research-dashboards-memory-design.md), required experience 6–7 and feedback/rebuild architecture. Depends on [saved dashboards](2026-09-09-saved-dashboards.md).

## Global Constraints

- Preserve exact source passages, deterministic validation, and explicit answer withholding.
- Every protected read/write, graph traversal, feedback lookup, source link, and export must enforce project authorization.
- Use deterministic synthetic providers and model outputs in automated tests; no live paid calls.
- Preserve existing uncommitted work; never reset or stage unrelated changes.

All remaining design constraints also apply.

## Task 2.1: Append-only contextual article decisions

**Files:** Create `sci_search/application/article_feedback.py`, `sci_search/infrastructure/feedback_repository.py`, `sci_search/api/routes/article_feedback.py`, `tests/api/test_article_feedback.py`, and `tests/integration/test_article_feedback.py`. Modify `sci_search/infrastructure/tables.py`, `sci_search/api/app.py`, `sci_search/infrastructure/local_workspace.py`, and the existing centralized policy definitions. Add an additive Alembic migration after the actual head.

**Interfaces:** `ArticleFeedbackService.record(user_id: str, project_id: str, run_id: str, publication_id: str, *, decision: str, reason: str, expected_sequence: int, idempotency_key: str) -> dict`. Decisions are `include`, `background`, `exclude`, `reset`. Returns event ID, new feedback sequence, rebuild job ID, and current completed revision. Internal `effective_decisions(project_id: str, run_id: str, *, sequence: int) -> dict` folds ordered events; Reset withdraws the applicable override.

- [ ] Test Include→Exclude→Reset, repeated idempotency key, stale expected sequence, unauthorized actor, paper absent from the run, and attempts to edit events. Seed a real synthetic study in the run ledger rather than accepting arbitrary publication IDs.
- [ ] Persist this event shape; author and time must be server-derived:

```text
article_feedback_events: id, project_id, run_id, publication_id,
  actor_user_id, sequence, decision, reason, question_context_json,
  reviewed_revision, source_fingerprint, idempotency_key, created_at
UNIQUE(run_id, sequence); UNIQUE(run_id, actor_user_id, idempotency_key)
```

- [ ] Store the reviewed question, scope dimensions, review configuration, and canonical paper identity in context. Keep reasons optional but strongly prompted for exclusion/background; reject whitespace-only reason if the user explicitly supplies a reason field. Never invent one. Preserve historical source fingerprints.
- [ ] Expose `POST /api/v1/projects/{project_id}/runs/{run_id}/articles/{publication_id}/feedback` with the interface fields. Require existing REVIEW permission (owner/reviewer); viewers and editors without REVIEW cannot submit decisions. Record and enqueue rebuild atomically using the current job repository's durable delivery/recovery mechanism. Local SQLite persists the same event and pending work transactionally.
- [ ] Return HTTP 409 for stale sequence or mismatched reuse of an idempotency key, 404 for unknown/unauthorized objects, and 422 for invalid decisions. Return the existing receipt for an identical retried request. Verify the fold with this test assertion:

```python
assert [e["decision"] for e in stored_events] == ["include", "exclude", "reset"]
assert publication_id not in effective_decisions(project_id, run_id, sequence=3)
```

- [ ] Run `uv run pytest tests/api/test_article_feedback.py tests/integration/test_article_feedback.py tests/security/test_project_isolation.py -q`. Verify no feedback is lost if the process stops between commit and queue delivery.

## Task 2.2: Rebuild and publish coherent revisions

**Files:** Create `sci_search/application/rebuild_dashboard.py`, `sci_search/infrastructure/dashboard_rebuild.py`, `tests/test_dashboard_rebuild.py`, and `tests/system/test_dashboard_rebuild_recovery.py`. Modify `sci_search/research_runs.py`, `sci_search/fulltext_screening.py`, `sci_search/study_matrix.py`, `sci_search/literature_review.py`, `sci_search/research_landscape.py`, `sci_search/infrastructure/research_execution.py`, and `sci_search/infrastructure/local_research.py`.

**Interfaces:** `rebuild_investigation(state: dict, *, decisions: dict, corpus_directory: Path, analyzer: object | None) -> dict` accepts a retained source ledger and effective decisions. It returns the same investigation schema consumed by `build_dashboard`. Keep concrete analyzer typing aligned with the existing analyzer protocol during implementation. Worker input is `{project_id, run_id, base_revision, feedback_sequence}`. Publication uses stage 1's `publish_revision` contract.

- [ ] Add a fixture with two papers supporting different claims and a third background paper. Excluding one must remove its supporting claims and citations from the current synthesis, change coverage/adequacy, update review/study matrix, and regenerate matching exports. Original revision remains readable. Reset re-evaluates automated screening without destroying the event history.
- [ ] Extract the reusable rebuild operation from `ResearchRunManager._rebuild_evidence` into the application-facing flow. Load authorized retained artifacts into an isolated revision work directory; never overwrite the completed revision. Preserve legacy CLI behavior with its adapter. A dashboard rebuild must not restart discovery.
- [ ] Make Background context-only: retain its metadata/context in the study list and review, but prevent its passages from serving as direct support for primary conclusions. Include still requires a readable acquired full text and valid source grounding. An include decision for missing text records `full_text_unavailable` in the study view and keeps the acquisition/upload action available; it does not claim that evidence was added.
- [ ] Recompute all dependent outputs: evidence, validated synthesis, answer adequacy, study matrix, included/discovered landscape counts, literature review, citations, validation, and exports. Preserve the discovered ledger and distinguish its population from included evidence. Carry evidence-review states only when their content/schema fingerprints still match; changed evidence returns to review.
- [ ] Key rebuild work by `(run_id, feedback_sequence, generator_version)`. Before publication, compare both parent revision and feedback sequence in one transaction. If newer feedback exists, mark the old job superseded and ensure latest pending work is scheduled. On error retain current revision and expose failed rebuild status/retry. Recover committed pending work after worker/server restart.
- [ ] Prove atomicity and race handling with these assertions in fixture-driven tests:

```python
assert current_snapshot["revision"] == 1  # while revision 2 is rebuilding
assert old_export_bytes == original_export_bytes
# Complete a sequence-1 job after sequence-2 feedback was committed.
assert published_feedback_sequence != 1
assert latest_job_status in {"queued", "running", "completed"}
```

- [ ] Run `uv run pytest tests/test_dashboard_rebuild.py tests/system/test_dashboard_rebuild_recovery.py tests/test_fulltext_screening.py tests/test_online_discovery.py tests/test_literature_review.py -q`. Include zero remaining studies, invalid model output, failed export generation, source mismatch, duplicate delivery, rapid decisions, and cancellation cases. Publish no partial revision in any failure case.

## Task 2.3: Article controls and visible revision history

**Files:** Create `sci_search/frontend/static/article_feedback.js` and `tests/browser/test_article_feedback.py`. Modify `frontend/static/{dashboard.js,history.js,evidence.js,runs.js,app.css}` and `frontend/templates/app.html` under `sci_search/`.

**Interfaces:** `submitArticleFeedback({projectId, runId, publicationId, decision, reason, expectedSequence})` invokes task 2.1 with a stable idempotency key per submission. Dashboard response includes current completed revision, feedback sequence, pending rebuild status, and effective article decisions. Task 1.2's revision-list endpoint supplies older snapshots.

- [ ] Add browser scenarios for Exclude and Reset with a reason, permission-disabled controls, stale-version conflict, failed rebuild/retry, and leaving a run during rebuild. Article feedback must not be confused with existing Accept/Reject evidence controls.
- [ ] Render controls per study with current automated decision, researcher override, reason, and full-text availability. On accepted feedback immediately show the saved decision and updating status while labeling the displayed dashboard's older revision. Update all blocks together only after a new revision is complete.
- [ ] Make historical revisions inspectable through a revision selector. Disable editing of an old snapshot and provide a link to the current revision. Show excluded papers in the study list so users can reset them. Ensure downloads always belong to the displayed revision.
- [ ] Verify the UI flow with Playwright assertions:

```python
page.get_by_role("button", name="Exclude article").first.click()
page.get_by_label("Reason").fill("Different study population")
page.get_by_role("button", name="Save decision").click()
expect(page.get_by_role("status").filter(has_text="Updating dashboard")).to_be_visible()
# Fixture worker publishes the rebuild, then all visible blocks share revision 2.
expect(page.locator("[data-dashboard-revision='2']")).to_be_visible()
```

- [ ] Run `uv run pytest tests/browser/test_article_feedback.py tests/browser/test_saved_dashboards.py tests/browser/test_role_workflow.py -q`. Complete the real service acceptance sequence A→Exclude→revision 2→Reset→revision 3, verifying B stays unchanged and restart retains all events. Document automatic synthesis reruns and failure recovery in README.
