# Program 5: Authenticated API and Project-First Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the monolithic local HTTP handler and embedded UI with an authenticated FastAPI service and modular, accessible project-first browser interface.

**Architecture:** Thin routers validate schemas and call project-scoped application use cases. Server-side authorization remains authoritative. Static HTML/CSS/JavaScript modules consume versioned JSON APIs and poll durable job status.

**Tech Stack:** FastAPI, Pydantic, Authlib session integration, Jinja2, vanilla ES modules, Playwright, pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-multi-user-production-platform-design.md`

## Global Constraints

- All research endpoints require an authenticated session and project policy decision.
- State-changing requests require CSRF validation.
- Unknown fields are rejected and errors never expose traces or resource existence.
- Current CLI behavior remains available independently of the web migration.

---

### Task 1: FastAPI application shell and security middleware

**Files:**
- Create: `sci_search/api/app.py`, `dependencies.py`, `errors.py`, `schemas.py`
- Test: `tests/api/test_app_security.py`

**Interfaces:**
- Produces: `create_app(settings, services) -> FastAPI`, authenticated principal dependency, CSRF dependency, and uniform `ResourceNotFound` mapping.

- [x] Write failing tests for unauthenticated denial, secure headers, same-origin CORS, body limits, CSRF rejection, and identical missing/unauthorized responses.
- [x] Implement the minimal app factory and middleware stack.
- [x] Add production-startup tests rejecting wildcard origins, insecure callbacks, development auth, and default secrets.
- [x] Run tests and commit.

### Task 2: Project and membership routes

**Files:**
- Create: `sci_search/api/routes/projects.py`
- Test: `tests/api/test_projects.py`

**Interfaces:**
- Produces list/create/read/update/delete projects and owner-only membership operations.

- [x] Write role-specific failing route tests with two users and guessed IDs.
- [x] Implement Pydantic schemas with `extra="forbid"` and thin application-service calls.
- [x] Assert audit events for create, role change, removal, and deletion.
- [x] Extend the shared isolation matrix and commit.

### Task 3: Runs, documents, evidence, validation, and export routes

**Files:**
- Create: `sci_search/api/routes/runs.py`, `documents.py`, `reviews.py`, `exports.py`, `audit.py`
- Test: `tests/api/test_research_routes.py`

**Interfaces:**
- Produces project-scoped start/status/cancel/retry, document streaming, evidence review, validation, export, and audit APIs.

- [x] Write failing tests for every route across owner/editor/reviewer/viewer and unrelated user.
- [x] Implement bounded schemas and streaming responses without loading entire multi-document packages in web-process memory.
- [x] Preserve current upload signature, parseability, path, and size validation behind the application service.
- [x] Add pagination and stable ordering to list endpoints; add conditional version checks to review mutations.
- [x] Run API, isolation, and current web tests; commit.

### Task 4: Separate frontend assets and project navigation

**Files:**
- Create: `sci_search/frontend/templates/app.html`
- Create: `sci_search/frontend/static/app.css`
- Create: `sci_search/frontend/static/api.js`, `auth.js`, `projects.js`, `runs.js`, `evidence.js`, `validation.js`, `exports.js`
- Test: `tests/browser/test_projects.py`

**Interfaces:**
- Produces same-origin authenticated browser application with accessible project/run navigation.

- [x] Write a Playwright test for login redirect, personal workspace, project creation, project switching, and logout.
- [x] Verify it fails before routes/assets exist.
- [x] Move HTML/CSS from `ui.py` without functional redesign, then split JavaScript by feature.
- [x] Add visible loading, empty, error, permission, cancelled, and failed-job states.
- [x] Verify keyboard navigation, labels, focus management, and no authorization dependence on hidden controls.
- [x] Run browser and API tests; commit.

### Task 5: Research and review browser workflows

**Files:**
- Extend frontend modules from Task 4
- Test: `tests/browser/test_research_workflow.py`, `test_role_workflow.py`

**Interfaces:**
- Covers starting/polling/cancelling/retrying runs, evidence review, authorized upload, and export.

- [x] Write failing browser tests for editor, reviewer, viewer, and unrelated-user workflows.
- [x] Implement bounded polling with backoff and stop conditions for complete, failed, and cancelled jobs.
- [x] Implement optimistic-version conflict UI for simultaneous reviews.
- [x] Confirm cross-project URLs and manipulated request bodies remain denied by the API.
- [x] Run browser tests and commit.

### Task 6: Compatibility cutover

**Files:**
- Modify: `sci_search/cli.py`
- Create: `sci_search/compatibility/local_web.py`
- Test: `tests/contracts/test_web_compatibility.py`

**Interfaces:**
- Makes `serve` start FastAPI for the new deployment while preserving an explicit temporary local compatibility path during migration.

- [x] Write failing CLI tests for the desired server selection and safe loopback defaults.
- [x] Implement FastAPI serve entry point; require explicit unsafe-development flag for compatibility handler.
- [x] Preserve API artifact semantics required by current tests or document versioned endpoint changes.
- [x] Run full suite and commit.

### Task 7: Program 5 verification

- [x] Run all API security and project-isolation tests.
- [x] Run Playwright workflows in Chromium with two simultaneous sessions.
- [x] Run current CLI, report, scientific, and web compatibility tests.
- [x] Run Ruff, Pyright, coverage, package build, migration checks, and dependency audit.
- [x] Verify CSP and browser console contain no unsafe-inline requirement, mixed content, token output, or uncaught errors.
