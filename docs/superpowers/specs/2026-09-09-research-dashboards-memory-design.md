# Saved research dashboards and scientific memory

Date: 2026-09-09. Status: implemented and verified; feedback-ranking activation awaits researcher-confirmed evaluation. See the execution record for implementation choices.

## Product outcome

Every submitted question becomes a durable entry in the left sidebar. Selecting an entry opens a complete interactive scientific dashboard, with the same content and layout as when the search finished. All searches remain accessible, including failed, cancelled, and incomplete searches. New searches never replace earlier ones.

Researcher decisions about article relevance rebuild the affected dashboard and become contextual feedback for future research. The app accumulates source-linked scientific knowledge and improves retrieval using measured feedback, without treating a relevance vote as proof of scientific correctness.

## Current evidence from the repository

- `frontend/static/runs.js` keeps one run per project in a JavaScript Map. There is no durable sidebar history in this flow.
- `frontend/templates/app.html` exposes evidence, validation, and downloads, but not the complete literature-review and landscape presentation.
- `infrastructure/local_research.py` retains research files but keeps projects, run associations, and exported-record associations in memory. Its evidence/export lists select the latest run.
- `infrastructure/tables.py` already has production projects, research runs, documents, evidence, artifacts, and review revisions. Build on these tables.
- `research_runs.py:review_candidate` saves include/background/exclude/reset decisions and rebuilds evidence, synthesis, study matrix, landscape, and literature review. This mutates current local artifacts and needs revision-aware adaptation.
- The workspace's accept/reject controls review individual evidence records and do not invoke article-level rebuilding.
- `scientific_memory.py` implements a SQLite node/edge graph, document reuse, validated analysis caching, and evidence review revisions. Article decisions are upserted as graph edges; this is not a complete append-only feedback history.
- `cli.py` supplies ScientificMemory for research-online. The default web `_manager` in `infrastructure/research_execution.py` does not supply it.
- Memory candidate ranking currently scores concept coverage, without consulting article relevance feedback.

## Required experience

1. The left sidebar lists searches in the selected project, newest first, with question, date, status, and text filtering. Project switching retains separation. Pagination prevents older research from disappearing.
2. Each search has a stable URL containing project and run identifiers. Opening that URL after login, refreshing, restarting the server, or returning in a new session restores the dashboard without another scholarly search or model call.
3. Fresh completion and reopening use one renderer and one versioned structured dashboard contract. Persist scientific content and layout version; transient expanded panels and filters need not survive a new session in the first release.
4. Dashboard blocks include question/scope, answer and adequacy, cited literature review, findings and themes, comparisons and measurements, research landscape, study matrix and screening, gaps/limitations/follow-ups, methods and search coverage, evidence and source passages, validation/review status, references, and downloads. Inventory existing outputs and retained examples before implementation; preserve any additional existing block. Empty or unsupported blocks explain why content is unavailable.
5. Citations open the supporting passage and original document. Landscape selections filter the corresponding paper list. Study/evidence lists offer expansion and filtering. The dashboard reads as a coherent explanation of the question.
6. Paper controls are Include, Background, Exclude, and Reset. Save question, paper identity, actor, scope, decision, reason, timestamp, and the version reviewed. Distinguish article relevance from accepting or rejecting an evidence claim.
7. Accepted relevance changes automatically schedule a rebuild. Keep the last complete revision visible with an updating status. On failure, keep it visible with a retry action. Publish the rebuilt dashboard and its exports atomically. Older revisions remain inspectable.
8. Future searches use authorized prior papers and contextual feedback. Exact applicable overrides govern the current search; feedback from similar questions is an explained ranking/screening suggestion, never a global blacklist.

## Architecture decisions

Use existing PostgreSQL and object storage in production. Store indexed identities, relationships, permissions, run/revision metadata, and feedback in relational tables; store complete dashboard snapshots and source bytes as immutable objects. A dedicated graph service is outside this first implementation. Keep the graph model explicit so a future projection is possible.

Provide the laptop demo with a durable SQLite catalog and filesystem artifacts behind the same application contracts. Retain loopback-only development login and recreate sessions on login; persist stable ownership, workspaces, projects, runs, and revisions. Do not silently make the deliberately temporary preview durable. The CLI's existing SQLite scientific memory remains compatible through an adapter.

A saved run has zero or more immutable dashboard revisions, one current completed revision, and a feedback sequence. A revision records schema/layout/generator versions, source hashes, configuration, feedback sequence, and parent revision. Feedback is append-only; Reset appends an event withdrawing the active override. Background means context-only in the new workflow: it must not silently supply direct support for primary conclusions. Test this change explicitly because existing screening includes background in the active extraction corpus.

Distinguish discovered literature from evidence included in synthesis. The landscape defaults to the discovered population, visibly labels it, and offers an included-evidence filter. Excluding a paper changes included counts and synthesis but does not erase it from discovery history.

Rebuild from retained source documents and acquisition/screening records. Missing or unreadable full text yields an explicit unavailable state, not fabricated evidence. Inclusion itself does not bypass acquisition or grounding rules. Rebuilds may rerun validated model synthesis; opening a saved dashboard must not. Explicit search refresh is a new run linked to the previous one.

Rebuild jobs capture a feedback sequence. If newer feedback arrives, an older job cannot replace the current dashboard with stale results. Enqueue feedback and rebuild work transactionally through the existing durable-job infrastructure. Local mode persists pending work and recovers it on startup. Coalesce rapid changes while preserving every feedback event.

Memory relationships connect questions/runs/revisions, publications, documents, passages, claims, measurements, concepts, and decisions. Scope protected knowledge and feedback to the personal/project/workspace permissions already granted. Shared workspace learning is allowed only within that visibility. App-wide use of private feedback is not enabled by default.

## Global constraints

- Python >=3.11; keep the existing FastAPI, SQLAlchemy, PostgreSQL, Dramatiq, Jinja, and vanilla JavaScript stack.
- Preserve exact source passages, deterministic validation, and explicit answer withholding.
- Keep CLI commands and scientific_evidence_v1 and scientific_evidence_graph_v1 artifacts compatible until a documented migration retires them.
- Keep domain and research code independent of HTTP, database, queue, identity-provider, and object-store implementations.
- Use deterministic synthetic providers and model outputs in automated tests; no live paid calls.
- Preserve existing uncommitted work; never reset or stage unrelated changes.
- Every protected read/write, graph traversal, feedback lookup, source link, and export must enforce project authorization.
- Opening a saved dashboard must not execute research or model analysis.
- Do not claim improved learning without a held-out evaluation against the feedback-free baseline.

## Delivery and acceptance

Deliver three independently testable increments: saved dashboards; feedback-driven revisions; contextual scientific memory. Dashboard persistence is the first priority and does not depend on finishing memory ranking.

Final demonstration: complete questions A and B; restart; reopen A from the sidebar with every block and source link intact; exclude one of A's supporting papers; observe a new consistent revision while B remains unchanged; reset the exclusion; run related question C and inspect authorized prior-feedback explanations; run an unrelated question and prove A's exclusion is not applied globally.

Existing artifacts must be inventoried and imported idempotently with explicit ownership. Files with missing metadata appear as incomplete recoverable entries; unassignable ownership is reported instead of guessed. Preserve original files. Rollout uses additive migrations and separate flags for dashboards, rebuilding, and feedback ranking; disable a failing stage without deleting history.
