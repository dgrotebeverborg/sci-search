# Saved scientific dashboard contract

`build_dashboard(investigation, *, run_id, revision)` copies the retained investigation into `research_dashboard_v1`, layout version 1. It performs no discovery, model inference, filesystem reads, or network requests. Opening a dashboard uses the same renderer as a newly completed run. Unknown or absent material remains explicit through `ready`, `empty`, and `unavailable` block statuses and server explanations.

| Block | Retained source | Interaction |
|---|---|---|
| Question and scope | question, question_brief, research_scope, plan, review scope | Read scope dimensions and decomposition |
| Answer and adequacy | answer_adequacy, synthesis, review executive_summary | Source-evidence anchors, explicit adequacy limitations |
| Literature review | literature_review_report (not its artifact descriptor) | Cited thematic sections, expandable appendices |
| Findings and measurements | synthesis.claims, findings, review thematic_findings/measurements | Evidence anchors and numerical context |
| Comparisons | comparisons, synthesis convergence_clusters/comparability, measurements | Read group and measurement detail without inferred comparability |
| Research landscape | research_landscape, discovered candidate/study ledger | Keyboard-operable timeline bars, year filter, discovered/included selector, tabular study list, author/organization/type/provider/trend panels |
| Studies and article relevance | study_matrix plus every discovered candidate | Study filter; Include/Exclude/Background/Reset with optional reason; expandable exact passages and dimensions; original source link |
| Gaps and limitations | review quality, synthesis quality_flags, follow_up_questions | Read limitations and future questions |
| Methods and selection | review methodology/selection_flow, research_run | Expand search and screening ledger |
| Source evidence | evidence | Expand exact quotation, identifiers, offsets, validation and source document |
| Validation | validation, synthesis.validation, evidence validation/review states | Inspect preserved deterministic checks |
| References | review references | Authorized original publication links or retained public URLs |
| Downloads | service-supplied revision artifacts | Download displayed revision's files |

Application services supply authorized `artifacts: [{id,filename,url,content_type}]` and `documents: {publication_id: {url,title}}`, plus `evidence_reviews: {source_evidence_id: {id,version,review_decision,review_note}}`, `role`, `current_revision`, `feedback_sequence`, `effective_decisions`, and `rebuild_status`. Storage paths in the retained investigation are never converted to client URLs. The UI uses text nodes for quotations and only HTTP(S) links.

History routes use project authorization and stable `/app?project=…&run=…&revision=…` URLs. Browser generation checks and abort signals stop stale dashboard responses from replacing a later selection. Finding review uses the runtime evidence identity and optimistic version independently of article relevance. Article feedback writes send the displayed revision and sequence and one stable idempotency key; a conflict leaves the decision form visible. Earlier revisions disable feedback. Pending rebuilds retain the completed revision; all blocks switch together after publication. Failed rebuilds expose a retry control for reviewers/owners.

A dedicated graph database is not needed to render these snapshots. Scientific-memory retrieval explanations are retained in study fields and shown with relevance context when provided by the pipeline.
