# Data Maintainability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Address the approved maintainability findings without changing research semantics.

**Architecture:** Use standalone helpers for replay manifests and artifact validation,
and a single publication boundary for analyses. Make source identity and planner state
explicit while retaining compatibility with existing callers and serialized runs.

**Tech Stack:** Python 3.11+, pytest, Ruff, Pyright; existing isolated bubblewrap runner.

**Spec:** `docs/superpowers/specs/2026-11-12-data-maintainability-design.md`

## Global Constraints

- Preserve all prior working-tree changes and numerical/scientific contracts.
- Never bypass isolation, overwrite historical artifacts or relax benchmark labels.
- Existing cancellation and budget exceptions must propagate unchanged.
- No commits, deployment, external messages or new dependencies are required.

## Review Focus

- A legacy tabular ZIP must replay independently with its transitive modules.
- Symlinks, path traversal, missing files and mismatched hashes must fail consistently.
- Fresh and resumed runs retain source identity despite differing assessment/folder order.
- Normal, fallback and reassessment publication preserve distinct overlap rules.
- Internal exceptions cannot silently become source-unavailability conclusions.

### Task 1: Replay manifests and shared artifact validation

**Files:** `data_research/artifacts.py`, `reporting.py`, `derived_artifacts.py`,
`resume.py`, `execution.py`; new standalone manifest/validation helpers; focused tests.

**Interfaces:** One exported engine manifest used by packaging; one standalone
`validate_artifacts(root, artifacts)` helper that raises ValueError for invalid
paths/files/hashes and can be retained with the offline runner. Keep full runtime
inventory separate from explicit replay install dependencies.

- [x] Reproduce legacy export failure and divergent file-validation cases in tests.
- [x] Implement the shared manifest and validator, retaining old-run compatibility.
- [x] Verify standalone ZIP replay, source/derived tamper detection and resume.
- [x] Review the task independently before final integration.

### Task 2: Publication and explicit source/planner contracts

**Files:** `data_research/workflow.py`, `adaptive.py`, `source_review.py`, new
publication/source-state helpers and focused workflow/recovery tests.

**Interfaces:** One publication helper owns execute/persist/append/success transition;
callers supply explicit overlap policy. Source records receive stable IDs; an explicit
adapter resolves historical positional source indexes. Planner rounds consume a
snapshot provider, with a compatibility wrapper for existing generator callers.

- [x] Write tests pinning existing normal/fallback/reassessment behavior and policies.
- [x] Add stable source records and snapshot-based planning without changing decisions.
- [x] Centralize publication and preserve callback/test injection seams.
- [x] Verify reordered assessments, resume, partial source recovery and cancellation.
- [x] Review the task independently before final integration.

### Task 3: Error classification and test seams

**Files:** Workflow/recovery boundaries after Task 2; focused tests and fixture modules.

**Interfaces:** Expected source/review errors remain recoverable; unexpected internal
errors have an explicit category and technical diagnostics. Domain availability
statuses must not assert an internal failure is a source deficiency.

- [x] Reproduce injected internal TypeError/KeyError at source boundaries.
- [x] Preserve source failures and partial results while separating internal diagnostics.
- [x] Move shared builders out of test modules where necessary for changed contracts.
- [x] Verify cancellation and budget propagation; review final combined changes.

### Task 4: Integration verification

- [x] Run relevant unit/replay/resume tests, Ruff and targeted Pyright.
- [x] Run the complete suite with isolated integration services and stop those services.
- [x] Run retained scientific checks and report the existing rebound disagreement separately.
- [x] Record results and completion in this plan; leave changes reviewable locally.
