# Program 8: Migration, Storage Lifecycle, and Legacy Retirement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate retained research data safely, reclaim duplicate storage, remove obsolete runtime paths, and prove the complete platform meets production acceptance criteria.

**Architecture:** Inventory and import are read-only/idempotent first. A parity gate compares legacy and new records before traffic cutover. Reference-counted garbage collection and legacy removal occur only after backup/restore and rollback windows pass.

**Tech Stack:** Existing legacy artifacts/SQLite, PostgreSQL, S3/MinIO, migration manifests, pytest system tests.

**Spec:** `docs/superpowers/specs/2026-08-27-multi-user-production-platform-design.md`

## Global Constraints

- Never delete legacy data during inventory, dry run, import, or parity validation.
- Every imported row and blob traces to a source fingerprint and import manifest.
- Garbage collection defaults to dry run and deletes only zero-reference objects older than the configured grace period.
- Legacy runtime removal follows a successful production rollback window and explicit owner approval.

---

### Task 1: Complete legacy inventory and classification

**Files:**
- Extend: `sci_search/compatibility/legacy_import.py`
- Create: `scripts/inventory_legacy_data.py`
- Create: `docs/migration/LEGACY_INVENTORY.md`
- Test: `tests/integration/test_legacy_inventory.py`

**Interfaces:**
- Produces deterministic JSON manifest of runs, corpora, memory rows, documents, hashes, sizes, references, unreadable files, and conflicts.

- [x] Create a fixture with duplicated blobs, conflicting publication metadata, incomplete run JSON, and an unreadable document; write expected counts/hashes by hand.
- [x] Verify inventory test fails before behavior exists.
- [x] Implement bounded traversal, path containment, content hashing, schema classification, and error collection without mutation.
- [x] Run inventory twice and assert byte-identical manifests; commit.

### Task 2: Production import and parity reports

**Files:**
- Extend: `scripts/import_legacy_data.py`
- Create: `scripts/compare_legacy_parity.py`
- Test: `tests/system/test_production_import.py`

**Interfaces:**
- Produces resumable import batches and parity report for publications, runs, documents, evidence, reviews, artifacts, and hashes.

- [ ] Write a failing interrupted-import test that stops after a fixed batch and resumes without duplicates.
- [ ] Implement import ledger checkpoints and explicit conflict policies that preserve source variants rather than silently merging disagreement.
- [ ] Compare counts, stable identifiers, evidence passages/offsets, review histories, and blob hashes.
- [ ] Fail parity on unexplained loss; permit only documented transformations with per-record mappings.
- [ ] Run system import against a protected copy of the current data tree and commit code plus sanitized summary, not source publications.

### Task 3: Reference-counted garbage collection

**Files:**
- Create: `sci_search/application/retention.py`
- Create: `scripts/storage_gc.py`
- Test: `tests/integration/test_storage_gc.py`

**Interfaces:**
- Produces `plan_gc(now, grace_period) -> GCPlan` and `apply_gc(plan_id, confirmation) -> GCResult`.

- [ ] Write failing tests for shared blobs, revoked grants, active exports, temporary files, grace periods, stale plans, and concurrent new references.
- [ ] Implement a transactionally recorded dry-run plan with object digest, reason, size, reference count, and cutoff.
- [ ] Recheck references and plan version immediately before each bounded deletion batch.
- [ ] Assert shared/re-referenced objects survive and audit events record deletion metadata without bytes.
- [ ] Run storage tests and commit.

### Task 4: Cutover and rollback rehearsal

**Files:**
- Create: `docs/migration/CUTOVER.md`
- Test: `tests/system/test_cutover.py`

**Interfaces:**
- Produces operator checklist and executable acceptance evidence.

- [ ] Restore the latest backup into a staging stack and run the import/parity report.
- [ ] Authenticate two OIDC test subjects, verify private/shared projects and roles, and run simultaneous research jobs.
- [ ] Drain legacy writes, perform final incremental import, switch traffic, and verify readiness and audit events.
- [ ] Rehearse rollback within the compatibility window and verify no new source data is lost.
- [ ] Record measured timings, thresholds, responsible role, and go/no-go checks; commit documentation.

### Task 5: Retire obsolete runtime paths

**Files:**
- Remove after approval: legacy `http.server` handler, daemon-thread start path, production SQLite writes, embedded `RESEARCHER_UI` string
- Preserve or adapt: CLI compatibility and legacy read-only import modules
- Test: contract, migration, browser, and full regression suites

**Interfaces:**
- Makes FastAPI, durable jobs, PostgreSQL, and blob storage the only production runtime path.

- [ ] Write tests proving production configuration cannot instantiate the legacy server/thread/SQLite runtime.
- [ ] Verify RED while legacy selection remains possible.
- [ ] Remove production selection paths and imports; keep explicit read-only migration tooling.
- [ ] Run artifact/CLI compatibility tests and document any versioned deprecation rather than silently changing formats.
- [ ] Run full suite and commit.

### Task 6: Final platform acceptance

- [ ] Execute every acceptance item in the master roadmap with captured command output.
- [ ] Run formatting, linting, typing, coverage, packaging, migrations, dependency audit, container scan, API security, browser, worker recovery, backup/restore, and scientific validation suites.
- [ ] Verify a SURFconext test-environment login and stable `(issuer, subject)` identity mapping.
- [ ] Verify cross-project denial for reads, writes, uploads, reviews, downloads, exports, jobs, and audit endpoints.
- [ ] Verify worker restart produces no duplicate evidence or artifacts.
- [ ] Verify content deduplication and project-scoped grants after migration and garbage collection.
- [ ] Obtain explicit repository-owner approval before deleting retained legacy copies after the rollback window.
- [ ] Tag the production release only after all evidence is attached to the release checklist.
