# Program 7: Production Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a secure, observable, backed-up Docker Compose deployment for approximately ten simultaneous users.

**Architecture:** One immutable application image runs web or worker commands. Caddy terminates TLS; PostgreSQL, Redis, and MinIO use private networks and persistent volumes. Explicit migration, backup, restore, and worker-drain commands support controlled releases.

**Tech Stack:** Docker Compose, Caddy, PostgreSQL, Redis, MinIO, Prometheus client, structured JSON logging.

**Spec:** `docs/superpowers/specs/2026-08-27-multi-user-production-platform-design.md`

## Global Constraints

- Production configuration must fail closed on default credentials, insecure callbacks, wildcard origins, or development authentication.
- Databases, Redis, and MinIO are not published on public interfaces.
- Logs and metrics contain no secrets, tokens, raw documents, prompts, or unbounded user labels.
- Backup is incomplete until a restore drill succeeds.

---

### Task 1: Immutable application image and Compose profiles

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `compose.yml`, `compose.test.yml`
- Create: `docker/entrypoint.sh`
- Test: `tests/deployment/test_container_smoke.py`

**Interfaces:**
- Produces `web`, `worker`, `migrate`, and administrative commands from one image.

- [x] Write a failing container smoke test that builds the image, runs as a non-root UID, imports the package, and exposes no source `.env.local` or data directory.
- [x] Implement a multi-stage build with pinned base digest, wheel installation, read-only application files, non-root runtime, and writable explicit temp directory.
- [x] Define private service networks, health checks, named volumes, resource limits, and development/test/production overrides.
- [x] Verify only Caddy publishes ports in production; commit.

### Task 2: TLS proxy and secure production configuration

**Files:**
- Create: `docker/Caddyfile`, `sci_search/infrastructure/settings.py`
- Test: `tests/deployment/test_production_settings.py`

**Interfaces:**
- Produces validated settings and HTTPS/security-header proxy configuration.

- [x] Write failing tests for every insecure production setting and a literal valid SURFconext-style configuration.
- [x] Implement typed settings with secret-file support and redacted representations.
- [x] Configure TLS, request limits, HSTS after TLS validation, CSP, frame denial, no-sniff, referrer policy, and trusted proxy headers.
- [x] Run production-startup smoke tests and commit.

### Task 3: Structured logging, health, and metrics

**Files:**
- Create: `sci_search/infrastructure/observability.py`
- Create: `sci_search/api/routes/operations.py`
- Test: `tests/infrastructure/test_observability.py`

**Interfaces:**
- Produces correlation context, JSON logs, `/health/live`, `/health/ready`, and bounded Prometheus metrics.

- [x] Write failing tests proving correlation IDs propagate and sensitive keys/document text are redacted.
- [x] Implement liveness without dependencies and readiness with bounded PostgreSQL, Redis, and S3 checks.
- [x] Add metrics for request latency, denials, queue age/depth, leases, stages, providers, storage, evidence, withholding, and model rejection.
- [x] Assert metric labels use bounded enums/route templates, not questions, document names, IDs, or error strings; commit.

### Task 4: Backup and verified restore

**Files:**
- Create: `scripts/backup.py`, `scripts/restore.py`, `scripts/verify_restore.py`
- Create: `docs/runbooks/BACKUP_RESTORE.md`
- Test: `tests/system/test_backup_restore.py`

**Interfaces:**
- Produces encrypted/versioned PostgreSQL and object-store backup manifests and isolated restore verification.

- [ ] Seed a temporary stack with two projects sharing one blob and write expected row counts, grants, object hashes, and audit-chain endpoints.
- [ ] Verify backup/restore system test fails before scripts exist.
- [ ] Implement subprocess argument lists without shells, explicit destinations, checksums, schema/version manifest, encryption hook, and atomic completion marker.
- [ ] Restore into new database/bucket names and compare counts, authorization grants, hashes, and representative reports.
- [ ] Document schedule, retention, encryption-key custody, monitoring, and quarterly restore drill; commit.

### Task 5: Deployment, drain, migration, rollback, and incident runbooks

**Files:**
- Create: `scripts/deploy.py`
- Create: `docs/runbooks/DEPLOYMENT.md`, `ROLLBACK.md`, `INCIDENT_RESPONSE.md`, `USER_REMOVAL.md`
- Test: `tests/deployment/test_deploy_sequence.py`

**Interfaces:**
- Produces a deterministic deployment state machine.

- [ ] Write a failing test with recorded command executor asserting order: backup, drain, migrate, start, readiness, release workers.
- [ ] Implement explicit confirmation for production, bounded drain timeout, migration lock, health verification, and rollback eligibility check.
- [ ] Document compromised session revocation, provider outage, leaked secret rotation, failed migration, data restore, and user access removal.
- [ ] Run test-stack deployment and rollback rehearsal; commit.

### Task 6: Program 7 verification

- [ ] Build and scan the container image.
- [ ] Start the production-like stack and verify only HTTPS is externally reachable.
- [ ] Run two-user load smoke with ten simultaneous sessions and bounded jobs.
- [ ] Terminate web and worker containers independently and verify recovery behavior.
- [ ] Complete encrypted backup and isolated restore verification.
- [ ] Run all engineering, migration, security, browser, and scientific gates.
