# Review corrections — 12 November 2026

Four reproduced review findings are corrected without changing historical runs,
benchmark expectations or default acquisition budgets.

## Exact series identity in the data workflow

Coverage source matches now retain `series_index` alongside `source_index`.
Derived input and reference selection use those exact positions, rather than
re-enumerating all series with the same label and entity. Separate male and female
series for the same country can now produce their own requested indices or shares.
Ambiguous sources still block calculation. Missing legacy series indexes fail
closed rather than guessing a stratum.

Coverage binding's existing-assignment guard also checks the exact series index.
A new binding for an unrecognized female code can therefore coexist with an
already recognized male series sharing its country label. Reassigning the same
series to a different requested category remains blocked.

`prepare_jobs` always computes fresh coverage. Derived artifacts retain resolved
`[analysis_index, series_index]` jobs in the existing format, and offline execution
calls `compute`, not `prepare_jobs`. Existing resolved-job replay is unaffected by
whether an older source artifact contains the new coverage field.

## Literature scope corrections

Wearable aliases preserve any prefix qualifier: `wrist-worn wearable devices` can
match `wrist-worn wearable ECG`, but a chest-patch ECG no longer satisfies that
requested subject. General, unqualified device synonyms remain available.

Method, limitation and explanatory checks may inherit subject/topic context from
the same evidence passage. They retain the applicable statement-level geography,
time, population and outcome restrictions. Numerical answer qualification remains
strict. Supporting evidence cannot borrow subject context from a different
passage, even in the same publication. Tests include transition-prefixed and bare
explanations, so acceptance does not depend on a specific opening phrase.

## Verification

Regression cases were observed failing before the repairs and passing afterward.
The focused data run passed 127 tests. The focused literature scope run passed
22 tests and 37 subtests. A separate review found no remaining blocking issues
after the transition-prefixed explanation case was corrected. Ruff passes, and
targeted Pyright reports zero errors and warnings.

The final full suite passed with the isolated PostgreSQL, Redis and MinIO test
services: **1,652 passed, 24 skipped and 39 subtests passed** in 134.37 seconds.
The retained scientific suite reports 39 passed, 7 subtests passed and one unchanged
failure: `QualityBenchmarkTests.test_diverse_question_benchmark_passes_with_exact_provenance`,
case `rebound-time-comparison` (expects partial, receives adequate).

The full command was:

```sh
.venv/bin/python -m pytest -q --tb=short -o faulthandler_timeout=60 -o faulthandler_exit_on_timeout=true
```

Bubblewrap data replay required execution outside the outer Codex sandbox; it
continued using the application's own isolated Python runner.

No independent scientific validation or fresh research benchmark was performed.
The existing `rebound-time-comparison` adequacy disagreement remains a separate
unresolved scientific benchmark expectation; its expected result is unchanged.
