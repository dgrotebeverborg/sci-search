# Program 5 verification record

Verified on 2026-08-27 from the isolated `feature/production-platform` worktree.

## Acceptance evidence

- Complete deterministic, API, security, integration, system, contract, and Chromium suite:
  316 tests and 2 subtests passed.
- Branch coverage: 83.21%, above the enforced 80% threshold.
- Browser coverage includes login redirect, project creation and switching, logout, research
  start/cancel, evidence and validation, exports, authorized PDF upload, owner/editor/reviewer/viewer
  behavior, unrelated-user denial, and two simultaneous review sessions exercising optimistic
  conflict recovery.
- Ruff: clean.
- Pyright: 0 errors; 143 warnings at the documented legacy baseline. New Program 5 modules add no
  warning.
- Source distribution and wheel: built successfully; the wheel contains the templates and all
  modular CSS/JavaScript assets.
- Alembic, PostgreSQL repository, and legacy-import checks: 12 passed in the final focused run.
- Dependency audit: no known vulnerabilities in third-party packages. The local `sci-search`
  distribution is correctly reported as not present on PyPI and skipped.
- CSP contains no `unsafe-inline`; rendered Chromium workflows produced no console errors, mixed
  content, or token output.

## Boundary for the next programs

Program 5 establishes the authenticated API, application-service contracts, project isolation,
modular UI, and explicit FastAPI/legacy cutover. The loopback bootstrap intentionally uses the
in-memory application adapters. Wiring the web process to PostgreSQL, Redis, S3, deployment secrets,
health/readiness checks, and production OIDC is the production-composition work tracked in Program
7. The legacy handler remains an explicit opt-in until Program 8 migration acceptance permits its
removal.
