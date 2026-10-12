# Question-driven data research
The interpreted question includes a proposed research approach: datasets, literature, or both.
The user approves that scope using the existing confirmation screen. The app then executes the
plan; users do not have to supply a dataset URL or prepare expected answers.

With a configured OpenAI model, dataset discovery uses that selected model and Responses web
search. It retains the search actions, consulted URLs, model/usage metadata and source decisions.
The local Codex provider can perform the same discovery using the owner's ChatGPT login and
Codex web search. It retains URLs from CLI web-tool results; URLs merely written in the model's
answer are not accepted as observed sources. Enable it as described in the README.
It inspects source pages and observed links before downloading files. A model assesses semantic
fit, definitions and column mappings; it does not supply the numerical observations.

The numerical output contract remains annual descriptive series. Supported calculations:
- EFFIS country-reported annual forest-fire counts and burned area, from independently discovered
  official workbook downloads. Broader Europe requests 46 named countries; EU-27 is a separate,
  explicit scope. A fixed reporting panel and missing years remain visible.
- Public UTF-8 CSV annual series with a header row (including leading comment metadata), explicit
  entity/dimension filters and documented units. Multiple requested measurements may use the same
  file. Duplicates, unknown conversions and all-missing selections are rejected. Missing years are
  not interpolated. Stacked tables can select a bounded section ending before a different header,
  retaining the full source and original line references. Documented daily means can be averaged
  into annual means only with every calendar day present; incomplete years remain missing and
  retain day counts. Once-daily snapshots are not interchangeable with daily means. Endpoint differences and percentage changes are descriptive calculations.

The initial discovery pass assesses at most four candidate sources and five requested measurements;
bounded follow-up can inspect up to ten sources.
For CSV downloads, up to three further HTML pages can be followed using observed links only;
loops and unresolved viewers remain explicit source gaps. Downloads are limited to 50 MB and public HTTP(S) addresses. DNS is validated and pinned for each
redirect; credentials are not sent to dataset hosts.

## Executed Python extraction and calculation

Every new successful data analysis executes a retained Python calculation before publication,
including the curated wildfire adapter. The published numerical result must equal that execution.
The selected model can choose Python directly for unfamiliar JSON, XML, PDF, HTML tables, workbooks
and archives, or recover a source when the standard parser or mapping fails. It sees a source
inspection and writes code that reads the original bytes; it receives real execution/validation
errors for up to three attempts. The data extra supplies pandas and openpyxl; pypdf is also available.
An installed library does not guarantee every document or source can be interpreted correctly.

Execution uses Linux bubblewrap with separate process, user, mount and network namespaces,
read-only source/dependency mounts, no inherited credentials, no child processes, 64 MiB temporary
storage, monitored output limits, CPU/memory limits and a 45-second wall-clock limit per execution.
The root and device filesystems are read-only. Cancellation kills the active Python execution;
an active model call retains the provider's existing timeout behavior. A non-root runtime and
unprivileged namespaces are required. Missing isolation is a visible failure, never a host fallback.
Generated code cannot download files or install packages.

Extracted records must have a requested measurement, entity, annual year, finite numeric value or
null, unit and original source reference. Duplicate measurement/entity/year rows are rejected.
The existing calculation engine computes annual series and descriptive changes. A separate model
review assesses extraction code, source definitions, units, scope and assumptions before accepting
generated extraction. This review is not independent expert validation, and source references from
custom code are inspectable rather than universally machine-proven.

Each source package also includes `download_source.py --output NEW_FILE`, a separate optional
network step using the retained public downloader. It reports whether the source has changed and
never overwrites retained data. Offline replay never invokes this download step.

Each source package contains original data, all attempted scripts/errors, accepted observations,
the executed calculation, its input snapshots, hashes and runtime versions. `reproduce.py` executes
the retained extraction and calculation again in isolation, checks artifact hashes, and compares
both source-level and aggregate published results. `environment.json` and `requirements.txt` record
the environment; install it before replay. Replay itself does not use the network or a model.

Browser-only portals, authentication, API pagination requiring additional acquisition, scanned
PDFs requiring OCR, geospatial processing and non-annual output remain access/analysis gaps.
The app can use already downloaded JSON or text PDF contents; it does not promise arbitrary web
automation or turn an unavailable observation into a generated number.

For combined runs, literature executes through the existing evidence workflow. Its synthesis and
data-derived observations remain separately attributed. The report includes a dataset appendix,
and the ZIP includes both literature and data artifacts. Data-only runs use their own report and ZIP.
The data package retains source bytes, metadata, assessments, mappings and calculation code.
Run python reproduce.py after extracting it to check source hashes and reproduce the retained values
without network access (matching Python environment, Linux and bubblewrap). Model assessments are not independent expert validation.

