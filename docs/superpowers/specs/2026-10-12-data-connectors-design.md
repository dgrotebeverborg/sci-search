# Statistical data connectors for data research

Date: 2026-10-12. Status: design approved in chat; awaiting written-spec review.

## Product outcome

Data research succeeds on questions answerable from published official statistics, instead of
only when web search happens to land on a file the scraper can read. The app queries the
statistical APIs that publish the data, lets the model choose a dataset and dimension codes from
labelled metadata, and recovers automatically from errors. Questions that still cannot be answered
name the missing connector instead of failing vaguely.

Data research no longer depends on a web-search-capable provider: catalogue search works with any
configured model, including Mistral.

## Decisions

- Connector catalogue search always runs. Web search is added when the provider supports it
  (OpenAI, Codex), and handles only measurements the connectors did not cover.
- First connectors: Eurostat (SDMX), CBS (OData and CSV packages), PxWeb (a fixed list of
  installations) and Our World in Data.
- Connectors feed the existing pipeline at `prepare_table`. They are not a separate pipeline, and
  the model does not construct API URLs.
- The existing CBS package reader and Eurostat special cases move into the connectors; no third
  parallel route is added.
- Recovery never relaxes a check. A wrong unit, an unobserved code or a non-annual series is never
  accepted on a later attempt.
- `SCI_SEARCH_DATA_CONNECTORS` (default on) disables the connector stage for comparison or rollback.

## Current evidence from the repository

Measured over the 32 stored data runs in `data/local_research_runs` (2026-09-29 to 2026-10-09):

- 18 runs produced no analysis; about 120 candidate sources were rejected. Since 2026-10-05,
  closest to the current code, 2 of 6 runs succeeded.
- Every success used a source with a dedicated route: CBS (CSV endpoint), Eurostat (SDMX in
  `retrieval.eurostat_download_url`), the EFFIS workbook, NOAA and Ember.
- Recent rejections cluster in three groups:
  1. JavaScript-only pages with no static links (about 11 of 40): `waterinfo.rws.nl`, the GRDC
     portal, AIMS metadata pages, eAtlas, Nextcloud shares.
  2. Search results about data rather than data (about 10): PDF reports, contact and 404 pages,
     station-location tables, session-specific Eurostat views.
  3. The right dataset rejected while being read: a wrong download link, unlabelled CBS codes,
     merged spreadsheet headers, IRENA's PxWeb.
- The same Eurostat dataset (`demo_mlexpec`) was found in 4 of the 5 life-expectancy runs; 2 of those failed, each on
  a different path (wrong link, viewer page, unfiltered dump).
- `workflow.execute` (`sci_search/data_research/workflow.py`) is one function of about 900 lines
  with web search wired in at the start. `prepare_table` (`packages.py`) dispatches on a `reader`,
  and the sandbox calculation in `artifacts.execute_analysis` reruns it from the stored raw bytes,
  failing the analysis on any difference.
- Three specific defects were fixed on 2026-10-12 before this design: EFFIS rejected named-country
  scopes, the CBS reader rejected measures repeating a title in another unit, and saved Eurostat
  views (`__custom_<n>`) resolved to HTTP 404.

API behaviour probed on 2026-10-12:

- Eurostat: the dataset list (`/sdmx/2.1/dataflow/ESTAT/all?detail=allstubs`, 7 MB, English names)
  can be searched locally. `dataflow/ESTAT/<id>?references=descendants` returns the structure with
  codelists. A key-filtered query (`data/demo_mlexpec/A.YR.M+F.Y_LT1.NL+DE/?format=TSV`) returned
  863 bytes; the unfiltered dataset is 4.9 MB.
- CBS: the catalogue (`opendata.cbs.nl/ODataCatalog/Tables`, 5,983 tables, 0.8 MB) can be searched
  locally. `datasets.cbs.nl/odata/v1/CBS/<id>/MeasureCodes` returns labelled measures with units.
- PxWeb: v2 (Statistics Sweden, `statistikdatabasen.scb.se/api/v2/tables?query=`) searches
  server-side and serves data by GET. v1 installations search at installation-specific paths
  (Statistics Norway: `data.ssb.no/api/v0/en/table/?query=`) and serve data only by POST.
  IRENA (`pxweb.irena.org/api/v1/en/IRENASTAT`) exposes a folder listing.
- OWID: `ourworldindata.org/api/search?q=` returns chart slugs.
  `grapher/<slug>.csv?csvType=filtered&country=NLD~DEU` and `grapher/<slug>.metadata.json` return
  the data and its metadata.

## Components

New package `sci_search/data_research/connectors/`:

