# Local research issue registration

`ResearchRunManager` automatically merges diagnostic observations into `issues.json`
beside each persisted `run.json`. This covers managed local research runs, including
failed and cancelled runs with retained data analysis. Direct calls to standalone
data workflows do not use this hook.

Data, literature and run lifecycle observations remain separate. Repeated progress
updates are deduplicated within a run. The ledger retains first/last observation time,
a source-code fingerprint and a pointer to the existing diagnostic. It does not copy
questions, source URLs, source text or raw exception messages. Original run artifacts
still contain their normal research content and need the same access protection.
Registration failures emit only the exception class and do not fail research.

Generate a report from the repository environment:

```sh
python -m sci_search.run_issues --root data/local_research_runs \
  --since 2026-10-18 --output data/issue-reports/2026-10-18.json
```

Without `--backfill` this only reads ledgers. `--since` is a UTC date filtering the
last observation time. Groups count distinct pipeline run folders, so retries in
separate folders count separately; repeated progress saves do not. Examples point
back to original artifacts. Corrupt ledgers are excluded and reported; a nonzero
exit status means at least one ledger or backfill snapshot could not be processed.

To register retained historical snapshots once:

```sh
python -m sci_search.run_issues --root data/local_research_runs --backfill \
  --output data/issue-reports/historical.json
```

Backfill leaves original snapshots and existing ledgers untouched and skips active
run statuses. Historical observations use the retained finish/creation timestamp and
`unknown_historical` as the code fingerprint: the current code is not attributed to
old runs. They cannot reconstruct transient errors absent from the retained snapshot.

## Review procedure

Run the report periodically and inspect example diagnostics for recurring categories.
Confirm whether each is a software defect, source limitation, unsupported question,
or correct scientific withholding before prioritizing it. Categories are coarse
triage signals, not root-cause diagnoses. Frequency alone is not scientific impact;
cancelled runs and rejected sources can represent correct behavior.

For confirmed defects, retain a regression case, implement a bounded fix and compare
both data and literature benchmarks before rollout. Disappearing observations are
not marked resolved automatically. This feature does not schedule reviews, change
prompts or code, or automatically turn observations into regression tests.
There is no frontend issue dashboard yet.