The OpenAI API provider requires OPENAI_API_KEY (or its existing file setting), and discovery
uses billable model and web-search calls. Local Codex instead uses its authenticated account and limits. If selected-provider web search is unavailable, the result
says so. The earlier curated EFFIS pilot remains available without a model.

### In-job investigation review

The data investigator can now reconsider a downloaded source, rather than only search for another
URL. Its decision context includes extraction errors, the last attempted script, archive inspection,
mapping gaps, retained measurements and earlier action outcomes. A `reassess` action selects a subset
of the original requested measurements and optionally an observed documentation link. It reuses the
original bytes, executes and validates extraction again, and retains the new artifacts separately.
Already retained measurements are excluded from that new extraction; previous results are preserved.
ZIP text documentation is available to both standard mapping and generated Python inspection.

After a failed Python attempt, a bounded model review chooses code repair, extraction of supported
requested measurements, or stopping that source. Partial years and measurements are allowed; missing
units, invented observations and unjustified aggregation are still rejected. Scripts, review decisions,
validation outcomes and documentation bytes/hashes are retained. Source comments and text are treated
as untrusted evidence. There are at most three Python attempts per extraction, six data follow-up
actions, ten distinct source URLs and a ten-minute data-loop budget checked between operations.
A single in-flight download/model call may finish after that budget; its provider timeout still applies.

When a literature run cannot answer the overall question, an additional investigation review can
reassess acquired passages for individual original subjects. It sees selection reasons and the data
stream's outcomes, chooses up to eight existing publications per action, and must copy exact source
quotes for any retained partial evidence. The loop permits two actions and checks a two-minute budget
between them. Relevance remains a model assessment; verbatim quote validation is not expert review.
Partial findings are displayed separately and never promote the overall adequacy assessment or change
original screening decisions. The research package includes `data/investigation-review.json` and the
corresponding original analysis documents under `reviewed-sources/`.

These actions extend the existing supported readers. They do not add a general browser agent,
account access, unrestricted model-generated downloads, or support for every dataset format.

### Measurement meaning before publication

New research jobs require a source-grounded meaning review in addition to executable calculations.
This applies to standard CSV/Excel/statistical-table mappings, generated Python extraction and
EFFIS results. Older saved EFFIS plans now enter the same general investigation workflow; previously
saved results are not retroactively certified. The standalone curated EFFIS CLI remains a deterministic
calculation tool, outside this job review workflow.

For each published measurement, the reviewer must assess its definition, unit, geographical level,
time basis and calculation. Each aspect needs exact quotations from retained source documents.
Missing, conflicting, malformed or fabricated evidence blocks publication even when the script runs
and a model gives an overall positive verdict. Derived measures need documented compatible inputs,
justified aggregation and protection against double counting. Suspected documentation typos cannot
be silently corrected; reporting years cannot silently become measurement years.

Unresolved checks and targeted documentation questions enter the existing bounded follow-up planner.
It can consult an observed methods link and reassess the original bytes. Semantic uncertainty cannot
trigger an unchanged code-repair retry, including when reflection fails. Independently supported
measurements can still be retained through per-measurement mapping or a narrower Python extraction.
Rejected attempts, their original observations and source files remain in the downloadable package,
separate from published results. The dashboard shows unresolved questions and the passages behind
accepted or rejected interpretations. Python evidence documents and standard review files are sealed
with the calculation artifacts for offline replay.

These checks verify the presence of citations deterministically. Whether those passages actually
justify the interpretation remains a model judgment, not independent scientific expert validation.
The additional standard-table review costs one model call per candidate measurement; existing
Python semantic review now uses the same structured evidence contract.

## Statistical API connectors

Before web search, `workflow.execute` runs a connector stage that queries four statistical APIs
directly. Each connector has a fixed host set and never requests a URL supplied by the model;
dataset IDs must match a per-connector pattern. All traffic goes through the same public-address,
DNS-pinning and redirect checks as web downloads, and no credentials are sent.

| Connector | Hosts | Data request |
|---|---|---|
| Eurostat | `ec.europa.eu` | SDMX 2.1 dataflow list, structure and a TSV slice for the selected codes |
| CBS (Statistics Netherlands) | `opendata.cbs.nl`, `datasets.cbs.nl`, `www.cbs.nl` | OData catalogue; the CSV package with every code table |
| PxWeb | `statistikdatabasen.scb.se` (Statistics Sweden, API v2), `data.ssb.no` (Statistics Norway, API v1, POST) | JSON-stat 2 for the selected table cells |
| Our World in Data | `ourworldindata.org` | Grapher CSV and its metadata for one indicator |

