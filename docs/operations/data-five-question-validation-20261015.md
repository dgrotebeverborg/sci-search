# Five-question data validation, 15 October 2026

Two live rounds found useful improvements, but do not establish that arbitrary data questions
work reliably. Internet and measles now have complete numerical series; housing remains partial,
PM2.5 remains blocked, and hydropower discovery changed which half of the requested inputs it found.
Complete numerical coverage does not mean that all requested methodological explanations or
derived outputs were produced.

## Protocol

Baseline: `19bf500`. Provider/model: Codex / `gpt-6-sol`. Each data investigation allowed
600 seconds, 80 model calls, 8 searches and 100 downloads. Limits are checked before operations;
an in-flight call can finish after the time limit. The baseline interpreted the Dutch question;
the second round reused that brief to avoid changing the question between measurements.
Deterministic validation could remove an exactly duplicated geographic breakdown.

The table reports **workflow time**, excluding initial question interpretation. Independent
reference downloads were used only for checking results, never injected into source discovery.
These are single runs with model and search variability, not a controlled statistical benchmark.
Only the data workflow ran: literature research is a separate component and was not evaluated here,
including for the measles brief that proposed both routes.

## Before and after

| Question | Baseline | Second round | Assessment |
|---|---|---|---|
| Household internet access, NL/DE/PL, 2010–2025 | 8 values; 605 s | 48 values; 37 s | All country-years retained. German 2021 break flag retained; endpoint comparison withheld. Full history of definition changes is not established. |
| Annual PM2.5, Amsterdam/Paris/Warsaw, 2005–2024 | 0 values; 620 s | 0 values; 607 s | Still blocked. Station metadata, concentration downloads and station-year identity need more reliable handling. |
| Dutch house prices and household income, 2000–2024, nominal/real indices | 50 values; 603 s | 64 values; 617 s | 25 house prices, 25 CPI values, and 14 disposable-income values (2011–2024). Income before 2011 and the requested 2000-based nominal/real outputs remain absent. |
| Hydropower in Norway/Sweden, 1990–2024, TWh and share | 70 hydro values; 609 s | 70 total-generation values; 572 s | Not a demonstrated improvement: the second run loses the hydro numerator, retains the denominator in GWh, and produces neither the requested TWh output nor the share. |
| First-dose measles coverage, Belgium/France/Italy, 2000–2024 | 0 values; 410 s | 75 values; 73 s | All country-years retained from WHO/UNICEF via OWID. Country/year-specific methodology and target-population changes still require documentation. |

Coverage bookkeeping also improved: redundant country/city axes created impossible Cartesian
products. Internet went from 9 cells to 3, measles 9 to 3, hydro 8 to 4, and PM2.5 18 to 6.
The frozen PM2.5 brief still incorrectly requires both citywide and station series. The new
interpretation instruction treats “identify which spatial basis applies” as source qualification;
that prompt change was checked separately, not credited as a successful PM2.5 data run.

## Changes

- Remove only exact duplicate geographic axes, preserving genuine breakdowns such as sex or
  country of birth. City matching can retain a named city with its parent country without
  allowing country-only results to satisfy a city request.
- Inspect CBS annual period codes in mixed monthly/annual datasets. Use bounded OData selections
  when full packages are too large or ambiguous; do not invent annual aggregates from months.
  Preserve fixed regional identity and ignore duplicate measure labels outside the selected slice.
- Supply statistical status flags for the selected years to the meaning review, including breaks
  that occur between the first and last observations.
- Distinguish valid raw observations from missing later calculations. Missing rebasing inputs or
  a full history of definition changes need not discard correctly defined raw series. Numerical
  source checks and restrictions on comparability remain in force.
- Read observed publisher PDF methodology inside the existing isolated Python runner. Retain the
  original bytes and page markers; reject encrypted, excessive or effectively textless documents.
  This supports definition evidence, not OCR or arbitrary PDF table extraction.
