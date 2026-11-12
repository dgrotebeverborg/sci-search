# Scientific Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect authorized cumulative scientific knowledge and contextual researcher feedback to future web searches, with measurable retrieval benefit.

**Architecture:** A storage-independent memory interface has a legacy SQLite adapter and a production PostgreSQL graph projection. Revision/feedback stores remain the source of truth; graph ingestion is idempotent and recoverable. Start with deterministic feedback-aware retrieval, evaluated against the existing concept-matching baseline.

**Tech Stack:** Python protocols/dataclasses, existing PostgreSQL/SQLite and object stores, research pipeline, pytest, deterministic benchmark scripts.

**Spec:** [Design](../specs/2026-09-09-research-dashboards-memory-design.md), required experience 8 and memory architecture. Depends on [saved dashboards](2026-09-09-saved-dashboards.md) and [researcher feedback](2026-09-09-researcher-feedback.md).

## Global Constraints

- Keep domain and research code independent of HTTP, database, queue, identity-provider, and object-store implementations.
- Keep CLI commands and scientific_evidence_v1 and scientific_evidence_graph_v1 artifacts compatible until a documented migration retires them.
- Every protected read/write, graph traversal, feedback lookup, source link, and export must enforce project authorization.
- Do not claim improved learning without a held-out evaluation against the feedback-free baseline.

All remaining design constraints also apply.

## Task 3.1: Authorized memory contracts and graph storage

**Files:** Create `sci_search/application/memory.py`, `sci_search/infrastructure/sql_memory.py`, `sci_search/infrastructure/local_memory.py`, `tests/integration/test_memory_repository.py`, and `tests/security/test_memory_isolation.py`. Modify `sci_search/scientific_memory.py`, `sci_search/infrastructure/tables.py`, and add an additive Alembic migration.

**Interfaces:** Define `MemoryContext(user_id: str, project_id: str)` and `MemoryCandidate(publication: PublicationCandidate, base_score: float, feedback_score: float, explanations: tuple[str, ...])` as frozen dataclasses. `MemoryService.candidates(context: MemoryContext, plan: ResearchPlan, *, limit: int) -> tuple[MemoryCandidate, ...]`; `ingest_revision(context: MemoryContext, run_id: str, revision: int) -> dict[str, int]`. Also retain adapters for the existing manager's `assess`, `reuse_document`, `evidence_states`, `apply_lifecycle`, `cached_analysis`, and `cache_analysis` operations, using the signatures in ScientificMemory. Bind context once in the adapter rather than allowing arbitrary callers to change its scope.

- [ ] Test re-ingestion, canonical DOI aliases, duplicate documents, conflicting feedback by different researchers, withdrawn feedback, and unauthorized graph neighbors. Two projects can reference one stored document's bytes without gaining visibility into each other's questions, decisions, or private evidence.
- [ ] Add graph nodes/relationships for run/revision, question context, publication, document, passage, claim, entity/measurement, concept, and feedback event. Prefer existing canonical publication/document tables over duplicate identities. Store provenance, schema version, visibility grant, and source revision for each projected relationship. Use typed relation names and unique source-event keys.
- [ ] Implement ingestion as an idempotent projection of completed snapshots and append-only feedback. Example relationships:

```text
RUN --HAS_REVISION--> REVISION --ASKS--> QUESTION_CONTEXT
REVISION --CONSIDERED--> PUBLICATION --HAS_DOCUMENT--> DOCUMENT
CLAIM --SUPPORTED_BY--> PASSAGE --IN_DOCUMENT--> DOCUMENT
FEEDBACK --ABOUT--> PUBLICATION
FEEDBACK --IN_CONTEXT--> QUESTION_CONTEXT
FEEDBACK --MADE_BY--> RESEARCHER
```

- [ ] Bind authorization at every query/traversal and before source reuse. Visible workspace feedback may be retrieved only through existing membership grants. Do not turn personal decisions into globally visible labels. Deletion or revoked access removes eligibility immediately even if content-addressed bytes remain referenced elsewhere.
- [ ] Keep legacy SQLite memory readable; adapt it for CLI compatibility and local ownership. Append new contextual events to the stage-2 store; stop treating overwritten `RESEARCHER_DECISION` graph edges as the feedback history. Represent imported legacy events with unknown actors explicitly instead of inventing researcher identity.
- [ ] Run `uv run pytest tests/integration/test_memory_repository.py tests/security/test_memory_isolation.py tests/test_memory_ai.py -q`. The crucial assertion is:

```python
assert private_publication_id not in visible_candidate_ids
assert private_feedback_id not in visible_graph_event_ids
assert second_ingestion_counts["new_nodes"] == 0
```

## Task 3.2: Web memory reuse and recovery

**Files:** Modify `sci_search/infrastructure/research_execution.py`, `sci_search/infrastructure/local_research.py`, `sci_search/research_runs.py`, `sci_search/cli.py`, and stage-2 rebuild publication. Create `tests/integration/test_web_memory.py` and `scripts/import_scientific_memory.py`.

**Interfaces:** Extend `_manager(root: Path, *, memory=None)` to inject a context-bound manager-compatible adapter. Existing calls without memory remain valid. Production creates adapters per authorized job; local research binds its persistent owner/project. `ingest_revision` runs after successful publication through retryable durable work, never for a failed or partially published snapshot.

