# Program 3: PostgreSQL Persistence and Blob Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PostgreSQL authoritative for multi-user metadata and store document bytes once through a content-addressed filesystem/S3 abstraction.

**Architecture:** Application services depend on repository protocols. SQLAlchemy implementations own transactions and project-scoped queries; Alembic owns schema evolution. `BlobStore` implementations never authorize access and expose only opaque keys plus verified metadata.

**Tech Stack:** SQLAlchemy 2, Alembic, psycopg 3, PostgreSQL, boto3, MinIO, pytest, testcontainers or Docker Compose integration profile.

**Spec:** `docs/superpowers/specs/2026-08-27-multi-user-production-platform-design.md`

## Global Constraints

- No protected repository lookup may omit `project_id` or an already-authorized global identity key.
- PostgreSQL transactions must atomically persist state and audit events.
- Blob keys are not access tokens; APIs authorize database grants before reads.
- Legacy import is repeatable, fingerprinted, and non-mutating by default.

---

### Task 1: Database foundation and initial migration

**Files:**
- Create: `alembic.ini`, `migrations/env.py`, `migrations/versions/0001_identity_projects.py`
- Create: `sci_search/infrastructure/database.py`, `sci_search/infrastructure/tables.py`
- Test: `tests/integration/test_migrations.py`

**Interfaces:**
- Produces: `Database`, `transaction()` context manager, and schema for identities, sessions, workspaces, memberships, projects, and audit events.

- [x] Write a failing integration test that upgrades an empty PostgreSQL database to head, downgrades one revision, and upgrades again.
- [x] Run the test against the integration database and verify missing Alembic configuration causes RED.
- [x] Implement naming conventions, UTC timestamps, foreign keys, unique `(issuer, subject)`, unique membership keys, optimistic versions, and append-only audit rows.
- [x] Add a test proving migration startup is explicit and normal application startup does not alter schema.
- [x] Run migration tests and commit.

### Task 2: SQL repositories and transaction boundaries

**Files:**
- Create: `sci_search/infrastructure/repositories.py`
- Test: `tests/integration/test_project_repositories.py`

**Interfaces:**
- Implements Program 2 identity, session, workspace, project, membership, and audit repository protocols.

- [ ] Write failing tests for provisioning idempotency, role updates, optimistic conflicts, session rotation, and atomic audit creation.
- [ ] Add a cross-project test proving a guessed project ID cannot retrieve membership or resources through repository methods.
- [ ] Implement SQLAlchemy repositories with explicit transactions and scoped selectors.
- [ ] Force a failure after the domain write but before commit; assert neither domain row nor audit event persists.
- [ ] Run focused and Program 2 suites, then commit.

### Task 3: Content-addressed blob contract

**Files:**
- Create: `sci_search/application/blobs.py`
- Create: `sci_search/infrastructure/filesystem_blobs.py`
- Test: `tests/application/test_blobs.py`

**Interfaces:**
- Produces: `BlobStore.put(stream, maximum_bytes) -> BlobRef`, `open(key)`, `stat(key)`, `delete(key)` and `BlobRef(sha256, size, content_type, key)`.

- [ ] Write failing tests proving identical bytes deduplicate, oversized streams abort without a visible partial blob, mismatched expected hashes fail, and keys contain no filename or project identifier.
- [ ] Implement streaming hashing, bounded temporary writes, atomic rename, and digest-derived opaque keys in `FilesystemBlobStore`.
- [ ] Test concurrent identical puts and verify one final object with the same `BlobRef`.
- [ ] Run the focused suite and commit.

### Task 4: S3/MinIO blob implementation

**Files:**
- Create: `sci_search/infrastructure/s3_blobs.py`
- Test: `tests/integration/test_s3_blobs.py`

**Interfaces:**
- Implements `BlobStore` using a private bucket and server-side multipart operations where appropriate.

- [ ] Reuse the behavioral blob contract suite against MinIO and verify RED before `S3BlobStore` exists.
- [ ] Implement bounded streaming upload, metadata verification, private object ACL assumptions, retry classification, and idempotent digest keys.
- [ ] Assert object URLs are never returned from domain/application APIs and pre-signed URLs are not used in version 1.
- [ ] Run filesystem and MinIO contract suites and commit.

### Task 5: Publication grants and evidence persistence

**Files:**
- Create: `migrations/versions/0002_research_storage.py`
- Extend: `sci_search/infrastructure/tables.py`, `repositories.py`
- Test: `tests/integration/test_research_storage.py`

**Interfaces:**
- Produces project-scoped publication, document-grant, run-document, evidence, validation-check, revision, and artifact repositories.

- [ ] Write failing tests proving one digest can be referenced by two projects while revoking one project does not revoke the other.
- [ ] Write concurrent-review tests proving optimistic version conflicts preserve both attempted audit events without overwriting accepted state.
- [ ] Implement schema and repositories; require authorization before resolving a blob key.
- [ ] Run migration, isolation, and storage tests and commit.

### Task 6: Legacy dry-run and idempotent import

**Files:**
- Create: `sci_search/compatibility/legacy_import.py`
- Create: `scripts/import_legacy_data.py`
- Test: `tests/integration/test_legacy_import.py`

**Interfaces:**
- Produces: `scan_legacy(root) -> ImportManifest` and `apply_import(manifest, target, blob_store) -> ImportResult`.

- [ ] Copy a minimal legacy SQLite/run fixture into a temporary directory and write expected publication, run, evidence, and hash counts by hand.
- [ ] Verify RED before importer implementation.
- [ ] Implement path containment, schema validation, source fingerprinting, dry-run default, explicit apply flag, and import ledger.
- [ ] Run the same import twice and assert the second adds zero rows/blobs and reports identical source fingerprints.
- [ ] Verify source files are byte-identical before and after import; run full suite and commit.

### Task 7: Program 3 verification

- [ ] Upgrade an empty database and a Program 2 schema to Alembic head.
- [ ] Run PostgreSQL, filesystem blob, MinIO, isolation, and legacy-import tests.
- [ ] Run the complete unit suite, Ruff, Pyright, package build, and dependency audit.
- [ ] Document database rollback and verify the previous application image can read the supported rollback schema.