- `base.py`: the dataclasses `DatasetCandidate` (connector, id, title, frequency, first and last
  period, landing URL) and `DatasetDescription` (dimensions with labelled codes, measures with
  units, time coverage, licence, definitions text), the connector registry, selection validation,
  and host rerouting.
- `eurostat.py`, `cbs.py`, `pxweb.py`, `owid.py`: one connector each.
- `stage.py`: the connector stage of the workflow (search terms, candidate choice, code
  selection, fetch, recovery) as a function `workflow.execute` calls before web search.

Each connector implements four functions:

| Function | Runs | Does |
|---|---|---|
| `search(terms, scope)` | outside the sandbox | returns at most 10 `DatasetCandidate`s |
| `describe(candidate)` | outside the sandbox | returns a `DatasetDescription` |
| `fetch(candidate, selection)` | outside the sandbox | requests exactly the selected slice; returns raw bytes and the exact request (URL, and body for POST) |
| `normalize(raw, selection)` | in the sandbox as well | returns the existing long-form table and per-row provenance |

`selection` is plain data: `{"connector", "dataset", "measure", "filters": {dimension: [codes]},
"entity_dimension", "start_year", "end_year"}`. It is validated against the `DatasetDescription`
before fetching.

`normalize` is a pure function registered as a `reader` in `prepare_table`, and each connector
module is added to `artifacts.ENGINES`, so the sandbox calculation reproduces the table from the
stored raw response. Its output has the columns Year, the entity label, one column per remaining
filtered dimension (labels), Value, Unit and Status. The connector also returns the column mapping
for `analyse_csv`, so the model does not map columns for connector data.

Moved into connectors:

- `packages._cbs` becomes the CBS `normalize` for CSV packages; `prepare_table` keeps
  recognising CBS ZIPs by delegating to it.
- `retrieval.eurostat_download_url` and `statistical_tables` become part of the Eurostat
  connector; `retrieval._await_eurostat` is reused for the asynchronous delivery protocol.

Catalogue caching: the Eurostat dataset list and CBS catalogue are cached per calendar day under
the data directory. Each run records the hash of the snapshot it searched.

Fetcher: `retrieval.fetch_public` gains a POST variant for JSON bodies (at most 64 KB) with the
same public-address check, DNS pinning, redirect validation and size limit. Only the PxWeb
connector uses it.

Hosts: each connector has a fixed host set. PxWeb uses a reviewed list (Statistics Sweden,
Statistics Norway, Statistics Finland, IRENA) with each installation's API version and search
path. A connector never requests a URL supplied by the model; dataset IDs are matched against a
per-connector pattern.

## Data flow

The connector stage runs at the start of `workflow.execute`:

1. **Search terms.** One model call turns each requested measurement into 2 to 4 search terms, in
   English and in a connector's language where relevant (Dutch for CBS). Without a configured model,
   the measurement text is used. Connectors are searched one after another; each request has the fetcher's timeout.
2. **Candidate choice.** The model sees the merged candidates (title, connector, frequency, period
   range) and picks at most 4 datasets with a reason each, preferring annual series that cover the
   requested years.
3. **Code selection.** For each chosen dataset, `describe` provides the metadata. The model fills a
   strict schema whose enums are the observed codes. Codes are first reduced to those present in the
   dataset (Eurostat and CBS availability queries), and countries to `strategy["countries"]` when set.
4. **Fetch and read.** The slice is fetched and stored as the source artifact; `normalize` builds the
   table; the existing `analyse_csv`, `semantics.assess` (with the dataset's definitions as
   documents), `execute_analysis`, provenance and replay follow unchanged.
5. **Hand-off.** Measurements still uncovered go to the existing web-search workflow, when the
   provider supports web search, restricted to those measurements.

Host rerouting: a web-search candidate on a connector host whose URL contains a dataset ID enters
at step 3 instead of the scraper. Recognised forms: Eurostat `databrowser/view/<id>` and
`web/products-datasets/-/<id>` (with `__custom_<n>` removed), CBS `cijfers/detail/<id>`,
`opendata.cbs.nl/ODataApi/OData/<id>` and `datasets.cbs.nl/.../<id>`, OWID `grapher/<slug>`, and
table paths on the listed PxWeb installations.

Connector gaps: a web candidate whose page is JavaScript-only or has no static links is recorded in
`result["connector_gaps"]` as `{host, measurement, evidence}`. The dashboard shows it as "needs an
API connector for <host>".

## Error handling and recovery

Every failure is classified, and each class has a fixed recovery:

