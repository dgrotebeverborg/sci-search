# Data research maintainability — 12 November 2026

The approved review findings are addressed through bounded helper extractions.
Numerical algorithms, scientific expectations and acquisition budgets are unchanged.
Earlier uncommitted correctness fixes are retained.

## Shared boundaries

- `replay_manifest.engine_modules` provides one transitive module manifest for
  ordinary source execution, derived execution and legacy exports. Standalone
  legacy tabular ZIPs now include `calculations.py` and replay without the installed
  repository.
- `artifact_validation.validate_artifacts` is a portable standard-library helper
  used by source and derived replay, derived input checks and resume. It rejects
  path escape, symlink components, missing/nonregular files and changed hashes.
  Newly generated replay packages retain their own copy of the validator.
- `publication.publish_analysis` owns execute, persist, append and successful
  assessment transition. Initial/fallback and reassessment overlap policies remain
  explicit and distinct. Successful recovery archives previous diagnostics under
  `initial_assessment` rather than leaving failure fields on the current result.
- `source_state` owns snapshot creation, stable retained-source resolution and
  digest-bound restoration of resumable source contexts. Existing positional
  inputs use an explicit adapter. Unknown, ambiguous or invalid references fail
  instead of selecting a source by list order. Legacy context is restored only
  when its assessment association is unambiguous.
- `failures.record_failure` separates expected source errors from internal
  processing errors. Internal errors retain a technical traceback and do not
  establish source unavailability. Nested mapping/transform checks no longer
  convert internal TypeError/KeyError into source gaps. Secondary recovery errors
  remain separate from the original source failure. Cancellation and budget
  exhaustion propagate unchanged.

Planning consumes an explicit fresh state snapshot provider. Existing generator
callers remain compatible. Resuming does not refresh retained observations over
the network, and malformed/ambiguous source contexts do not become new evidence.

## Replay requirements and tests

The full environment inventory remains in `environment.json`. Installation pins
are limited to identified static imports in retained scripts and copied helpers,
including installed pandas Excel readers. Equivalent duplicate distribution names
are normalized. Pip resolves distribution dependencies; opaque dynamic imports
and other indirect imports remain documented environment uncertainty rather than
a guarantee of a complete minimal environment.

Shared workflow strategy/mapping builders now live in
`tests/data_workflow_fixtures.py`, with consumers importing that fixture module.
New replay, publication and failure-diagnostic contract tests cover the reviewed
problems and the edge cases discovered during independent review.

Ruff passes. Targeted Pyright over the changed production boundaries reports zero
errors and warnings. Independent review found no remaining blocking findings after
the dependency, nested-error and diagnostic-transition corrections.

No benchmark expectations or historical research artifacts were rewritten, and
the Python runner continues to require bubblewrap isolation.

## Final verification

- Complete suite with isolated PostgreSQL, Redis and MinIO services: **1,704 passed,
  24 skipped and 39 subtests passed**, 144.66 seconds.
- Retained scientific checks: **39 passed and 7 subtests passed**, with the same
  existing failure in
  `QualityBenchmarkTests.test_diverse_question_benchmark_passes_with_exact_provenance`:
  `rebound-time-comparison` expects partial and receives adequate. This expectation
  remains unchanged and requires separate adjudication.
- Ruff passes; targeted Pyright over all changed production boundaries reports
  **zero errors and zero warnings**.
- Two independent review tracks checked replay/validation and workflow/error
  contracts. Their dependency, nested-error and diagnostic-transition findings were
  reproduced in regressions and corrected before the complete-suite run.

Tests requiring bubblewrap ran outside the outer Codex sandbox, retaining the
application's own isolation. Changes remain local and uncommitted.
