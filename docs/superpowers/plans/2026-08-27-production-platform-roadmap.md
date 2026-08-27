# Sci-Search Production Platform Implementation Roadmap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved SURFconext-authenticated, project-scoped, durable multi-user Sci-Search platform through eight independently testable programs.

**Architecture:** Preserve the scientific core while adding a modular application boundary, PostgreSQL, Redis-backed workers, S3-compatible blobs, FastAPI, and a separated frontend. Each program has its own test-first implementation plan and leaves the repository deployable or backward-compatible.

**Tech Stack:** Python 3.11+, pytest, FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL, Redis, Dramatiq, Authlib, boto3, Docker Compose, Caddy, Ruff, Pyright, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-27-multi-user-production-platform-design.md`

## Global Constraints

- Support Python 3.11 through 3.14.
- Preserve exact-passage provenance and deterministic answer-withholding behavior.
- Require authentication for every version-1 research resource.
- Identify OIDC users only by `(issuer, subject)`; never by email.
- Scope every protected resource through a project authorization decision.
- Keep PostgreSQL authoritative for jobs and application metadata; Redis is delivery and coordination only.
- Store document bytes through a content-addressed `BlobStore` interface.
- Keep current CLI commands and serialized research artifacts compatible until Program 8 explicitly retires legacy paths.
- Apply test-driven development to behavior changes and run the complete existing suite at every program boundary.
- Do not add Kubernetes, public sharing, passwords, billing, or WebSockets in version 1.

---

## Program sequence

| Order | Program plan | Deployable outcome |
| --- | --- | --- |
| 1 | `2026-08-27-program-1-engineering-baseline.md` | Reproducible dependencies, CI, quality gates, and compatibility contracts |
| 2 | `2026-08-27-program-2-identity-projects.md` | Users, OIDC sessions, workspaces, projects, RBAC, and isolation tests |
| 3 | `2026-08-27-program-3-persistence-blobs.md` | PostgreSQL/Alembic repositories, content-addressed blobs, and legacy import |
| 4 | `2026-08-27-program-4-durable-jobs-pipeline.md` | Restart-safe jobs and staged research execution |
| 5 | `2026-08-27-program-5-api-frontend.md` | Authenticated FastAPI service and project-first modular UI |
| 6 | `2026-08-27-program-6-scientific-quality.md` | Diverse model evidence selection, provider abstraction, and bias review records |
| 7 | `2026-08-27-program-7-production-operations.md` | Docker production stack, metrics, health, backup, restore, and runbooks |
| 8 | `2026-08-27-program-8-migration-retirement.md` | Verified migration, garbage collection, and safe legacy retirement |

## Program gates

Each program may begin only when the preceding program meets all of these gates:

- [x] Its focused unit and integration tests pass.
- [x] `python -m pytest -q` passes for the complete repository.
- [x] Ruff, Pyright, and package-build checks pass at the current documented baseline.
- [x] Database migrations, if any, upgrade an empty database and the previous program schema.
- [x] New protected-resource operations have cross-project denial tests.
- [x] Documentation describes forward migration and rollback.
- [x] The program has no unresolved high-severity security or scientific-integrity regression.

## Final acceptance run

- [x] Start the complete Docker Compose stack with production-like secrets and TLS test certificates.
- [ ] Authenticate two different SURFconext test-environment subjects and verify each receives a distinct private workspace.
- [x] Create a shared project and verify owner, editor, reviewer, and viewer behavior.
- [x] Start simultaneous research runs in separate projects and terminate a worker during one run.
- [x] Restart the worker and verify the interrupted run resumes without duplicate evidence or artifacts.
- [x] Attempt cross-project reads, mutations, uploads, reviews, downloads, and exports; verify uniform not-found responses.
- [x] Verify model-invalid evidence produces the deterministic fallback and an audit record.
- [x] Back up PostgreSQL and object storage, restore into an isolated stack, and compare manifest counts and hashes.
- [x] Run the complete deterministic, integration, migration, browser, packaging, typing, linting, and security suites.
- [x] Record production deployment, rollback, recovery, and storage-cleanup evidence in the release checklist.

## Workspace prerequisite

The active environment currently allows writes only below `sci_search/` and exposes no functional Git metadata. Before repository-wide execution, place these plans under repository-root `docs/superpowers/plans/`, make repository-root `tests/`, `pyproject.toml`, `.github/`, deployment files, and migrations writable, then create an isolated Git worktree. Package-local behavior can be developed in the current workspace, but no program may be declared complete until its repository-level changes and tests are integrated.
