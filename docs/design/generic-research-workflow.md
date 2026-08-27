# Generic question-to-evidence workflow

**Status:** implemented cross-domain proof  
**Date:** 2026-08-17

## Product boundary

Sci-Search now accepts arbitrary questions over a selected, local full-text corpus. It plans the question, selects an optional domain profile, retrieves passages, extracts source-reported statements, and produces a progressively disclosed report:

```text
question → transparent research plan → passage retrieval
→ exact source-reported evidence → optional validated model synthesis
→ cited summary and findings
→ passage/full-text inspection → contextual follow-up question
```

The answer is deliberately conservative. Generic mode always retains an extractive evidence navigator and is not an autonomous Scientist Agent. When Mistral is configured, its structured synthesis is shown only after local exact-quote, evidence-ID, entity-span, and numerical-context validation. A failure returns to the extractive answer. When required question concepts are not represented in the corpus, it returns insufficient evidence.

## Separation of concerns

- The generic core owns publications, passages, question plans, provenance, evidence records, reports, and evaluation.
- Domain profiles contribute vocabulary expansion and comparison dimensions without changing the evidence contract.
- The energy specialist remains responsible for validated contextual numerical comparison.
- The model adapter proposes structured interpretations but cannot write unrestricted prose into scientific memory.
- The cumulative memory owns publication de-duplication, cached full texts, run/evidence/claim/entity/measurement nodes, and provenance edges.
- The web layer selects a corpus, preserves session history, and renders progressively deeper evidence; it does not create scientific facts.

Every generic evidence record contains publication and source-document identifiers, section and page where available, exact passage and character offsets, the selected source sentence, evidence/study classification, retrieval terms and score, extraction method, DOI, and source URL.

## Cross-domain proof

The `goat_foraging` corpus contains ten real open-access JATS full texts. Its four-question gold set checks seven expected source passages across vegetation, season, and feed-preference questions plus one deliberately unsupported lunar-geology question. Evaluation also fails on findings without evidence IDs or passage offsets that do not reproduce the canonical source.

This proves that the product is no longer hard-coded to its original iron-air question. Adding a new domain currently requires a local manifest/full-text corpus and, when useful, a small vocabulary profile and manually inspected gold questions.

## Honest limitations and next production gates

Lexical retrieval cannot yet resolve every synonym, implicit relationship, table, figure, or cross-document citation chain. Evidence-type classification combines manifest metadata with inspectable lexical cues. Model synthesis can organize supported disagreement, methods, assumptions, and gaps, but it does not perform statistical pooling, establish causality, or assign a universal evidence score.

The next production gates are semantic/hybrid retrieval, a human review queue for model candidates, more diverse gold corpora, stronger citation-origin tracing, and specialist analyzers for additional scientific result types. Those should be evaluated before large-scale harvesting or an autonomous Scientist Agent is added.
