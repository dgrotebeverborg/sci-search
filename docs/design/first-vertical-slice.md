# Contextual Iron-Air Evidence Slice

Extract and compare round-trip-efficiency results while preserving the context needed for scientific verification.

**Status:** implemented and evaluated real-corpus slice  
**Date:** 2026-08-17  
**Decisions:** D1–D5

## Sci-Graph audit

The checked-out `sci-graph` branch contains dependency-free domain records, a minimal HTTP server, a Pure API source contract, a publication scientific profile, deterministic extraction, and tests. Its archived later prototype adds Pure harvesting/mapping, local full-text resolution, Mistral JSON extraction, vocabulary review, source-fragment repair, statement-quality gates, organization profiles, graph export, optional Neo4j import, browser builder/explorer surfaces, and a gold-set evaluation harness.

The useful architectural sequence is:

```text
source document → structured extraction profile → validation/normalization
→ durable artifact → graph projection → query
```

Its most important reusable rules are explicit provenance, publication-level extraction artifacts, deterministic identifiers, model output validation, separating rejected candidates from graph-safe records, a non-interpretive graph-import boundary, and evaluation of hallucination/span faithfulness.

The parts not carried forward are organization-first aggregation, Pure as the mandatory backbone, large preview/presentation modules, the embedded builder/explorer UI, early Neo4j coupling, and flattened content nodes that cannot represent contextual numerical results. The archived code also has dependency cycles between source loading, previews, OpenAlex enrichment, and vocabulary candidates; Sci-Search keeps these directions separate.

## Minimal architecture

```text
generic scientific core
  Publication, Provenance, Statement, MeasurementResult, EvidenceType
                    ↑
energy profile
  metric aliases, units, required context, comparison tolerances
                    ↑
extraction boundary
  local document → structured ExtractionBundle
                    ↓
validated EvidenceStore → optional graph artifact
                    ↓
comparison/search + gold evaluation
```

`Provenance` records publication, source document, section, page, exact passage, exact character offsets, extraction method/version, and optional model identity. `MeasurementResult` keeps the quantity attached to technology, evidence type, result nature, configuration, scale, calculation boundary, quantitative conditions, and assumptions.

The generic statement contract covers research questions, claims, limitations, assumptions, knowledge gaps, and implications. The first extractor deliberately handles only one result type. Adding a concept to the schema does not imply it is already extracted reliably.

## Literature-informed energy profile

The initial comparison dimensions are not taken only from the prompt. Iron-air publications span materially different architectures, including alkaline aqueous electrodes and high-temperature solid-oxide systems, so `technology` is not a sufficiently precise comparison key. A solid-oxide iron-air study reports that current density, cycle duration, and iron utilization affect storage capacity and round-trip efficiency ([DOI 10.1039/C2RA21992A](https://doi.org/10.1039/C2RA21992A)). Experimental work on alkaline iron electrodes connects physical/textural properties to capacity loss and electrochemical stability ([DOI 10.1016/j.electacta.2023.142964](https://doi.org/10.1016/j.electacta.2023.142964)). A system-level techno-economic study identifies power density, lifetime, and discharge duration as major economic sensitivities ([University of South Carolina thesis](https://scholarcommons.sc.edu/etd/3613/)).

That evidence motivates configuration, temperature, current density, duration, scale, evidence type, result nature, and calculation boundary as first comparison dimensions. Chemistry, materials, electrodes, electrolyte, degradation, lifetime, CAPEX/OPEX/LCOS, TRL, and uncertainty remain candidate extensions. They should become enforced fields only for a question and annotated corpus that need them. LCOS in particular must never be compared without its cost basis and model assumptions.

## First pilot

The smoke corpus has three synthetic full-text papers: two comparable laboratory measurements and one deliberately non-comparable modeled system assumption. It demonstrates percent/fraction normalization, page/section/passage traceability, condition association, evidence-type separation, graph projection, and pairwise comparison.

The scientifically meaningful output shape answers:

> Which round-trip-efficiency values were reported, and which share enough evidence context to compare?

It must show that the two laboratory values share the defined context, while the assumed AC-to-AC grid-system value differs in evidence type, result nature, configuration, scale, and calculation boundary.

## Real-corpus refinement

The real pilot now contains ten locally inspectable open-access PDF/JATS full texts. PDF ingestion inserts page markers; JATS ingestion retains section structure. Four RTE records were manually reviewed against exact passages and conditions. The visible result spans 40%–82.9%, but the comparison layer identifies all six pairs as different-context comparisons: the 61.9% and 82.9% results are measured solid-oxide laboratory-cell results at different temperatures, while 40% and 40%–45% are aqueous/grid system assumptions with different scale, duration, provenance, and energy boundaries.

The other six documents remain part of corpus coverage but contribute no direct RTE record because review did not establish a sufficiently attributable value for this question. This prevents values cited in reviews or broad slide decks from being reassigned to the document's headline technology.

The inspectable gold set checks missing results, hallucinated results, value/unit accuracy, page/section/passage offsets, and association with temperature, current density, and storage duration. Result ranges are stored as ranges rather than converted into two false point estimates.

## Model-assisted extraction boundary

The implemented Mistral adapter submits the retrieved evidence set through an API-enforced JSON schema for assertions, entities, and contextual measurements. It validates evidence IDs, exact source quotes, numerical text, entity labels, and stated conditions before promotion into cumulative scientific memory. Invalid records are rejected independently and counted; if no grounded answer or claim survives, the complete model response is discarded and the deterministic extractive answer remains. Provider responses are not database records.

## Evaluation gate

The smoke gold fixture detects missing and hallucinated results, incorrect values/units, incorrect source passage/page/section/offsets, and incorrect association with conditions. Before any scientific claim is presented, replace or extend it with 10–20 rights-cleared iron-air papers annotated by a domain reviewer. Evaluate measured, modeled, and assumed values separately.

## Next smallest changes

1. Expand the primary-study subset so independent studies exist within each chemistry/configuration, not only across incompatible systems.
2. Expand the model evaluation set beyond unit fixtures and score its candidates against reviewed records before relying on it for a new metric.
3. Add an explicit review queue with accept/reject/correct actions and persisted reviewer identity/version.
4. Add one additional high-value metric; LCOS is a strong candidate but needs currency year, system boundary, discount rate, lifetime, cycling, charging cost, and cost basis.
5. Add semantic/hybrid retrieval over the cumulative passages and structured records; follow-ups already execute against the frozen run corpus.

Neo4j, semantic retrieval, broad ontology work, and a Scientist Agent are explicitly outside this first gate.

## Question-first report

The first product-facing boundary is now `ResearchInvestigation`. A natural-language round-trip-efficiency question produces structured JSON plus Markdown or HTML reports. Reports lead with the answer and corpus/full-text coverage, then progressively disclose findings, contextual values, comparability decisions, exact evidence, full-text access, limitations, and suggested follow-up questions. The specialist result remains deterministic; generic investigations can add validated Mistral synthesis and execute conversational follow-ups over the frozen evidence corpus.

The dependency-free researcher UI serves that investigation through a narrow API. It accepts a question, renders progressive evidence layers, filters measured versus assumed results, navigates comparison explanations, opens assumption evidence, and displays complete known corpus documents. Operational controls and diagnostics sit in one collapsed Research details panel. Full-text access resolves publication IDs through the evidence store and rejects arbitrary paths. The UI remains a consumer of validated investigation records and does not perform extraction or modify the graph.
