# Online scientific discovery architecture

**Status:** implemented bounded vertical slice  
**Date:** 2026-08-17

## Research-run boundary

Online work is represented by a durable `ResearchRun`, not an ephemeral model conversation:

```text
question
  → transparent query plan
  → OpenAlex + Europe PMC + Crossref search log
  → DOI/title deduplication
  → concept-coverage screening ledger
  → bounded reference/cited-by expansion around screened seeds
  → bounded trusted open-full-text acquisition
  → immutable generated corpus manifest
  → existing provenance-aware passage analysis
  → cited report and corpus-scoped follow-ups
```

The run persists `run.json` for progress and final state, `discovery.json` for the complete candidate/acquisition ledger, `corpus/manifest.json` plus acquired documents, and `investigation.json` for the evidence report. Provider credentials are read from the environment and never serialized.

## Provider roles

- OpenAlex provides broad cross-domain works search, citation counts, OA status and structured/PDF content availability.
- Europe PMC adds life-science discovery and JATS full text from its open-access subset.
- Crossref improves DOI metadata coverage and provides an independent fallback candidate stream.

Provider failures are logged independently. One unavailable provider does not erase successful results from the others. Requests have timeouts, bounded page sizes and exponential retry for transient errors.

## Screening and acquisition

Candidates are deduplicated by normalized DOI, falling back to normalized title. Screening requires explicit coverage of planned question concepts; retracted works are excluded. Ranking combines concept coverage, query-strategy agreement, lexical overlap, full-text availability and a deliberately small citation signal. Citation counts cannot override topical mismatch.

Only candidates marked open access are eligible for automatic acquisition. Europe PMC JATS is preferred when a PMCID is present. OpenAlex GROBID/TEI is next, followed by an OpenAlex PDF fallback. Downloads are bounded to 50 MB, gzip is decoded, XML/PDF signatures are validated and unusable documents are retained as acquisition failures rather than evidence.

The GROBID parser retains Abstract, Methods, Results, Discussion and Conclusions headings. Figures, reference lists, acknowledgements and funding boilerplate are excluded from the textual evidence stream. The generated passage offsets are validated against this deterministic canonical text.

## User and agent behavior

The browser starts a run asynchronously and polls its persisted state while showing the active stage and counts. Once complete, it displays the final answer, citations, exact passages, full text, search strategies and candidate ledger. Suggested follow-ups query the frozen generated corpus. A new live question creates a separate evidence snapshot.

The ledger also functions as a human review queue. Include/exclude decisions are timestamped and persisted separately from automated screening. Excluding an acquired paper removes it from the generated manifest and recomputes the report. A rights-confirmed local full text can be attached to any candidate; accepted files are parsed, hashed, provenance-labelled and then trigger the same rebuild. Sci-Search never downloads around a paywall.

Researchers can download one active acquired document in its original local format, select an arbitrary subset, or export the complete active corpus. Multi-document exports are ZIP archives containing the documents, a provenance/licence manifest, and a rights notice. Excluded and metadata-only candidates cannot be downloaded from Sci-Search.

Generic reports include `synthesis`, a versioned deterministic structure containing only exact source-text claims with evidence IDs, evidence/study-design distributions, convergence clusters, numerical-comparability status, and explicit quality flags. Validation rejects a claim if its text is absent from a linked passage. This is the safe baseline for a future structured-output model adapter; no model is allowed to write unconstrained scientific prose into storage.

This is intentionally not an unbounded autonomous crawler. Research review uses at most 100 metadata results per query and 100 selected candidates, begins with up to 25 acquired full texts, and reassesses coverage in ten-paper batches up to a 50-paper cap. Deep review raises only the full-text cap to 100 and uses fifteen-paper continuation batches. Quick scan uses smaller metadata and citation bounds and stops at 10 full texts. Every run records whether it stopped on adequate coverage, consecutive no-yield batches, candidate exhaustion, acquisition-attempt exhaustion, or its safety cap.

## Evaluation and remaining gates

Automated tests cover query planning, provider normalization, DOI deduplication, domain concept thresholds, retraction-safe screening, OpenAlex abstract reconstruction, gzip/TEI decoding, section preservation, persistent artifacts, secret exclusion, grounded findings, dynamic full-text access and frozen-corpus follow-ups.

Discovery recall is evaluated separately from extraction correctness using a curated DOI bibliography. The first broad goat-foraging benchmark initially recovered 1/8 known papers. Phrase-concept de-duplication, transparent synonym facets, and a high-recall metadata bound raised discovery to 7/8 and automated selection to 6/8, meeting the predefined 75% discovery target. The remaining miss is retained in the evaluation output: a valid JSON report and well-grounded passages do not make the search exhaustive.

Live acceptance has been demonstrated in behavioural ecology and plant science. The next scientific-quality gates are:

1. benchmark discovery recall against published review bibliographies;
2. add researcher accept/reject/correct controls to the screening ledger;
3. traverse references and cited-by edges for seminal-source recovery;
4. add optional structured model-assisted query expansion and extraction behind validated schemas;
5. run iterative gap-driven discovery rounds with explicit budgets and stopping criteria;
6. evaluate answer synthesis, study-design classification and context association with domain reviewers.

Until those gates pass, online results should be described as a bounded, inspectable evidence search—not a systematic review or exhaustive statement about all literature.
