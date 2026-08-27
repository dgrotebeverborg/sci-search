# Decisions

## D1 — Evidence records precede graph projection

**Status:** accepted  
**Date:** 2026-08-17

Sci-Search stores validated publication, statement, and contextual measurement records as its scientific memory boundary. A graph artifact is a derived projection and may not normalize, repair, or reinterpret evidence. This retains the strongest `sci-graph` graph-artifact rule while avoiding a graph database dependency in the first slice.

## D2 — A numerical result is a contextual evidence record

**Status:** accepted  
**Date:** 2026-08-17

A measurement includes a canonical metric and quantity, original value text, evidence and result types, technology/configuration/scale/boundary, conditions, assumptions, and exact passage provenance. A naked technology–metric–value edge is invalid.

## D3 — Comparability has three states

**Status:** accepted  
**Date:** 2026-08-17

Two measurements are `comparable`, `different_context`, or `insufficient_context`. Metric-specific energy profiles define required dimensions and tolerances. Missing context must not silently imply equality.

## D4 — Local full text before harvesting and infrastructure

**Status:** accepted  
**Date:** 2026-08-17

The first slice reads a local manifest and inspectable text files. Large-scale discovery, PDF parsing, Neo4j, vector search, and UI work wait until contextual extraction passes a manually reviewed real-paper evaluation set.

## D5 — Synthetic fixtures are never scientific evidence

**Status:** accepted  
**Date:** 2026-08-17

Bundled full texts are explicitly synthetic and validate software behavior only. CLI comparison output labels them. Real scientific conclusions require a rights-cleared, researcher-reviewed corpus.

## D6 — The primary product object is a question-first investigation

**Status:** accepted  
**Date:** 2026-08-17

A researcher begins with a scientific question. Sci-Search returns a `ResearchInvestigation` whose first layer is a concise evidence-backed answer, followed by coverage, findings, comparisons, exact evidence, full-text access, limitations, and follow-up questions. The evidence graph remains internal scientific memory; generated summaries never replace or detach underlying evidence records.

## D7 — Reviewed records, not raw candidates, drive researcher answers

**Status:** accepted  
**Date:** 2026-08-17

Automated extraction may propose candidates, but the real-corpus vertical slice exposes only records whose value, context, and source passage are represented in an inspectable review sidecar. A reviewed empty result set is meaningful: it prevents a percentage mentioned in a review, table, or unrelated technology section from being attached to the publication-level technology label. The extraction method and version remain visible in every evidence reference.

## D8 — Generic mode is extractive and refuses missing concept coverage

**Status:** accepted  
**Date:** 2026-08-17

For questions without a validated specialist analyzer, Sci-Search retrieves exact source passages and promotes only sentences present verbatim in those passages. Domain profiles expand terminology but do not change the generic evidence contract. Retrieval requires coverage of the question's concepts; an isolated topic match is insufficient. This trades recall for a lower risk of plausible but unsupported answers.

## D9 — Corpora remain explicit research scopes

**Status:** accepted  
**Date:** 2026-08-17

The researcher selects the local evidence corpus before asking a question. Sci-Search does not imply that absence from a ten-paper pilot means absence from science. Multi-corpus UI support demonstrates reusable architecture while keeping corpus coverage visible and auditable.

## D10 — Online questions create immutable, inspectable research runs

**Status:** accepted  
**Date:** 2026-08-17

Every online question produces a durable search plan, provider log, candidate ledger, acquisition ledger, generated corpus and investigation artifact. Follow-ups use the frozen corpus unless the researcher explicitly starts a new live search. This prevents the evidence base from changing invisibly between questions.

## D11 — Discovery candidates are not evidence

**Status:** accepted  
**Date:** 2026-08-17

Titles, abstracts and ranking signals are used for screening only. A candidate contributes researcher-facing evidence only after an open full text has been acquired, parsed and associated with exact passage provenance. Provider relevance and citation counts are never scientific confidence scores.

## D12 — Acquisition is open, bounded and provider-audited

**Status:** accepted  
**Date:** 2026-08-17

Automatic acquisition uses trusted Europe PMC or OpenAlex content services, requires open-access status, enforces document and run limits and records failures. Sci-Search does not bypass paywalls or silently substitute an abstract for unavailable full text.

## D13 — Citation expansion is bounded and remains subject to screening

