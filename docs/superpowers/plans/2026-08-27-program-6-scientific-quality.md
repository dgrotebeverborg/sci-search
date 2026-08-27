# Program 6: Scientific Quality and Model Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove leading-record model bias, make analysis providers interchangeable, add explicit risk-of-bias review records, and strengthen independent scientific validation.

**Architecture:** Deterministic selection creates a recorded evidence packet before any model call. Provider adapters receive only that packet and return one common schema that passes existing source-grounding validators. Human methodological judgments remain revisioned project records.

**Tech Stack:** Existing evidence models and validators, Python protocols/dataclasses, PostgreSQL repositories, pytest benchmarks.

**Spec:** `docs/superpowers/specs/2026-08-27-multi-user-production-platform-design.md`

## Global Constraints

- Model output never bypasses exact quote, evidence-ID, numerical, context, or answer-responsiveness checks.
- Deterministic extraction remains the visible fallback.
- Evidence selection must record included/excluded IDs and reasons.
- Risk-of-bias state is unknown until a reviewer records a judgment.

---

### Task 1: Diversity-aware evidence packet selection

**Files:**
- Create: `sci_search/research/model_evidence.py`
- Test: `tests/research/test_model_evidence.py`

**Interfaces:**
- Produces `select_model_evidence(evidence, adequacy, limits) -> EvidencePacket` with policy version, selected records, exclusions, and reasons.

- [x] Write hand-derived failing fixtures where the first twelve records come from one publication and later records contain a contradiction, limitation, different method, and negative direction.
- [x] Assert the packet respects record/token budgets while including publication and evidence-type diversity plus qualifying counterevidence.
- [x] Implement stable scoring and round-robin diversity with deterministic tie-breaking by evidence ID.
- [x] Add empty, one-publication, incomplete-coverage, and oversized-passage tests.
- [x] Run mutation-sensitive assertions for contradiction and publication-diversity branches; commit.

### Task 2: Provider-neutral analysis contract

**Files:**
- Create: `sci_search/application/analysis.py`
- Modify: `sci_search/mistral_analysis.py`
- Test: `tests/application/test_analysis_provider.py`

**Interfaces:**
- Produces `AnalysisProvider.analyze(question, EvidencePacket) -> AnalysisResult`; `MistralAnalysisProvider` implements it.

- [x] Write failing contract tests for success, provider error, malformed structure, invalid quote, unknown evidence, and empty grounded result.
- [x] Extract shared orchestration and preserve current Mistral JSON schema validation.
- [x] Record provider, exact model, packet policy, prompt contract, schema, validator, usage, rejected records, and fallback reason.
- [x] Update callers to use the selected `EvidencePacket`; remove the fixed `evidence[:12]` slice only after parity tests pass.
- [x] Run all Mistral, study-matrix, coverage, and memory-cache tests; commit.

### Task 3: Risk-of-bias review records

**Files:**
- Create: `sci_search/domain/risk_of_bias.py`
- Create: `migrations/versions/0005_risk_of_bias.py` (`0004_jobs` already existed)
- Extend review repository and API
- Test: `tests/domain/test_risk_of_bias.py`, `tests/api/test_risk_of_bias.py`

**Interfaces:**
- Produces versioned judgments with study, domain/tool, judgment, rationale, source evidence IDs, reviewer, timestamp, and revision lineage.

- [x] Write failing tests proving no judgment defaults to low risk and every non-unknown judgment requires rationale and a valid source reference.
- [x] Implement domain contract and optimistic revision persistence.
- [x] Enforce reviewer-or-higher mutation and viewer read permissions.
- [x] Add simultaneous-review conflict tests and audit assertions; commit.

### Task 4: Independent gold-label workflow

**Files:**
- Extend: `sci_search/validation_workspace.py`
- Create: `benchmarks/researcher_gold_v1.schema.json`
- Test: `tests/test_validation_workspace.py`, `tests/test_quality_benchmark.py`

**Interfaces:**
- Produces explicit labels for must-retrieve/exclude publications, key conclusions, counterevidence, distinctions, and answerability, with reviewer provenance.

- [ ] Write failing tests that prevent silver output or system-generated conclusions from being promoted without a named researcher review revision.
- [ ] Add schema validation and blinded independent reviewer capture.
- [ ] Report discovery recall, screening precision, grounding, unsupported assertions, conclusion coverage, context preservation, and disagreement separately.
- [ ] Keep zero unsupported assertions and complete provenance as independent hard gates.
- [ ] Run locked legacy and new benchmark suites; commit.

### Task 5: Scheduled provider and scientific regression protocol

**Files:**
- Modify scheduled CI workflow
- Create: `docs/SCIENTIFIC_RELEASE_PROTOCOL.md`
- Test: deterministic benchmark command coverage

- [ ] Define credential-scoped live cases, acquisition/model budgets, sanitization, immutable question versions, and artifact retention.
- [ ] Keep live outcomes informational until researcher-reviewed; never rewrite expected gold labels from current output.
- [ ] Document release blocking thresholds and manual reviewer sign-off.
- [ ] Run deterministic protocol commands and commit.

### Task 6: Program 6 verification

- [ ] Run model packet mutation tests and provider contract tests.
- [ ] Run risk-of-bias authorization and concurrent revision tests.
- [ ] Run all locked scientific, reliability, metamorphic, and validation benchmarks.
- [ ] Compare representative pre/post migration deterministic answers and provenance.
- [ ] Run full engineering gates and verify no model-invalid assertion enters persisted evidence or reports.
