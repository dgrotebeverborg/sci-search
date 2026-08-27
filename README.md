# Sci-Search

Sci-Search is a provenance-aware scientific evidence-search prototype. A researcher asks a question, receives a concise source-cited answer, and can drill down through findings, exact passages, and complete local full texts. It has a specialist contextual comparison for iron-air battery efficiency and a conservative generic evidence workflow demonstrated on goat foraging behaviour.

Sci-Search is released under the [MIT License](LICENSE). Development and architectural guidance is
available in [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

The project includes a three-document synthetic smoke fixture, a ten-document real open-access iron-air pilot, and a second ten-document open-access behavioural-ecology corpus. The iron-air specialist exposes only manually reviewed result records. Generic mode always builds an extractive evidence baseline. When Mistral is configured, it adds structured cross-paper synthesis only after every assertion, entity, and numerical result has passed local citation and exact-quote validation; otherwise the baseline remains the visible answer.

## What you can test now

- Ask a new question in **Search scientific literature · live** mode and let Sci-Search build a fresh evidence corpus.
- Review an AI-generated **Check my understanding** brief before searching: interpreted question, objective, scope, comparison dimensions, assumptions, exclusions, and any material ambiguity remain attached to the run as provenance.
- Watch planning, discovery, screening, open-full-text acquisition and evidence analysis progress asynchronously.
- Inspect the exact search strategies and a candidate inclusion/exclusion ledger.
- Inspect bounded reference/cited-by expansion and the citation relation that introduced a candidate.
- Override candidate inclusion, exclude unsuitable studies, or add a locally authorized full text; the evidence report is rebuilt after every decision.
- Download one acquired publication, any checkbox selection, or the complete active evidence corpus as a ZIP with source/licence provenance.
- Choose **Quick scan** (up to 10), **Research review** (adaptive 25–50, the default), or **Deep review** (adaptive 25–100). Research and Deep modes reassess question coverage after each batch and stop on adequate coverage, evidence saturation, candidate exhaustion, or the recorded safety limit.
- Inspect a validated structured synthesis of evidence types, convergence, quality flags, and numerical-comparability warnings.
- Reuse publications and cached full texts from cumulative scientific memory on later questions.
- Persist automatically checked silver evidence with document fingerprints, extraction/schema/validator versions, individual validation checks, and an append-only review history.
- Treat acquisition and scientific inclusion as separate stages: parsed full texts receive an auditable question-specific decision (`included`, `background`, `uncertain`, or `excluded`) before analysis or packaging, while researcher overrides are retained explicitly.
- Validate that every downloaded artifact can actually be parsed before it consumes the full-text target. Scanned, malformed, or otherwise unreadable files are retained as auditable `unreadable` outcomes, reported as possible OCR/replacement needs, and skipped while acquisition continues to seek a usable replacement.
- Mark an expanded evidence record as researcher-verified, uncertain, or rejected; rejected extractions are excluded from later answers while the original extraction and decision remain auditable.
- Use optional Mistral structured analysis for claims, agreements, contradictions, methods, assumptions, limitations, gaps, entities, and contextual measurements.
- Switch between the iron-air and goat-foraging evidence corpora.
- Ask arbitrary questions about the selected local corpus.
- Start with a cited summary and progressively inspect findings, provenance, and full text.
- Continue with suggested follow-up questions in the same research session.
- Get an explicit insufficient-evidence answer for unsupported questions instead of a plausible invention.
- Export the same investigation as JSON, Markdown, or a self-contained HTML report.
- Download a prominent complete research package: every acquired full text in its retained original format, a cited PDF/HTML/Markdown literature review, the research landscape, references, exact evidence passages, and machine-readable provenance.
- Read that literature review directly as the primary answer, organized into scope and approach, synthesis, contradictions and method differences, limitations and uncertainty, knowledge gaps, and references; evidence records and full texts remain available underneath for verification.

## Online scientific search

Create a local configuration from `.env.example` and set `OPENALEX_API_KEY`. To enable model-assisted analysis, also set `MISTRAL_API_KEY`; `MISTRAL_MODEL` defaults to `mistral-small-latest`. Real values belong only in `.env.local`, which is ignored by version control and should have restrictive file permissions.

During migration from sci-graph, if Sci-Search has no Mistral key of its own, it reads only `MISTRAL_API_KEY` from the sibling `sci-graph/.env.local`. It deliberately ignores all other variables in that file. A Sci-Search-local key or process environment value takes precedence.

Mistral output is requested through schema-enforced JSON. Valid structure alone is not accepted: all assertions must cite known evidence IDs and exact source quotes, while numerical and condition text must occur in those quotes. Invalid individual records are rejected; if no grounded answer or claim survives, the complete model result is discarded in favor of the deterministic extractive answer. API keys are not persisted in runs or scientific memory.

Every acquired full text also receives a question-specific study card before synthesis. The card records its inclusion decision, required-dimension coverage, inferred evidence nature, and selected methods/results/limitations passages with exact source offsets. Only uncertain studies may be sent for optional quote-validated Mistral adjudication; deterministic exclusions are not automatically promoted. The matrix is visible as a collapsed researcher review queue and is included in the cited review and complete research package.

The header’s **Validate quality** workspace opens a blind-by-default ten-question cross-domain benchmark tied to immutable current-code replays. Researchers can inspect acquired full texts, confirm publication relevance, assertion support, extraction accuracy, units, provenance, context, and conclusion coverage, and record missed publications. Silver seed labels remain distinct from researcher-confirmed annotations. The live scorecard enforces minimum sample sizes, 100% provenance, and zero unsupported assertions as release gates. **Export audit** produces a complete review ZIP; the machine-readable scorecard can also be exported with `python3 scripts/validation_scorecard.py`. The protocol is documented in `docs/RESEARCHER_VALIDATION_GUIDE.md`.

Run the interface:

```bash
python3 -m sci_search.cli \
  --corpus corpora/iron_air_real \
  serve \
  --additional-corpus corpora/goat_foraging \
  --host 127.0.0.1 --port 8000
```

Select **Search scientific literature · live**. A default Research review submits transparent query variants to OpenAlex, Europe PMC and Crossref, deduplicates the records, screens them against the question concepts, and acquires an initial set of up to 25 open full texts. If important coverage is still missing, Sci-Search performs targeted gap searches and continues in ten-paper batches up to a 50-paper safety limit. It stops earlier when coverage is adequate or consecutive batches add no new evidence-contributing publications. Quick scan is capped at 10; Deep review can continue to 100. The selected mode, every coverage check, and the exact stopping reason are retained in the run and cited review. Full-text acquisition is restricted to trusted Europe PMC and OpenAlex content endpoints. The resulting corpus and complete candidate ledger are persisted under `data/research_runs/<run-id>/`.

Run the same pipeline from the command line with a smaller explicit budget:

```bash
python3 -m sci_search.cli \
  --corpus corpora/goat_foraging \
  research-online \
  --question "How does salinity affect tomato seed germination?" \
  --per-query 10 \
  --max-full-texts 3 \
  --output /tmp/research-run.json
```

The durable run records provider, query, timestamp, raw/unique/selected counts, relevance and concept-coverage scores, inclusion/exclusion reasons, acquisition source/errors, generated corpus manifest and final passage-grounded investigation. API keys are never written into these artifacts.

Completed runs are accumulated in `data/scientific_memory/`: a SQLite provenance graph plus a content-addressed document cache. Later searches consult this memory before external acquisition, deduplicate publications, reuse available full text, and cache only successfully validated model analysis. Asking more questions therefore grows reusable coverage, but does not automatically make conclusions true or complete; new answers still depend on retrieval coverage and validation.

Generic extractive records pass deterministic source-grounding checks before they receive `silver_source_verified` status: their offsets must reproduce the stored passage, the selected statement and numerical mentions must occur verbatim, and publication, source-document, extraction-method, document-hash, schema, and validator provenance must be present. This status verifies the extraction's connection to its source; it is explicitly not expert confirmation of the scientific interpretation. Researcher decisions are stored separately as revisions and survive later questions. A changed content/schema fingerprint returns a previously reviewed record to `needs_review` rather than silently carrying approval across versions.

Online mode does not bypass paywalls. It currently analyzes available open full text and records unavailable candidates. Suggested follow-ups query the frozen run corpus without spending credits or silently changing the evidence base; starting a new question in live mode creates a new run.

Unavailable and paywalled candidates remain visible. A researcher who lawfully has a copy may attach a local TXT, Markdown, JATS/XML, or PDF document from the screening ledger after explicitly confirming authorization. Sci-Search validates and hashes the file, records its origin as `researcher_supplied_authorized`, and never treats metadata or an abstract as a substitute for full-text evidence.

Downloads preserve the best acquired publication artifact rather than regenerating a report as a fake paper. Researcher-supplied files retain their original format; Europe PMC full texts remain JATS XML; PDF-only OpenAlex records remain PDF. When OpenAlex offers both structured GROBID XML and an open-access PDF, Sci-Search retains XML for section-aware analysis and the PDF as the researcher download. Both are cached across later runs. ZIP manifests distinguish the analysis document from the downloaded artifact and record its source.

Measure discovery coverage against a researcher-curated DOI bibliography:

```bash
python3 -m sci_search.cli \
  --corpus corpora/goat_foraging \
  evaluate-discovery \
  --discovery data/research_runs/<run-id>/discovery.json \
  --gold corpora/goat_foraging/gold/discovery_bibliography.json
```

The current eight-paper goat-foraging pilot bibliography is retained as a quality gate. In explicit **high-recall** mode, the frozen broad-question benchmark improved from 12.5% to 87.5% discovery recall and selected 75% of the bibliography, meeting its predefined 75% discovery target. The quick-pilot mode is faster but is not suitable when coverage matters. This small benchmark is not proof of systematic-review completeness in other domains.

## Current real-corpus result

For the guiding RTE question, the pilot finds four reviewed contextual records spanning 40% to 82.9%:

- measured solid-oxide laboratory-cell results of 61.9% at 500 °C and 82.9% at 550 °C;
- a 40–45% manufacturer specification for a 100-hour aqueous grid system, with an AC-to-AC boundary including conversion and auxiliary losses;
- a 40% input assumption for a 72-hour, 25 MW energy-system model.

These are not direct estimates of one common quantity. Their chemistry, scale, evidence type, operating conditions, and calculation boundaries differ. This qualified non-comparability—not the numerical range alone—is the vertical slice's principal finding.

## Ask a research question

Generate a readable HTML investigation report:

```bash
python3 -m sci_search.cli \
  --corpus corpora/iron_air_real \
  investigate \
  --question "What round-trip efficiencies are reported for iron-air batteries, and are they comparable?" \
  --format html \
  --output /tmp/sci-search-investigation.html
```

Use `--format markdown` for a text report or `--format json` for the durable structured investigation artifact.

## Researcher web interface

Run the local question-first interface:

```bash
python3 -m sci_search.cli \
  --corpus corpora/iron_air_real \
  serve \
  --additional-corpus corpora/goat_foraging \
  --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. Select a corpus, ask a question, then inspect the cited evidence and full texts. Iron-air round-trip-efficiency questions use the validated specialist comparison; other questions use the domain-profiled generic workflow.

The main view intentionally shows only the answer, findings, evidence, limitations, and follow-ups. Search strategy, screening controls, downloads, memory statistics, model provenance, and diagnostics are grouped under the collapsed **Research details** panel. Search-depth controls appear only in live-search mode.

Completed live runs prominently expose **Download research package** directly below the answer summary. The ZIP contains every included or relevant-background publication artifact, `literature-review.pdf` as its human-readable starting point, HTML and Markdown alternatives, a research-landscape export, the candidate/run ledger, the complete post-acquisition full-text screening ledger, and provenance manifests. Acquired documents classified as excluded or uncertain remain auditable but are not silently analyzed or placed in the default paper bundle. The report clearly distinguishes discovered metadata records, acquired full texts, included full texts, and publications actually cited in its conclusions. It includes an executive summary, scope, reproducible search strategies, selection counts, corpus overview, landscape, thematic findings, contextual measurements, contradictions and limitations, knowledge gaps, bibliography, excluded-record ledger, and an exact-passage appendix. It is explicitly labelled an AI-assisted evidence review rather than a systematic review until protocol, dual screening, and formal risk-of-bias requirements are completed.

For machine inspection, `GET /api/scientific-memory?limit=500` returns a bounded node/edge projection and total counts. The limit is clamped to 5,000; the SQLite database remains the complete durable memory.

Try:

```text
How does vegetation structure affect goat foraging behaviour?
Does season change goat foraging behaviour?
Do goats prefer leaves or grass?
How does lunar geology affect goat foraging?
```

The last question is an intentional negative test and should return no evidence.

Generate a portable generic report:

```bash
python3 -m sci_search.cli \
  --corpus corpora/goat_foraging \
  investigate \
  --question "How does vegetation structure affect goat foraging behaviour?" \
  --format html \
  --output /tmp/goat-foraging-report.html
```

Evaluate cross-domain retrieval and grounding:

```bash
python3 -m sci_search.cli \
  --corpus corpora/goat_foraging \
  evaluate-generic \
  --gold corpora/goat_foraging/gold/generic_questions.json
```

Acquire or refresh the curated public full texts with:

```bash
python3 scripts/acquire_iron_air_corpus.py
```

Repository access can change; unavailable sources are reported and skipped rather than replaced with unverified copies.

## Run the vertical slice

```bash
python3 -m sci_search.cli \
  --corpus corpora/iron_air_real \
  compare --metric round_trip_efficiency
```

The JSON response contains every value, its conditions and evidence type, the exact source passage with page/section/character offsets, and pairwise comparability judgments.

Evaluate extraction against the inspectable gold fixture:

```bash
python3 -m sci_search.cli \
  --corpus corpora/iron_air_real \
  evaluate --gold corpora/iron_air_real/gold/round_trip_efficiency.json
```

Export the derived graph artifact:

```bash
python3 -m sci_search.cli \
  --corpus corpora/iron_air_real \
  export --format graph --output /tmp/sci-search-graph.json
```

Run tests:

```bash
python3 -m pytest -q
```

See [the first vertical-slice design](docs/design/first-vertical-slice.md) for the `sci-graph` audit, [the generic research workflow](docs/design/generic-research-workflow.md), and [online discovery architecture](docs/design/online-discovery.md) for current capabilities and boundaries.