**Status:** accepted  
**Date:** 2026-08-17

Top metadata candidates seed at most two reference/cited-by hops with explicit seed, direction, depth, and provider logs. Citation proximity is a discovery signal, not evidence of relevance or scientific support; every neighbor is screened normally and can remain excluded.

## D14 — Researcher decisions rebuild scientific memory

**Status:** accepted  
**Date:** 2026-08-17

Human include/exclude decisions are audit records layered over automated screening. They change the generated corpus and rerun evidence analysis. Authorized local full texts are hashed and provenance-labelled; access confirmation does not imply that Sci-Search redistributes the document.

## D15 — Synthesis cannot detach claims from evidence

**Status:** accepted  
**Date:** 2026-08-17

The baseline structured synthesis promotes only exact source sentences and validates every claim/evidence link. It reports distributions and quality flags rather than a universal score. The optional model-assisted synthesis now satisfies the same contract through evidence-ID, exact-quote, entity-span, and numerical-context validation before output can enter scientific memory.

## D16 — Publication exports follow the active evidence corpus

**Status:** accepted  
**Date:** 2026-08-17

Single and multi-publication downloads are limited to files present in the active generated manifest. Excluded and metadata-only candidates are ineligible. ZIP exports retain original local formats and include DOI, source, access-status and licence metadata; researcher-supplied documents retain their authorized-source provenance.

## D17 — Model synthesis is optional and fails closed

**Status:** accepted  
**Date:** 2026-08-17

Mistral receives bounded evidence passages and must return the API-enforced Sci-Search JSON contract. Every retained assertion cites known evidence IDs and exact source quotes; entities, values, units, and conditions must be recoverable from those quotes. Invalid records are rejected independently. A provider failure, malformed response, or response without any grounded answer or claim preserves the deterministic extractive answer. Only validated output may become claim, entity, or measurement nodes.

## D18 — Scientific memory accumulates evidence, not truth

**Status:** accepted  
**Date:** 2026-08-17

Completed online runs populate a cumulative SQLite provenance graph and content-addressed document cache. Later questions may reuse publication metadata, full texts, and identically keyed validated analyses. Reuse improves speed and coverage but does not increase scientific confidence by itself. Nodes and edges retain run, publication, passage, evidence, extraction, citation, and researcher-decision provenance.

## D19 — Operational depth is progressively disclosed

**Status:** accepted  
**Date:** 2026-08-17

The default report shows the answer, findings, source evidence, limitations, and follow-up questions. Screening, downloads, search details, scientific-memory statistics, model provenance, and diagnostics remain accessible in one collapsed Research details panel. Live-search settings appear only when live search is selected.

## D20 — Analysis representation and researcher download may differ

**Status:** accepted  
**Date:** 2026-08-17

Sci-Search preserves the acquired scholarly artifact and does not present generated text as the original publication. When both structured XML and an open-access PDF are available, XML is the analysis representation and PDF is the download representation. The manifest and cumulative cache retain both paths and their sources. JATS XML and researcher-authorized files remain in their acquired formats when no separate PDF is available.

## D21 — Full-text scale uses adaptive review profiles

**Status:** accepted  
**Date:** 2026-08-17

Online runs default to **Research review**: acquire an initial set of up to 25 full texts, assess question coverage, and continue in ten-paper batches only while important coverage is missing. It has a 50-paper safety cap. **Quick scan** is exploratory and capped at 10; **Deep review** begins at 25 and can continue to 100. Research and Deep reviews can stop because coverage was achieved, consecutive batches added no new contributing publications, the screened candidate pool was exhausted, acquisition attempts were exhausted, or the safety cap was reached. This is not a completeness claim. The profile, batch assessments, stopping criterion, target, actual acquisitions, access failures, and inclusion decisions remain in run provenance and the cited review.

## D22 — A generated review is a cited evidence artifact, not a systematic-review claim

**Status:** accepted  
**Date:** 2026-08-17

Every completed online run can produce HTML, Markdown, and JSON cited-review artifacts. Conclusions carry evidence IDs and numbered publication references; appendices retain search queries, selection counts, exclusions, exact passages, extraction methods, and rejected model records. The artifact identifies itself as an AI-assisted evidence review and states that formal protocol registration, comprehensive database coverage, dual independent screening, and study-specific risk-of-bias appraisal have not yet been completed.