| Class | Example | Automatic recovery | Limit |
|---|---|---|---|
| Model selection error with an informative reason | unobserved code; too many entities; "no results for this key" | Return the error to the model with the facts it needs (valid codes, or combinations that contain data) for a new selection | 2 repairs per dataset |
| Wrong dataset | semantic review rejects the meaning; monthly-only; years not covered | Next candidate. The rejection reason goes to the model, which reformulates search terms for one more search round | 1 extra search round per measurement |
| Transient | timeout; HTTP 5xx; Eurostat asynchronous delivery | Wait and retry; follow the asynchronous protocol | 1 retry; 6 status checks |
| Connector cannot read the response | `normalize` meets an unknown format | No model loop. The same raw bytes go to the existing file path, including Python recovery; the case is recorded as a connector defect | the existing 3 Python attempts |

After each round, the reflection step used by `python_recovery` chooses repair, another dataset,
a different search, or stop. Its reason appears in progress messages and the dashboard.

Every failed step is recorded as an assessment with `failure_stage` `connector:<step>` and a
readable reason. A connector failure never stops the run.

Limits: 5 MB per raw response, the existing 50,000-row limit, at most 60 entities per selection,
and a year range within the dataset's coverage.

Meaning rules, unchanged in strictness:

- Annual data only: Eurostat `freq=A`, CBS `JJ00` periods, PxWeb time codes in year format, OWID
  `year`. Other frequencies are rejected with "dataset is <frequency>; no aggregation was performed".
- Status is kept: Eurostat flags such as `p` and `e`, and CBS provisional status, go into the Status
  column. Missing values stay missing, never zero.

## Recorded provenance

Each connector analysis records: connector and dataset ID; the exact request (URL, and body for
POST); the response SHA-256; the catalogue snapshot SHA-256 it was found in; retrieval time; the
licence from the metadata (CC BY 4.0 for Eurostat, CBS and OWID; per installation for PxWeb); and
the model's candidate choice and code selection with their reasons. Replay uses the stored raw
response and works offline.

## Testing

Offline, in the standard suite:

- Recorded real responses per connector (catalogue excerpt, metadata, data slice) as fixtures under
  `tests/fixtures/data_research/connectors/`. `normalize` is tested on those bytes, including status
  flags, missing values and the period formats `2024`, `2024JJ00` and `2024 `.
- Selection validation: unobserved code, too many entities, years outside coverage, non-annual
  frequency.
- Each recovery class with scripted model replies (`complete=lambda ...`): a code repair succeeds;
  "no results for this key" uses availability; a semantic rejection reformulates the search; an
  unknown format reaches Python recovery; limits stop with a clear reason.
- Host rerouting for each recognised URL form, and no rerouting for other hosts.
- The POST fetcher with the same DNS-pinning, redirect and size tests as GET.
- Offline sandbox replay of a connector analysis from its stored raw response.

Live acceptance, opt-in (a marker enabled by `--run-live-data`, like `--run-retained-corpus`):
runs the benchmark questions against the real APIs and writes the outcomes to
`docs/operations/data-connectors-acceptance.md`.

| Question | Before (stored runs) | Target |
|---|---|---|
| Life expectancy for men and women by European country | 2 of 5 | succeeds via Eurostat |
| Renewable electricity share in NL, DE and DK | succeeded via Ember | also succeeds via Eurostat or CBS |
| Burned area in Spain, Portugal and Greece | 1 of 2 | succeeds via EFFIS |
| Annual mean CO₂ at Mauna Loa | 2 of 3 | unchanged (NOAA route) |
| Electricity storage in the Netherlands | 4 of 9 | succeeds via CBS 85929NED |
| Rhine discharge at Lobith | 0 of 3 | names the Rijkswaterstaat connector gap |
| Coral cover on the Great Barrier Reef | 0 of 1 | names the AIMS connector gap |

With Mistral and no web search, the connector-covered questions (life expectancy, renewable share, electricity storage) must succeed; burned area and CO₂ use non-connector sources and need web search.

## Compatibility and rollback

- The analysis result shape is unchanged apart from the new `connector_gaps` list and connector
  provenance fields; the dashboard and exports read existing fields as before.
- Stored runs replay as before. CBS packages and Eurostat TSVs prepared by earlier runs still
  normalise through the moved code, which keeps their reader names.
- `SCI_SEARCH_DATA_CONNECTORS=0` skips the connector stage and restores the previous behaviour.

## Out of scope

- Connectors for Rijkswaterstaat, AIMS, GRDC, CKAN portals and the World Bank. The connector-gap
  record determines which to build next.
- Non-annual output, aggregation of monthly or quarterly data, and sub-national geography beyond what
  a dataset's own codes provide.
- Linking data results to literature findings.
