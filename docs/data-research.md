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
