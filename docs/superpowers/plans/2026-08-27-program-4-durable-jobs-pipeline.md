# Program 4: Durable Jobs and Research Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace daemon-thread orchestration with restart-safe jobs and independently testable, checkpointed research stages.

**Architecture:** PostgreSQL owns job, lease, attempt, and checkpoint state; Redis/Dramatiq delivers wakeups. A stage runner claims a lease, loads versioned inputs, invokes one injected stage, commits its checkpoint and audit event, and enqueues the next stage.

**Tech Stack:** PostgreSQL, SQLAlchemy, Redis, Dramatiq, pytest, existing Sci-Search pipeline modules.

**Spec:** `docs/superpowers/specs/2026-08-27-multi-user-production-platform-design.md`

## Global Constraints

- Duplicate delivery must not duplicate evidence, artifacts, or external acquisition records.
- Cancellation and retry occur at explicit stage boundaries.
- Existing synchronous CLI research remains available through a compatibility runner.
- Every checkpoint records input fingerprint and implementation version.

---

### Task 1: Job state machine and persistence

**Files:**
- Create: `sci_search/application/jobs.py`
- Create: `migrations/versions/0004_jobs.py`
- Extend: `sci_search/infrastructure/repositories.py`
- Test: `tests/integration/test_jobs.py`

**Interfaces:**
- Produces: `JobStatus`, `Job`, `StageAttempt`, `JobRepository.create`, `claim`, `heartbeat`, `checkpoint`, `fail`, `request_cancel`, and `complete`.

- [x] Write failing table-driven tests for every valid transition and literal invalid transition.
- [x] Write lease tests using an injected clock: one owner, heartbeat extension, expired reclaim, stale owner rejection.
- [x] Implement schema and transactional compare-and-swap lease methods.
- [x] Add idempotency-key tests proving repeated start requests return one job.
- [x] Run focused tests and commit.

### Task 2: Queue adapter and worker recovery

**Files:**
- Create: `sci_search/infrastructure/queue.py`
- Create: `sci_search/worker.py`
- Test: `tests/integration/test_worker_recovery.py`

**Interfaces:**
- Produces: `JobQueue.enqueue(job_id, stage_name)` and `Worker.execute(job_id, stage_name)`.

- [x] Write a failing test delivering the same message twice and assert the stage side effect occurs once.
- [x] Write a failing test that kills execution after checkpoint commit but before acknowledgement; redelivery must advance without repeating the stage.
- [x] Implement Dramatiq Redis delivery with PostgreSQL claim/checkpoint authority.
- [x] Add bounded retry classification and dead-letter audit behavior.
- [x] Run Redis/PostgreSQL recovery tests and commit.

### Task 3: Extract versioned stage contracts

**Files:**
- Create: `sci_search/research/stages/base.py`
- Create: `sci_search/research/stages/planning.py`
- Create: `sci_search/research/stages/discovery.py`
- Create: `sci_search/research/stages/acquisition.py`
- Create: `sci_search/research/stages/analysis.py`
- Create: `sci_search/research/stages/reporting.py`
- Test: `tests/research/test_stage_contracts.py`

**Interfaces:**
- Produces: `StageContext`, `StageResult`, `ResearchStage.run(context)`, stable stage names, and explicit version strings.

- [x] Capture a current end-to-end run fixture and its hand-checked stage-relevant artifacts.
- [x] Write failing contract tests invoking desired stage classes with injected providers, repositories, clock, and blob store.
- [x] Move planning/discovery logic behind stages without changing serialized outputs; run current discovery tests.
- [x] Move acquisition/screening/study-matrix logic; run current full-text tests.
- [x] Move extraction/coverage/synthesis/report logic; run current scientific and reporting tests.
- [x] Keep `ResearchRunManager.run_sync` as a compatibility composition of the same stages.
- [x] Compare old fixture and staged output after removing only newly documented operational metadata; commit.

### Task 4: Cancellation, quotas, and backpressure

**Files:**
- Create: `sci_search/application/quotas.py`
- Extend: `sci_search/application/jobs.py`, stage runner
- Test: `tests/integration/test_job_limits.py`

**Interfaces:**
- Produces global, workspace, and per-user active/queued limits plus cooperative cancellation.

- [ ] Write failing tests for global saturation, per-user saturation, fair release after completion, and cancellation between acquisition iterations.
- [ ] Implement transactional quota reservations linked to job lifecycle.
- [ ] Add cancellation checks at every stage and inside bounded acquisition/gap-search loops.
- [ ] Verify cancelled jobs retain completed checkpoints and cannot publish later-stage artifacts.
- [ ] Run tests and commit.

### Task 5: Restart and parity acceptance

**Files:**
- Test: `tests/system/test_research_restart.py`
- Test: `tests/contracts/test_staged_run_parity.py`

**Interfaces:**
- Proves operational durability and scientific compatibility.

- [ ] Start a controlled multi-stage run, terminate the worker process during acquisition, and restart it.
- [ ] Assert the run completes, each published stage has one successful checkpoint, and document/evidence hashes are unique.
- [ ] Compare a representative legacy synchronous run with a durable staged run for question, evidence IDs, passages, adequacy, citations, and review content.
- [ ] Run the complete suite and commit.

### Task 6: Program 4 verification

- [ ] Run PostgreSQL/Redis worker integration tests including duplicate delivery and lease expiry.
- [ ] Run restart, cancellation, quota, and parity system tests.
- [ ] Run all existing scientific tests, Ruff, Pyright, coverage, migration, and package checks.
- [ ] Document queue draining, failed-job retry, cancellation, and rollback to synchronous compatibility mode.
