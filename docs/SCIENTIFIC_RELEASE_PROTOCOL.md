# Scientific release protocol

Sci-Search separates deterministic release gates from live provider observations and from
researcher-owned scientific gold labels. A passing software build is not, by itself, evidence that
a literature review is scientifically complete.

## Deterministic release gates

Every release must pass the locked question, metamorphic, reliability, source-grounding,
validation, provider-contract, authorization, migration, and full engineering suites without live
credentials. Exact provenance and zero researcher-confirmed unsupported answer assertions are
independent hard gates: an aggregate score cannot compensate for either failure. The gold-label
export must conform to `benchmarks/researcher_gold_v1.schema.json` and contain named, independent
researcher revision provenance.

## Scheduled live protocol

The immutable case selection and budgets are in
`benchmarks/scheduled_scientific_protocol_v1.json`. Version 1 pins the SHA-256 contract of
`researcher_questions_v1.json` and samples a core, difficult-synthesis, and deliberately
unanswerable case. Any question change requires a new protocol version and explicit review; a
scheduled result must never modify the question file or expected gold labels.

The weekly/manual workflow runs only in the protected `provider-contracts` GitHub environment. It
is never triggered by pull requests and reads only environment-scoped OpenAlex and Mistral
credentials. Per case it permits at most five records per query, two acquired full texts, six
acquisition attempts, and one final model-analysis call. The workflow has a 15-minute outer bound
and does not retry the workflow automatically.

Only allowlisted diagnostics are retained: case and question identifiers, run state, coverage
counts, adequacy, citation-integrity status, model status, distinctions, and bounded warnings.
Source passages, full texts, provider response bodies, URLs, request headers, and credentials are
excluded. Sanitized artifacts are retained for 30 days. The raw file remains only inside the
ephemeral runner and is not uploaded.

Live outcomes are always labelled `informational_pending_researcher_review`. Provider drift may
open an investigation or block operational rollout, but current output can never rewrite its own
expected labels. Scientific expectations change only through a separately reviewed benchmark
revision based on independent researcher appraisal.

## Release decision and sign-off

A release is blocked when deterministic tests fail, exact provenance is incomplete, any confirmed
answer assertion is unsupported, migrations fail, or the gold-label contract is invalid. Discovery
recall, screening precision, grounding, conclusion coverage, context preservation, and reviewer
disagreement are reported separately with their predefined thresholds.

Before a scientific-quality release, a named reviewer records the benchmark version, deterministic
result, unresolved live-provider warnings, hard-gate status, and decision. A second domain
researcher adjudicates disputed scientific labels. Until the current benchmark has sufficient
independent gold labels, release notes must describe scientific performance as preliminary rather
than validated.

Run the deterministic protocol checks with:

```bash
python -m pytest -q tests/test_scheduled_scientific_protocol.py
python -m sci_search.quality_benchmark benchmarks/diverse_questions.json
python -m pytest -q tests/test_quality_benchmark.py tests/test_reliability_audit.py \
  tests/test_validation_workspace.py
```
