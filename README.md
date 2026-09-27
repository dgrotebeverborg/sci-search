# Sci-Search

Sci-Search is a provenance-aware scientific evidence-search prototype. A researcher asks a question, receives a concise source-cited answer, and can drill down through findings, exact passages, and complete local full texts. It has a specialist contextual comparison for iron-air battery efficiency and a conservative generic evidence workflow demonstrated on goat foraging behaviour.

Sci-Search is released under the [MIT License](LICENSE). Development and architectural guidance is
available in [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

The project includes a three-document synthetic smoke fixture, a ten-document real open-access iron-air pilot, and a second ten-document open-access behavioural-ecology corpus. The iron-air specialist exposes only manually reviewed result records. Generic mode always builds an extractive evidence baseline. When Mistral is configured, it adds structured cross-paper synthesis only after every assertion, entity, and numerical result has passed local citation and exact-quote validation; otherwise the baseline remains the visible answer.

## Choose a runtime

- **Local research:** use `research-online` for synchronous discovery and analysis, or `investigate` to create a cited report from an existing corpus. Examples below produce durable files without a web deployment.
- **Local workspace preview:** use `serve --unsafe-development` on loopback to sign in with a temporary development account and create or switch projects. State is lost when the server stops; research execution is disabled.
- **Production web research:** deploy the FastAPI service with PostgreSQL, Redis, S3-compatible storage, Dramatiq workers, and OIDC authentication. The project interface supports live reviews, source-linked evidence, validation, and downloads through project-scoped APIs. Follow the [deployment runbook](docs/runbooks/DEPLOYMENT.md) and [production Compose configuration](compose.yml).

Install the locked development environment before running the local examples:

```bash
uv sync --frozen --extra dev --python 3.11
source .venv/bin/activate
```

## Online scientific search

Create a local configuration from `.env.example` and set `OPENALEX_API_KEY`. To enable model-assisted analysis, also set `MISTRAL_API_KEY`; `MISTRAL_MODEL` defaults to `mistral-small-latest`. Real values belong only in `.env.local`, which is ignored by version control and should have restrictive file permissions.

During migration from sci-graph, if Sci-Search has no Mistral key of its own, it reads only `MISTRAL_API_KEY` from the sibling `sci-graph/.env.local`. It deliberately ignores all other variables in that file. A Sci-Search-local key or process environment value takes precedence.

Mistral output is requested through schema-enforced JSON. Valid structure alone is not accepted: all assertions must cite known evidence IDs and exact source quotes, while numerical and condition text must occur in those quotes. Invalid individual records are rejected; if no grounded answer or claim survives, the complete model result is discarded in favor of the deterministic extractive answer. API keys are not persisted in runs or scientific memory.

Every acquired full text also receives a question-specific study card before synthesis. The card records its inclusion decision, required-dimension coverage, inferred evidence nature, and selected methods/results/limitations passages with exact source offsets. Only uncertain studies may be sent for optional quote-validated Mistral adjudication; deterministic exclusions are not automatically promoted. The matrix is included in the cited review and complete research package.

The [researcher validation protocol](docs/RESEARCHER_VALIDATION_GUIDE.md) describes the cross-domain benchmark and source-grounding checks. Silver seed labels remain distinct from researcher-confirmed annotations. Export its machine-readable scorecard with `python3 scripts/validation_scorecard.py --output /tmp/validation-scorecard.json`.

The synchronous local research pipeline submits query variants to OpenAlex, Europe PMC and Crossref, deduplicates records, screens candidates, and acquires available open full texts. Its review modes record coverage checks and stopping reasons, and persist the resulting corpus and candidate ledger under `data/research_runs/<run-id>/`. These local files and the SQLite scientific memory belong to the CLI workflow; the production web service uses PostgreSQL and object storage.

Run local online research with a small explicit budget:

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

Completed local CLI runs are accumulated in `data/scientific_memory/`: a SQLite provenance graph plus a content-addressed document cache. Later searches consult this memory before external acquisition, deduplicate publications, reuse available full text, and cache only successfully validated model analysis. Asking more questions therefore grows reusable coverage, but does not automatically make conclusions true or complete; new answers still depend on retrieval coverage and validation.

Generic extractive records pass deterministic source-grounding checks before they receive `silver_source_verified` status: their offsets must reproduce the stored passage, the selected statement and numerical mentions must occur verbatim, and publication, source-document, extraction-method, document-hash, schema, and validator provenance must be present. This status verifies the extraction's connection to its source; it is explicitly not expert confirmation of the scientific interpretation. Researcher decisions are stored separately as revisions and survive later questions. A changed content/schema fingerprint returns a previously reviewed record to `needs_review` rather than silently carrying approval across versions.

Online research does not bypass paywalls. It analyzes available open full text and records unavailable candidates. Use `investigate` against a completed run’s corpus for further local questions without starting another online search.

Unavailable and paywalled candidates remain in the discovery ledger. The production project interface supports authorized PDF uploads through its evidence controls. Sci-Search validates and hashes the file, records its origin as `researcher_supplied_authorized`, and never treats metadata or an abstract as a substitute for full-text evidence.

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

## Saved scientific dashboards

Every submitted question appears in the left sidebar of its project. Select a question to reopen its
complete dashboard: answer and adequacy, cited literature review, findings, comparisons, research
landscape, studies, limitations, methods, evidence passages, validation, references, and downloads.
Fresh and reopened results use the same renderer. A saved dashboard opens without another provider
search or model call. Stable links preserve project, question, and optional revision selection.

Article **Include**, **Background**, **Exclude**, and **Reset** controls save a contextual decision and
schedule a rebuild from retained sources. Background papers provide context rather than direct
support for conclusions. The previous complete dashboard remains visible while updating; a failed
rebuild can be retried. Older revisions and their downloads remain available. Finding-level
**Accept evidence / Reject evidence** is a separate review of an extracted claim, not article relevance.
The landscape distinguishes all discovered publications from the included evidence population.

The web runner now uses project-scoped scientific memory to reuse acquired full texts and validated
analysis. Feedback is retained with its question and actor. Optional feedback-aware acquisition ranking
is disabled by default until researcher-confirmed evaluation passes; storing more votes alone is not
proof of better scientific answers. See [memory rollout and evaluation](docs/operations/research-memory-rollout.md).

To recover an older local run into an explicitly selected project, first inspect a dry run (stop the
local server during import so there is one catalog writer):

```bash
python scripts/import_saved_dashboards.py --source /path/to/old/run \
  --local-root data/local_research_runs --project-id PROJECT_ID --dry-run
```

Remove `--dry-run` to import. Original files are preserved and repeat imports are idempotent. A missing
result becomes an incomplete history entry. Production can reopen retained legacy result artifacts;
article rebuilding is unavailable when the original source ledger was not retained.

Back up the complete local research root, including `workspace.sqlite3`, objects, source run folders,
and project memory. Production requires migrations through `0009_memory` plus a coordinated database
and object-store backup. The plain `--unsafe-development` preview remains intentionally temporary;
use `--local-research` for persistence.

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

Start an explicit, temporary workspace preview:

```bash
python3 -m sci_search.cli \
  --corpus corpora/iron_air_real \
  serve --unsafe-development \
  --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` and choose **Continue with development account**. You can create and switch projects. The corpus argument supplies the initial project name; the preview does not load the corpus into a research service. A banner explains that changes are temporary, and **Start review** is disabled. Authenticated attempts to start a run through the preview API receive HTTP 503. Use the CLI examples for actual local research and report exports.

For a persistent laptop research workspace with real online research and a development login:

```bash
python3 -m sci_search.cli --corpus demo/my_research serve \
  --unsafe-development --local-research --host 127.0.0.1 --port 8010
```

Open `http://127.0.0.1:8010` (set `SCI_SEARCH_ALLOWED_ORIGINS` to that URL when using a non-default port).
Questions run through the real literature pipeline, one at a time. Keep the tab open to follow progress;
evidence and downloads appear when research finishes. Questions, projects, dashboard revisions, reports, acquired sources, and article feedback are retained under
`data/local_research_runs`. Login sessions are renewed when you return; the workspace survives server restarts. Cancellation suppresses
publication after the current research step finishes. This mode is loopback-only and cannot run in production.

Without production configuration, `serve` requires `--unsafe-development`. That flag is restricted to loopback addresses and rejected in production. Production startup uses `SCI_SEARCH_ENVIRONMENT=production` and requires database, queue, object-storage, session, and institutional OIDC settings; provider credentials are also required for live discovery. Configure the settings and secret files in [compose.yml](compose.yml), then follow the [deployment runbook](docs/runbooks/DEPLOYMENT.md), including migrations, readiness checks, and worker startup. See the [API cutover guide](docs/operations/api-cutover.md) for current routes and the [retirement notice](docs/migration/LEGACY_RUNTIME_DEPRECATION.md) for retained CLI compatibility.

The old local server and its unversioned endpoints have been removed. Production research uses the project’s **Research**, **Evidence**, **Validation**, and **Downloads** sections. Retained research packages contain full-text artifacts, cited reviews, discovery and screening ledgers, and provenance. The grounding checks described above apply to the scientific outputs; the preview cannot generate them.

Try these questions with the local `investigate` command against `corpora/goat_foraging`:

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

Run the full test suite with its browser and isolated service prerequisites:

```bash
python3 -m playwright install --with-deps chromium
docker compose --project-name sci-search-tests -f compose.integration.yml up --detach --wait
python3 -m pytest -q
docker compose --project-name sci-search-tests -f compose.integration.yml down --volumes --remove-orphans
```

The integration stack uses dedicated test databases and loopback ports. Stop it after testing, including when a test fails.

The default suite skips only tests explicitly marked `retained_corpus`. These scientific checks need locally retained full texts under `corpora/*/papers` or historical runs under `data/research_runs`, which are intentionally excluded from Git. They cover the iron-air and goat gold evaluations, real-corpus literature reviews, diverse and metamorphic benchmarks, and historical reliability audits. Benchmark manifests alone do not supply the source documents.

After restoring the authorized local assets, run these checks explicitly:

```bash
python3 -m pytest -q --run-retained-corpus -m retained_corpus
```

Missing required manifests, papers, or historical run artifacts fail this command; opting in never silently skips unavailable data. Use `--run-retained-corpus` without the marker filter to include these checks in the full suite. Deterministic fixture-based scientific, benchmark-schema, and replay tests continue to run by default. Do not upload retained corpora or private research data to make CI pass.

See [the first vertical-slice design](docs/design/first-vertical-slice.md) for the `sci-graph` audit, [the generic research workflow](docs/design/generic-research-workflow.md), and [online discovery architecture](docs/design/online-discovery.md) for current capabilities and boundaries.
