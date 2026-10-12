# Research flow quality implementation plan

**Goal:** Make confirmed question meaning control discovery and evidence screening, reject unsupported model claims, and clearly distinguish execution from scientific adequacy.

**Architecture:** Preserve a validated structured research plan with each question brief and run. Pass that same plan through planning, screening, extraction and rebuilds. Keep source-quote validation and add a separate, fail-closed semantic review before model assertions become findings. Expose a derived evidence-quality status alongside the existing durable run lifecycle.

**Scope:** The user approved all four sequential priorities in chat and requested autonomous implementation and testing. Preserve existing results, explicit model selection, tenant isolation and deterministic operation without a model. Do not alter unrelated promo files or disclose credentials.

## Tasks

- [x] Confirmed interpretation: structured subject, drivers, geography, evidence scope, intent and exclusions; validate model output; preserve deterministic fallback; persist and reuse the plan across execution and rebuilds; show fields before confirmation.
- [x] Claim support: independently verify cited passages support each assertion and answer the requested relationship/location; fail closed on missing/invalid review; retain rejection reasons and model provenance; test unsupported extension, reversed causality and geographic extrapolation.
- [x] Scientific regression set: reusable multi-domain cases with relevant/irrelevant sources and supported/unsupported claims; deterministic regression tests and recorded live evaluation.
- [x] Reporting: show processing complete separately from insufficient/partial/adequate evidence, and report actual AI usage for coverage-limited results.
- [x] Cooperative cancellation: stop cancelled local runs between provider/acquisition operations so queued reviews can proceed; retain safe persisted cancellation state.
- [x] Validation: unit/API/security/contracts, browser flows, isolated PostgreSQL/Redis/MinIO integration/system tests, lint/types, saved-corpus replay and fresh same-question deep review; inspect live findings, not just counts.

## Review focus

- Old persisted briefs/runs must retain a safe fallback and remain readable.
- User-confirmed plans cannot leak between concurrent requests or tenants.
- Missing semantic judgments must not silently approve claims.
- Quotes can be authentic while their interpretation or direction is wrong.
- Completion and coverage status must agree across UI, reports and exports.

Each task follows failing regression test, minimal implementation, focused verification, then integrated review. Re-run only checks affected by later fixes. A model review reduces risk; it does not constitute expert scientific validation.

## Verification results (2026-09-28)

- Combined suite: `.venv/bin/python -m pytest --run-retained-corpus -q --tb=short` — 626 passed, 4 explicitly opt-in deployment/restore checks skipped, 2 subtests passed. Includes 30 browser tests and isolated PostgreSQL/Redis/MinIO integration/system tests.
- Historical scientific checks include 43 diverse questions and 20 metamorphic cases; the tomato-composite-subject and ENSO-alias regressions found during testing were repaired without weakening confirmed-plan authority.
- New synthetic benchmark: five domains, 16 study vignettes and 10 labeled assertions. Live `gpt-4.1-mini` support review agreed with all 10 labels (5 supported, 5 unsupported). This small regression set is not a general accuracy estimate.
- Ruff passed; Pyright: 0 errors, 190 warnings (the repository retains existing typing warnings). `git diff --check` passed.
- Replay of acquired South America texts caught background-only HIV/publishing papers, missing factor aliases, and abbreviated adjudication quotes. Exact quote checks remain enforced; uncertain or invalid judgments cannot promote papers.
- A completed live deep run retained 3 relevant studies and 3 bounded assertions, with no overall answer because biophysical-driver coverage was insufficient. The final same-brief run `59b58382-3abc-468c-9fcf-120273b381b2` acquired 25 full texts, retained 4 studies and reported partial evidence with 2 bounded findings. OpenAlex returned HTTP 429 for some downloads during repeated testing. An isolated replay of the earlier 38 retained full texts also retained 4 studies and withheld the overall answer for insufficient coverage. The saved dashboard reports the selected OpenAI `gpt-4.1-mini` model correctly; the HTML export reports partial evidence and the 14-file research ZIP passed archive-integrity verification.

- Final cooperative-cancellation regressions pass: the cancelled run stops between requests and releases the local worker for queued work. An in-flight network request still finishes or times out. The provider interface cleanup passed the 14 focused manager/plan tests and all 6 local-run/cancellation tests; Ruff and Pyright were rechecked.
