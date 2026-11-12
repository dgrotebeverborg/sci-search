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

### Recovery of supported data after live acceptance checks

Missing measurement definitions now trigger bounded retrieval of the original publisher's
metadata before code reselection. Eurostat metadata may refer to underlying methodology; observed
related metadata links are followed within a small request limit. If those documents are missing
or insufficient, one metered search per run can retrieve up to two documents from the original
publisher's host. Search snippets are not evidence: the downloaded bytes, source URLs, exact
passages and hashes are retained. The unchanged observations undergo a fresh meaning review.

Python extraction can retain supported years and entities as well as supported measurements.
Selections must refer to previously extracted observations and remain within the requested
period; the next extraction must respect them. The final analysis keeps the original scope,
so omitted years stay missing. Partial evidence does not bypass semantic review. Web research
stops when the retained observations satisfy the coverage contract, avoiding unnecessary
additional sources and model calls.

Structured numeric locators now support original text line/column positions, whitespace or
single-character delimiters, and explicitly declared conversion factors. Numeric checks inspect
the original bytes; only converted values allow a four-ULP floating-point tolerance. Conversion
meaning still requires documented units. Verified line samples and retrieval metadata are
provided to the semantic reviewer. Free-text references remain explicitly unverified.

These are additive research-artifact fields; no database migration is required. Rollback means
reverting the recovery changes for new runs. Existing retained runs keep their bundled verification
and replay code; their source bytes and original results must not be rewritten. Monthly/daily
output and repository-specific acquisition (including a possible Datahugger adapter) remain
separate follow-up work.

Validation of this follow-up: 1,356 tests passed, 24 skipped and two subtests passed, with 84.94%
coverage. Ruff, Pyright (zero errors), build, secret scanning and the locked dependency audit
passed. Three bounded live acceptance cases produced 28 values matching independently retrieved
primary data: 16 life-expectancy values, eight renewable-electricity percentages and four CO2
annual means. Both electricity percentage-point changes matched independent calculations; all
three retained runs replayed offline. The CO2 result explicitly retains the Maunakea substitution
caveat. These are individual acceptance cases, not a representative accuracy benchmark. Raw
sources, intermediate unsuccessful attempts and final acceptance records remain local and are
not committed.

### Preserve requested scope and source context

Regional geography no longer expands implicitly into every constituent country in the coverage
contract. Explicit country lists, measurement-specific entities and requested breakdowns retain
their precedence. A country series still cannot stand in for a regional aggregate, and separate
sources are not spliced to manufacture a complete interval.

Observed parent-to-download links carry the parent's retained metadata into the next assessment,
extraction and meaning review. Matching a publisher hostname alone is insufficient. Reassessment
adds documentation to the original source context even when extraction remains blocked; the
document URL, byte hash and artifact path are retained in `source-context.json`. The already
bounded source text is not truncated again at the front when passed to Python recovery, so newly
appended definitions are available for exact citations.

Python observations may optionally declare `measurement_definitions`: a requested measurement,
a distinct source-supported label, definition and `narrower` relationship. Published series keep
the narrower label, original `requested_measurement` and `coverage_relation`. An independent
meaning review must also substantiate the subset relationship with exact source citations.
Proxy, unresolved and conflicting relationships are rejected. These series remain supplementary:
they never fill the broader measurement's coverage cells. The numeric verification and standalone
replay use the same observation contract; unsupported units and definitions remain blockers.

A cited geographic label conflict has a separate `clarify_labels` recovery action. It is unavailable
when other meaning checks or source citations fail. Only entity labels may change: all observation
values, units, years, measurement names, source references and row order must remain identical.
The output then undergoes fresh numeric verification and meaning review. This supports explicit
composite-record labels without weakening the rule against guessing missing definitions.

OWID exposes publisher variable IDs and hashes of the selected indicator metadata. A second chart
is skipped before another meaning review only when that identity, definition, entities, units,
measurement and annual observations match an already retained analysis. Coincidentally equal
numbers, different definitions and revised values are not deduplicated. The duplicate assessment
links to the retained source and does not count as independent evidence.

Follow-up reassessments use source-byte and context identities rather than only candidate indices.
Two consecutive invalid or no-new-source actions stop planning with explicit unresolved gaps.
Interactive pages without observed downloads prompt a search for a documented API or export;
this does not add browser execution or invent endpoints. All changes are confined to the data
path and additive artifacts; literature research retains its separate evidence stream.

Validation: 1,386 tests passed, 24 skipped, two subtests passed, 84.83% coverage; final targeted
checks passed (58 tests), Ruff passed and Pyright reported zero errors. Independent review found
and verified fixes for long-context truncation and malformed extraction payloads. The three
reference data questions again retained all 28 independently checked values with complete
requested coverage. An initial CO2 attempt exposed incomplete composite-record labelling;
the final case passed after the generic label guidance and constrained repair change. All three
reference cases and the wildfire case replayed offline.

The wildfire case retained five analyses, including explicitly narrower forest-fire series,
and detected a duplicate OWID count series. It remains partial: early count years are absent and
overlapping burned-area sources require reconciliation. Compared with the prior run, model calls
fell from 47 to 38, downloads rose from 47 to 57 and elapsed time rose from 519 to 570 seconds.
This is evidence of broader retained coverage, not a speedup or a representative accuracy claim.
The local acceptance record is `data/validation_runs/scope-context-20261015/acceptance.json`;
raw runs and intermediate failures are intentionally excluded from Git.
