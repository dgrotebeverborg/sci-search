# Data source quality corrections — 16 October 2026

## Scope

Baseline: `c0a5055`. This implements the source-selection, measurement-definition and unit
priorities identified in [the five-question evaluation](data-five-new-validation-20261016.md).
The literature workflow remains a separate stream and was not evaluated here.

## Corrections

- Filter Eurostat published-series discovery to requested countries and both period boundaries.
  Reject malformed series-key responses explicitly rather than misreporting missing geography.
- Preserve an explicitly recognized unit suffix from publisher measure labels when a statistical
  table lacks a `unit` dimension. For example, `Yield in EU standard humidity - tonnes per hectare`
  no longer becomes a table with an empty unit. An explicit unit dimension takes precedence;
  unknown or conflicting unit declarations remain unresolved. Semantic review is still required.
- Use shared bounded conversion factors in CSV processing and derived calculations. Supported
  additional dimensions include mass, area, mass per hectare, passenger-distance and decimal
  Celsius scales. Unknown units require exact identity. Explicit symbol aliases prevent `mW/MW`,
  `mWh/MWh`, `mg/Mg` and `T/kg` from becoming false identity or cross-dimension conversions.
  A quantity in `1 000 kg` cannot become tonnes per hectare without a documented denominator.
- Bind ordinary CSV output labels to the explicitly selected requested measurement. Retain
  source-coded entities with separately cited geography, without rewriting original codes.
  Identity quotations must occur in source evidence and name both code and geography; the
  meaning reviewer remains responsible for the interpretation. This is not expert certification.
- Give raw-source and extraction reviewers an input-specific scope. The original research question
  is retained as context for exclusions and definitions; unperformed calculations are not their
  task. Extraction instructions likewise distinguish published inputs from requested derived outputs.
  This reduces conflicting instructions but cannot guarantee that a model follows them.

## Controlled verification

A direct Eurostat connector check uses the actual `apro_cpsh1` structure, published keys and TSV
responses, with manually specified observed selections for potatoes (`R1000`) in NL, FR and PL,
1990–2024. This tests acquisition/normalization and is **not automatic discovery**.
All returned non-missing values match a separately downloaded Eurostat JSON reference:

| Published measure | Retained unit | Independent numeric matches |
|---|---|---:|
| Yield (`YLD_HUMD_EU_T_HA`) | tonnes per hectare | 43 |
| Production (`HPRD_HUMD_EU_THS_T`) | thousand tonnes | 75 |
| Area (`AR_THS_HA`) | thousand hectares | 75 |

Thus 193 values match without inventing missing years. The original publisher's distinctions
between sown/harvested/production area and humidity bases still need source-specific assessment;
a correct parser does not prove that all three measures can be divided scientifically.

The [Eurostat crop dataset](https://ec.europa.eu/eurostat/databrowser/view/apro_cpsh1/default/table)
and its retained code-label metadata supply these units. The controlled harness and original
responses are stored under `data/validation_runs/source-quality-20261016/controlled-crop/`.

A deterministic end-to-end station fixture verifies that documented station code 260 maps to
De Bilt, the requested measurement label survives publication, and 104/101 tenths of a degree
become 10.4/10.1 °C. Isolated execution and offline replay reproduce the result. Negative cases
reject invented quotations, another station's code, unknown units and incompatible dimensions.
The station fixture is synthetic test data, not a new live climate-data success.

## Regression and live-validation limits

The prior retained life-expectancy, renewable-electricity and CO2 packages were reprocessed with
current engines in fresh directories. Their 16 + 8 + 4 observations are unchanged, numerical
completion remains complete, and all three packages replay offline. This verifies current
processing of known inputs; it does not retest discovery or obtain a fresh semantic judgment.

Fresh attempts for the five Dutch questions use the previous budgets (600 seconds, 80 model
calls, eight searches, 100 downloads) and Codex / `gpt-6-sol`. Initial attempts encountered
provider failures, including an explicit selected-model-at-capacity error. The temperature
interpretation returned the provider-failure fallback with no executable data scope. Other
attempts failed during catalogue selection before useful source assessment. These failures
must not be scored as evidence that source retrieval improved or regressed.

One initial batch was stopped when review corrections were identified, retained as
`aborted-pre-review`, and restarted. The final symbol-allowlist correction affects rejected
case variants; none of the five requested scopes relies on those conversions. Exact patches,
scopes, snapshots and run outcomes are retained locally. This is **not a completed fresh live
no-regression benchmark**; broader retrieval robustness remains unproven.

## Checks

- Failing regression cases were observed before the corresponding fixes.
- Full suite: 1,482 passed, 24 skipped, two subtests passed; 85.22% coverage.
- Ruff checks/formatting, Pyright (zero errors) and package build passed.
- Independent review identified unit-case conflation and loss of original-question constraints;
  both were corrected, covered by regressions and re-reviewed without remaining blockers.

## Remaining limitations

Source discovery, metadata quality and model availability still vary. These changes do not
implement general ratios, population-rate recomputation, reference-period temperature anomalies,
automatic source splicing or reconciliation of incompatible source definitions. They do not
make all five previously incomplete questions complete. A fresh live benchmark remains needed
when the chosen model is available.
