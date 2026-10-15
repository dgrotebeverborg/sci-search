# Adaptive data research implementation

The approved direction is a question-driven investigator that identifies gaps, chooses a
relevant bounded action, and verifies the result. Unknown inputs must produce an explicit
capability or evidence gap, never fabricated observations or silent scope changes.

## Implementation sequence

1. Add a backward-compatible question contract and deterministic coverage evaluation. Track
   measurement, geography, requested breakdowns and actual non-missing years. Use coverage
   throughout connector selection, web fallback, reassessment and reporting. Do not merge
   incompatible sources to declare a complete series.
2. Give the investigation a shared operation budget and durable checkpoints. Supply coverage
   and classified failures to the existing adaptive planner; require new information or a
   changed selection before retrying. Preserve completed source artifacts on interruption.
3. Apply measurement-aware arithmetic and explicit verification levels. Extend independent
   source checks where structured references permit them; keep unverified extraction visible.
4. Extend bounded source inspection and acquisition, reusing existing readers and sandbox.
   Support targeted inspection rather than trusting a fixed leading sample. Keep existing
   access restrictions and replay contracts intact.
5. Persist versioned source knowledge with invalidation, present coverage and stopping reasons,
   and evaluate outcomes against independent expected values and adversarial synthetic inputs.

## Constraints

- Preserve saved dashboards and the existing data result's `partial`/`blocked` contract;
  new coverage and verification fields are additive. Never certify historical results.
- Keep numerical computation and publication checks deterministic; model judgments remain
  explicitly qualified. Source text is untrusted data.
- No live paid calls in deterministic tests. Use retained synthetic fixtures and real sandbox
  execution. Separate infrastructure failures from scientific correctness.
- Implement in the current checkout; preserve unrelated untracked data and promo files.
- Add failing behavioral tests before production changes, then run affected tests and the
  repository gates. Record verification and limitations below.

## Rollout and rollback

No database migration is intended. New strategy fields must accept absent fields in old plans;
new result fields must be optional in renderers. Retain the complete research root before an
upgrade. Rollback restores the previous application version and matching workspace backup;
already downloaded research packages contain their own engines and remain reproducible.

## Execution record

- Initial review: 151 targeted tests passed before implementation. Full baseline started.
- Implementation follows the approved architecture incrementally; individual format adapters
  remain subject to actual acquisition and validation capabilities, not a claim of universal
  data access.

### Implemented scope

- Optional per-measurement requirements, actual observation coverage, conflicting-source gaps,
  bounded planner context and follow-up selection for missing countries.
- Shared operation/time limits, atomic checkpoints and hash-checked resume, including recovery
  of completed source artifacts newer than the checkpoint.
- Measurement-aware changes, direct CSV/JSON value verification, targeted source inspection,
  a bounded CBS OData fallback and project-scoped extraction recipe reuse with fresh review.
- Coverage and verification qualifications in exports and the data dashboard. Literature
  research remains a separate workflow.
- Independent review found aggregate-label false coverage, display-label-hidden conflicts and
  stale-checkpoint source loss; all three received regression tests and fixes.

### Validation and remaining work

- Full deterministic suite: 1,339 passed, 24 skipped, two subtests passed. No paid live model calls.
- Build, secret scan, Ruff lint and formatting pass.
- Pyright reports six possibly-unbound errors (five in connector stage and one in question
  interpretation), plus warnings. The type-check gate is not clean.
- Dependency audit reports 11 advisories in existing urllib3 2.7.0 and pypdf 6.16.2. Dependency
  upgrades require their own compatibility checks; this change does not resolve those advisories.
- Both coverage runs could not combine statement and branch measurement files, including the
  run with an isolated measurement path. All 1,339 tests passed in both runs, but no valid
  aggregate coverage percentage was produced. This test-instrumentation issue remains open.
- After the final label-matching corrections, all 89 affected coverage, resume, connector and
  research-reflection tests passed; Ruff and whitespace checks also passed.
- Broader live acceptance against provider changes and an independently curated real-world
  benchmark remain necessary. Synthetic fixture success is not a claim of universal autonomy.
- Monthly/daily output, browser interaction, OCR and general geospatial adapters remain future
  capabilities. Unknown or unsupported inputs must remain explicit gaps. Coverage checks and
  exact numeric locators do not replace scientific interpretation or semantic review.

### PR validation follow-up

The CI blockers above were addressed after the initial push. The connector now explicitly rejects
an exhausted selection loop, making successful publication paths definite for the type checker;
question interpretation prepares retry arguments before entering its exception handler. Pyright
reports zero errors. Explicit pytest coverage configuration propagates branch settings to replay
subprocesses: the complete suite now passes with 1,342 tests, 24 skips, two subtests and 85.08%
coverage (80% required). Updated pypdf and urllib3 within their existing version constraints;
the locked dependency audit reports no known vulnerabilities. The lock also now includes the
already-declared optional NetCDF dependency. Capability limitations above remain unchanged.
