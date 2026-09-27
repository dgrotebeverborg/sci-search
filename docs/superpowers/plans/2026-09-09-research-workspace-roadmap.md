# Research Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn every search into a saved interactive scientific dashboard, rebuild it from researcher feedback, and reuse contextual scientific memory in future searches.

**Architecture:** Versioned dashboard snapshots and append-only feedback use the current production database, object store, and durable jobs. Local research implements the same contracts with a persistent catalog. Scientific memory becomes an authorized service shared by web and CLI adapters.

**Tech Stack:** Python >=3.11, FastAPI, SQLAlchemy/PostgreSQL, SQLite for local use, Dramatiq, object/filesystem storage, vanilla JavaScript, pytest and Playwright.

**Spec:** [Research dashboards and memory design](../specs/2026-09-09-research-dashboards-memory-design.md).

## Global Constraints

All constraints in the linked design apply unchanged to all three implementation plans. Read CONTRIBUTING.md before execution. This is a planning deliverable, not evidence that the product changes are implemented or tested.

## Ordered delivery

| Stage | User-visible deliverable | Implementation plan | Release gate |
|---|---|---|---|
| 1 | All searches in the left sidebar; complete dashboards reopen consistently | [Saved dashboards](2026-09-09-saved-dashboards.md) | Two searches survive browser and server restart, with matching content and working citations/downloads |
| 2 | Article relevance decisions automatically update the dashboard | [Researcher feedback](2026-09-09-researcher-feedback.md) | Exclude/include/reset regenerate consistent revisioned results; failed or stale jobs cannot corrupt them |
| 3 | Prior research and corrections improve future retrieval | [Scientific memory](2026-09-09-scientific-memory.md) | Web searches reuse authorized memory; related feedback improves a held-out benchmark without harming unrelated questions |

## Task checklist

- [ ] 1.1 Define the full dashboard contract and map every existing scientific block.
- [ ] 1.2 Persist runs/revisions, expose history APIs, and restore laptop workspace identity/state.
- [ ] 1.3 Build the sidebar and shared interactive dashboard renderer.
- [ ] 1.4 Recover existing results, validate restart behavior, and release saved dashboards.
- [ ] 2.1 Store contextual article-feedback events with version/conflict handling.
- [ ] 2.2 Rebuild from retained sources into atomic dashboard revisions.
- [ ] 2.3 Connect article controls, feedback reasons, updating state, and revision history.
- [ ] 3.1 Introduce an authorized scientific-memory interface and production graph storage.
- [ ] 3.2 Connect web/CLI memory reads and idempotent ingestion after publication.
- [ ] 3.3 Use contextual feedback in retrieval and screening, with explanations and evaluation.
- [ ] 3.4 Complete the cross-stage acceptance scenario and document migration/rollback.

## Execution rules

Each numbered task in the linked plans is a reviewable change with its own behavior tests. Establish a failing test, implement the defined contract, run the targeted tests, and review the diff before moving on. Make task-sized commits only from an authorized writable checkout; this workspace has pre-existing modified and untracked files, which must be preserved. No additional agent orchestration is needed for this plan.

Run integrations only against the disposable `sci_search_test` database. Existing migration tests drop schemas and must never target user research. Use `compose.integration.yml` following CI configuration. Install Chromium with `uv run python -m playwright install chromium` for browser tests.

At each stage, run its targeted tests plus project-isolation regressions. At final integration, run the required gates in CONTRIBUTING.md: secret scan, formatting, lint, typing, full tests with coverage, build, and dependency audit. Record passed, failed, and unavailable checks separately.

## Decisions captured for implementation

- Prioritize save/reopen and full presentation before feedback ranking.
- Preserve current visible results during rebuild and retain old revisions.
- Keep discovered and included populations explicit in the landscape.
- Keep relevance separate from claim validity; use Background for context only.
- Keep personal/project feedback private within existing access grants; do not pool it across unrelated users.
- Start with the existing database stack and an explicit graph model; measure before adding a dedicated graph engine or learned ranking model.
- Preserve existing research files and import with verified ownership rather than rerunning searches.

## Completion evidence

Capture one deterministic browser walkthrough covering A/B searches, restart, reopen, exclusion/rebuild/reset, and related C search with feedback explanation. Retain the evaluation scorecard and migration rehearsal output outside committed research data. Implementation is complete only when all three stage gates pass; completing this document does not satisfy them.

## Execution result — 2026-09-09

Implemented on `codex/saved-research-dashboards`; changes remain uncommitted for review alongside
pre-existing workspace edits. See [execution record](../../operations/research-dashboards-verification.md)
for validation, implementation choices and the test-environment incident.

The ranking code and evaluation harness are complete, but activating feedback-based ranking remains
gated on researcher-confirmed held-out labels. Saved contextual feedback, explicit dashboard rebuilds,
source reuse and scoped graph memory work with ranking disabled. No real-world learning improvement
is claimed from the synthetic scorecard.