For each requested measurement, the model proposes 1 to 4 English and, separately, 1 to 4 Dutch
search terms. The measurement text itself is always one of the English terms. Each connector
searches only in its declared languages: English for Eurostat, PxWeb and Our World in Data, and
Dutch and English for CBS. The model then chooses at most four candidate datasets, and selects codes from a strict schema whose values are
the codes observed in the dataset. The selection is validated before fetching: at most 60 entities,
years within the dataset's coverage, annual data only. Other frequencies are rejected with
"dataset is <frequency>; no aggregation was performed". Missing values stay missing, and source
status flags (Eurostat `p` and `e`, CBS provisional) are kept in the Status column. The fetched
slice is stored with its SHA-256 and passes through the same table mapping, meaning review, executed
Python calculation and offline replay as web-discovered files. Each connector analysis records the
connector, dataset ID, exact request (URL, and body for POST), the response SHA-256, the SHA-256 of
the catalogue snapshot it was found in, the licence from the metadata, and the model's choices with
their reasons.

Measurements no connector covered continue to the web-search workflow, restricted to those
measurements. A web candidate on a connector host whose URL names a dataset enters the connector
path instead of the scraper. Results that include connector analyses keep the existing status
`partial`, like every other discovered-data result. If the connector stage itself fails, the
failure is recorded as a `connector:stage` assessment and the run continues with web search.
`SCI_SEARCH_DATA_CONNECTORS=0` (or `false`, `no`) skips the stage and restores the previous path
exactly.

Limits: catalogue and search requests are bounded to 20 MB (the Eurostat dataflow list is about
7 MB); metadata and data responses to 5 MB. The existing 50,000-row limit applies. Catalogues are
cached per calendar day: under `data/connector-catalogues` for the CLI, `<root>/connector-catalogues`
for the local service, and in the container's temporary directory
(`sci-search-connector-catalogues`) for the production worker. Cache files are replaced atomically;
a damaged cache file is fetched again.

Known limitation: CBS delivers each table as one CSV package with every code table, and filtering
happens only after download. Large CBS tables therefore exceed the 5 MB response limit or the
package ZIP's file-count and expanded-size limits, and are rejected ("Dataset exceeds the 5 MB
acquisition limit", "Data ZIP exceeds its file-count or expanded-size limit"). The limits are not
relaxed for connectors; such a measurement continues with the next candidate or web search.

### Recovery

Every failure is classified, and each class has a fixed recovery. Recovery never relaxes a check:
a wrong unit, an unobserved code or a non-annual series is never accepted on a later attempt.

| Class | Example | Automatic recovery | Limit |
|---|---|---|---|
| Model selection error with an informative reason | unobserved code; too many entities; "no results for this key" | Return the error to the model with the facts it needs (valid codes, or combinations that contain data) for a new selection | 2 repairs per dataset |
| Wrong dataset | semantic review rejects the meaning; monthly-only; years not covered; a reader's content rejection (frequency, unit, status flag, size or entity limit, duplicate or unobserved code) | Next candidate. The rejection reason goes to the model, which reformulates search terms for one more search round | 1 extra search round per measurement |
| Transient | timeout; HTTP 5xx | Retry the request once | 1 retry |
| Connector cannot read the response | the reader meets bytes it cannot parse or an unexpected shape | No selection loop. The same raw bytes go to Python recovery for that one measurement only, with its own semantic review; the case is recorded as a connector defect | the existing 3 Python attempts |

Only parse and shape failures reach Python recovery; any other reader failure is a content
rejection and moves to the next candidate, so Python extraction cannot bypass the annual, unit or
limit checks. A Python recovery that leaves its measurement uncovered is rejected. Every failed step
is recorded as an assessment with `failure_stage` `connector:<step>` and a readable reason, and its
recovery steps appear on the dashboard. A connector failure never stops the run.

### Connector gaps

When a web candidate on a host without a connector is a JavaScript-only page, or a near-empty page
without static links, the run records it in `result["connector_gaps"]` as
`{host, measurement, evidence}`. The dashboard and Markdown report show it as "Needs an API connector for <host>".
Pages on connector hosts are never recorded as gaps. The gap list shows which connector to build
next (for example Rijkswaterstaat or AIMS).

### Live acceptance run

The standard suite is offline. An opt-in acceptance test queries the real APIs with the configured
model, loading `.env.local` as the CLI does:

```bash
SCI_SEARCH_ANALYSIS_PROVIDER=openai uv run python -m pytest tests/live -q --run-live-data
```

It runs seven reference questions and writes `docs/operations/data-connectors-acceptance.md`.
Questions answered only by sources without a connector (EFFIS, NOAA) need web search, so with
Mistral they are not required to succeed. The run makes paid model calls; results from earlier
runs are kept as `docs/operations/data-connectors-acceptance-<provider>.md`.