- Clarify that published percentages, rates and indices are base series. Numerator/denominator
  inputs are required for newly computed ratios, not to reconstruct every published percentage.

## Independent verification and regressions

All **257 retained second-round values** matched separately downloaded references: Eurostat
JSON-stat for internet (48) and total electricity (70); CBS OData for house prices (25), income
(14), and CPI (25); World Bank's WHO/UNICEF series for measles (75). This verifies retained
numerical observations, not the completeness of explanations, discovery, or derived outputs.
Every retained analysis in both rounds replayed offline with the saved source hashes and code.

The baseline OWID CPI series differs slightly from the separately fetched current World Bank
series (maximum difference 0.0064421 index points). Its vintage was not reconciled; it is not
reported as an exact match. Baseline Ember hydropower differs from Eurostat by at most 0.005 TWh,
consistent with Ember's displayed precision; this is a cross-source comparison, not an exact oracle.

Three earlier reference questions were also rerun:

| Reference question | Result |
|---|---|
| Life expectancy, NL/DE, women/men, 2020–2023 | 16/16 reference values; full coverage; 52 s; offline replay passed. |
| Mauna Loa CO2, 2020–2023 | 4/4 reference values; full coverage; 103 s; offline replay passed. |
| Renewable electricity share, NL/DE, 2020–2023 | Initially blocked: 0/8 in 207 s. After the PDF documentation fix: 8/8, full coverage, 81 s; offline replay passed. |

The failed renewable run is retained. Its definition search found PDFs that were previously
decoded as plain text and discarded. The successful retry used the additional PDF fix; the main
five-question second round did not. One real publisher PDF exceeded the explicit text limit and
was correctly rejected; another yielded usable methodology. Fresh interpretation probes are
separate from all frozen-scope data runs.

Fresh interpretation probes caught an overcorrection: the initial share-input instruction made
the internet question request household counts instead of the published percentage. After the
wording correction, internet remains a percentage, PM2.5 no longer requires both spatial types,
and housing retains its requested calculations. The final probe still failed validation for
hydro and added methodological metadata as an extra measles measurement. Interpretation is
therefore not claimed to be fully reliable; these failures are retained too.

Local verification: 1,401 tests passed, 24 skipped, two subtests passed; 85.07% coverage. After the
last prompt wording adjustment, 35 focused interpretation/coverage/PDF tests passed. Ruff,
formatting, secret scanning, package build and Pyright passed (zero errors; 234 existing warnings).
An earlier browser test timed out waiting for the dashboard; its focused rerun and both subsequent
full-suite runs passed without frontend changes. Independent review found no important issues.

## Remaining work

Follow-up: the explicit calculation layer below has since been implemented and separately
validated; see [calculation validation](data-calculation-validation-20261015.md). This report
retains the original before/after results.

1. Represent requested calculations explicitly: base-year indices, inflation adjustment, unit
   conversion, and numerator/denominator joins need their own completion checks. Raw-data coverage
   must not imply these outputs exist.
2. Make discovery more stable across equivalent runs, preserve numerator and denominator progress,
   and test repeated runs before claiming that unrelated questions cannot regress.
3. Improve station-series discovery and identity checks for air-quality data, preserving the
   distinction between individual stations and citywide estimates.
4. Evaluate explanations of definition changes and measurement methods separately from numerical
   coverage. A missing account should remain visible even when annual values are retained.

## Retained evidence

Local artifacts are under `data/validation_runs/five-questions-20261015/` and are not committed:
`manifest.json`, `runner.py`, `implementation.patch`, `before/`, `after/`, `references/`,
`scorecard.json`, `independent-final-checks.json`, `regression/`, `regression-pdf/`, and
`interpretation-probes*/`. Run folders retain progress, outcomes, source artifacts, reviews,
extraction/calculation code and `reproduce.py`. The initial patch and later PDF/prompt changes
are distinguished so that rerun results are not attributed to untested code.
