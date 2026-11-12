# Scope-bound task evidence — 11 November 2026

`assess_answer_adequacy` previously counted method, method-limitation and
explanatory statements even when those records failed the requested subject,
statement geography or outcome scope. An unrelated record could consequently
unlock an overall answer. Exact-count and diagnostic checks also reported coverage
from such records, although their separate qualification gates prevented the same
overall-answer bypass.

All five checks now use the existing answer-record scope predicate. The existing
scope rules, extraction, benchmark expectations and source selection are unchanged.
This change does not implement a scientific comparability assessment.

The regression test first reproduced all 15 out-of-scope combinations, then passed
after the fix. Five matching-scope controls remain answerable. The complete coverage
test file passes: 12 tests and 20 subtests. Ruff passes; targeted Pyright reports
zero errors and six warnings in existing test assertions. A separate read-only code
review found no blocking issues.

The full suite passes with the isolated PostgreSQL, Redis and MinIO test services:
1,644 passed, 24 skipped and 22 subtests passed in 118.22 seconds. An initial run
without those services produced 10 failures and 39 setup errors; these disappear
with the documented integration stack running. A redirected-output rerun stalled
and was interrupted; the successful rerun used normal output and a 60-second
per-test faulthandler timeout.

Retained-source validation artifacts are in
`data/validation_runs/scope-guard-20261111/`:

- `locked24.json`: 8 adequate, 13 partial and 3 insufficient, matching the previous
  replay. All four boundary policies pass and all summary citation IDs are valid.
  The goat diet methods case now also reports missing source-reported method
  limitations; its overall status remains partial.
- `references5.json`: exactly matches the October 18 final reference report,
  including 15/19 known references used and its existing distractor warnings.
- The retained scientific suite reports 36 passed and one unchanged failure:
  `QualityBenchmarkTests.test_diverse_question_benchmark_passes_with_exact_provenance`,
  case `rebound-time-comparison`, expects partial and receives adequate. The stored
  sources contain paired short-/long-run estimates in different contexts. This
  repair does not adjudicate that scientific expectation or relax the test.

These are deterministic replays over retained sources. No new live discovery,
downloads, model syntheses or independent human scientific reviews were performed.
