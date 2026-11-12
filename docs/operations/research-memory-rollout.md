# Scientific memory rollout and recovery

Every project has an independent scientific-memory scope. Local research uses
`<research-root>/<project-id>/memory`. Production retains graph nodes, edges and
revision checkpoints in PostgreSQL (`memory_nodes`, `memory_edges`,
`memory_checkpoints`). `memory_states` references an immutable content-addressed
metadata checkpoint and individually stored source documents in the configured
blob store. Workers materialize an ephemeral SQLite working copy to reuse the
established extraction and graph engine; worker-local files are not production
persistence. A project row lock serializes checkpoint publication so concurrent
searches cannot overwrite each other's graph updates. Source bytes can deduplicate
across projects without exposing any project's questions or feedback.

Run the additive migrations through `0009_memory` before deploying the worker.
No global CLI memory is automatically imported into a user account. Every worker
memory read, source reuse, graph view and publication checks current membership;
revocation/deletion immediately removes eligibility. Feedback reads consult the
authoritative project event store, so a stale graph projection cannot revive a
withdrawn override. Validated analysis keys include question, model, source and
evidence fingerprints, validation/review state, active feedback history and the
analysis contract. A relevance vote does not validate a scientific claim.

## Publication and retry

The research engine queues graph ingestion while assembling a result. Publish the
immutable dashboard first, then call `publish_pending(revision=...)`. A failed
production projection leaves a pending checkpoint without removing the saved
dashboard. Before a subsequent search, `recover_project_memory` replays up to 25
missing/pending checkpoints from authorized retained revision archives. Missing
checkpoints cover crashes between dashboard commit and memory publication.
Recovery does not contact scholarly providers or language models. Legacy
revisions without retained archives are marked unavailable and skipped. Repeated
failures retain pending status, attempt time and exception class; unattempted
work and the oldest retry attempts receive priority so failures cannot starve
newer research. Replaying an older revision records its checkpoint/history
without overwriting a newer scientific projection. There is
no standalone periodic projection scheduler in this version; new searches
trigger recovery.

Back up PostgreSQL and all objects referenced by dashboard archives, artifacts,
documents and `memory_states.manifest_json` together. Retention checks include
memory object references. Restoring just worker directories is insufficient.
Restore the database and objects, then replay pending revisions. Source reuse
verifies content hashes; corruption causes a cache miss or explicit integrity
failure instead of evidence reuse.

## Legacy import

First verify the legacy store's owner and create `.memory-owner.json` in that
source with `{"project_id":"...","user_id":"..."}`. This is an explicit operator
attestation, not inferred identity. Then inspect a read-only dry run:

```sh
uv run python scripts/import_scientific_memory.py --source /verified/legacy-memory \
  --project-id PROJECT --destination data/project-memory --dry-run
```

Without the attestation the tool reports unknown ownership and imports nothing.
Hash or scope mismatches fail validation. Remove `--dry-run` only for a verified
empty destination. Repeated identical imports are no-ops. The tool refuses to
replace a populated project; merging populated projects requires authorized
revision replay. Historical unknown actors remain unknown and do not become
ranking votes. Source files are preserved. This is a local legacy adapter import;
production memory is populated from published authorized dashboard revisions.

## Feedback ranking and evaluation

`SCI_SEARCH_FEEDBACK_RANKING_ENABLED` defaults to disabled. Explicit article
feedback still rebuilds the current dashboard when ranking is disabled. The
optional ranker only changes acquisition order among already selected candidates;
it does not exclude a paper or change a current explicit include decision. It
requires compatible subjects/populations/outcomes and concept similarity,
averages the latest actor/context votes, caps adjustments at 0.25 and retains
contrary explanations. Reset withdraws that actor's prior vote. A conservative
rule dictionary recognizes explicit common population/outcome constraints;
researcher labels are required before expanding or enabling this policy.

```sh
uv run python scripts/evaluate_feedback_retrieval.py \
  --benchmark benchmarks/feedback_retrieval_v1.json \
  --output /tmp/sci-search-feedback-scorecard.json
```

The committed fixture is **synthetic plumbing coverage**, not evidence of quality
improvement. The scorecard compares nDCG@10, recall@20, irrelevant selections,
repeat-correction proxies and source reuse counts for ranking off/on. A
researcher-confirmed held-out dataset and unrelated-question regression gate are
still required before enabling ranking. No model training is performed.

## Rollback

Disable `SCI_SEARCH_FEEDBACK_RANKING_ENABLED` independently to restore baseline
ordering while preserving feedback and memory. An application rollback should
retain additive dashboard/feedback/memory tables and objects. Do not downgrade
through `0008_dashboards` on a user database: it would discard saved revision and
feedback history. For a schema rollback rehearsal use only the disposable
`sci_search_test` database, retain a full backup, and restore or replay projections
before enabling workers again.