- [ ] Build a test that completes A, then starts related C through the actual web service with fake providers. Count provider/download/model calls. C should retrieve A's eligible cached paper and reuse its source bytes while still evaluating the new question. Opening A must make zero such calls.
- [ ] Inject adapters into default production and local factories. Preserve validated analysis cache keys over question, source/evidence hashes, active feedback, schema, model, and validator versions. Rejected or stale analysis must not be reused. Relevance decisions alone cannot change a claim to researcher-verified.
- [ ] Persist ingestion checkpoints keyed by `(project_id, run_id, revision, projection_version)`. Failed memory ingestion does not hide a successfully completed dashboard; it records recoverable pending work. Before a new search, contextual feedback reads consult the authoritative event store so projection lag cannot resurrect a withdrawn override.
- [ ] Implement `uv run python scripts/import_scientific_memory.py --source <legacy-root> --project-id <id> --dry-run`. Validate ownership, canonical IDs, source hashes and schema versions; report unknown provenance, preserve files, and make repeated imports no-ops. Do not automatically merge every user's legacy memory.
- [ ] Run `uv run pytest tests/integration/test_web_memory.py tests/test_memory_ai.py tests/system/test_dashboard_rebuild_recovery.py -q`. Verify source/model reuse, feedback change invalidation, retryable ingestion failures, and CLI artifact compatibility.

## Task 3.3: Contextual feedback ranking and honest evaluation

**Files:** Create `sci_search/feedback_ranking.py`, `tests/test_feedback_ranking.py`, `benchmarks/feedback_retrieval_v1.json`, and `scripts/evaluate_feedback_retrieval.py`. Modify `sci_search/application/memory.py`, candidate-screening integration in `sci_search/research_runs.py`, and dashboard studies/methods presentation.

**Interfaces:** `score_feedback(plan: ResearchPlan, events: list[dict]) -> dict[str, dict]` returns publication-keyed `{adjustment: float, explanations: list[str]}`. `rank_candidates(candidates: tuple[MemoryCandidate, ...]) -> tuple[MemoryCandidate, ...]` sorts by combined score with a stable canonical-key tiebreak. Resolve current authorized events before scoring.

- [ ] Create deterministic fixtures covering related questions, unrelated populations/outcomes, positive and negative feedback, Reset, repeated votes, and conflicting researchers. Split feedback and evaluation by question family; do not train and test on the same paraphrases.
- [ ] Implement a transparent initial rule: require matching mandatory subject dimensions and compatible explicit population/outcome constraints; otherwise adjustment is zero. Among eligible feedback, compute concept-set Jaccard similarity and require >=0.5. Use the latest non-reset event per actor/context/paper, with Include=+1, Exclude=-1, Background=0. Average weighted votes and clamp the adjustment to [-0.25, 0.25] of the normalized base score range. A reset removes that actor/context's contribution. Preserve contrary votes and show uncertainty.
- [ ] Apply this score to memory and externally discovered candidates after canonical deduplication, before ranking for acquisition. A similar-question exclusion cannot remove a paper outright or override current exact-run inclusion. Emit reasons citing authorized question/decision IDs, e.g. "Previously included for a related population/outcome." Record scoring version and explanation in run provenance. Keep automatic screening suggestions distinct from explicit researcher overrides.
- [ ] Add assertions such as:

```python
assert unrelated_adjustment == 0
assert reset_adjustment == 0
assert -0.25 <= related_adjustment <= 0.25
assert current_explicit_inclusion_survives_negative_related_feedback
```

- [ ] Run `uv run pytest tests/test_feedback_ranking.py tests/integration/test_web_memory.py tests/security/test_memory_isolation.py -q`. Then run `uv run python scripts/evaluate_feedback_retrieval.py --benchmark benchmarks/feedback_retrieval_v1.json --output /tmp/sci-search-feedback-scorecard.json` with ranking off/on. Output nDCG@10, recall@20, irrelevant selections, repeated corrections, source reuse, and per-question deltas. Do not label a synthetic test a real-world quality improvement.
- [ ] Keep ranking behind a configuration flag until a researcher-confirmed held-out set shows positive mean nDCG@10 delta, no aggregate recall@20 regression, no unrelated-question degradation, and all isolation/grounding tests pass. If the set is not yet available, ship durable feedback and memory reuse with ranking disabled and explicitly record that evaluation is pending. Model training and embeddings are separate future decisions, not prerequisites for this release.

## Task 3.4: End-to-end release and rollback

**Files:** Create `tests/system/test_dashboard_memory_workflow.py` and `docs/operations/research-memory-rollout.md`. Modify `README.md`, `docs/ARCHITECTURE.md`, `docs/runbooks/BACKUP_RESTORE.md`, and `docs/runbooks/ROLLBACK.md`.

- [ ] Exercise the complete deterministic scenario from the design: A/B saved, restart, reopen A, exclude/rebuild/reset, related C with explained feedback, unrelated D without inherited exclusion. Assert that dashboards, revisions, sources, exports and graph relationships remain correctly scoped.
- [ ] Verify backup/restore covers database/catalog and referenced objects; replay graph projection from revisions/events. Keep immutable revisions and event history during application rollback. Roll back feedback ranking independently; if rebuilding is disabled, show that decisions are saved but the visible dashboard is awaiting an update.
- [ ] Run the required CONTRIBUTING.md gates, including isolated integration services and Chromium. Record baseline failures separately from new failures; do not weaken coverage, provenance, or authorization checks.
- [ ] Produce the release evidence: browser walkthrough, restart/import rehearsal, test results, migration/rollback record, and feedback scorecard with dataset status. Mark any ranking gate that lacks researcher labels as pending rather than claiming learning is complete.
