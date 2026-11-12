# Requested calculation validation — 15 October 2026

## Change and scope

Data research now records a bounded calculation plan, checks required inputs, executes fixed
arithmetic in the existing isolated Python runner, and reports raw-data and calculation
completeness separately. Literature synthesis remains a separate stream.

Supported operations are nominal base-year indices, real indices, deflation, compatible unit
conversion and shares. Missing base years, non-positive denominators, incompatible units,
ambiguous source choices and unresolved input definitions remain visible gaps. Sources are
never silently spliced. Older scopes without an explicit calculation plan remain unassessed.

This implements the calculation follow-up from the
[five-question evaluation](data-five-question-validation-20261015.md). It does not claim that
arbitrary questions, definitions or access methods are solved.

## Validation method

Three distinct checks were used:

1. Hand-calculated fixtures exercise arithmetic, missing inputs, incompatible units, country and
   breakdown joins, duplicate sources, provenance, cancellation/budget boundaries and offline replay.
2. Retained original sources from the previous evaluation isolate calculation behavior from
   stochastic discovery. New calculation packages are copies; prior evidence is preserved.
3. Fresh interpretation and live discovery rerun housing and hydropower, alongside three successful
   reference questions. All use Codex/gpt-6-sol. Main live budgets are 600 seconds, 80 model calls,
   8 searches and 100 downloads; reference budgets are 240/16/2/35. An in-flight call can finish
   after the time bound. Retained-source reviews are separately run validation probes.

Every published derived value is independently recomputed using Decimal arithmetic in the
validation harness. Offline replay verifies retained raw and derived executions. This tests
arithmetic and integrity, not independent scientific certification of model judgments.

## Retained-source results

| Question | Retained raw values | Derived values | Remaining limitation |
| --- | ---: | ---: | --- |
| Netherlands housing, 2000–2024 | 64 | 25 nominal average-price indices | Income baseline 2000 is absent; real-price review does not approve the interpretation and cross-method comparison. |
| Norway/Sweden hydro and total generation, 1990–2024 | 140 | 140 TWh values across both inputs | Ember hydro and Eurostat total definitions do not establish matching production boundaries for shares. |

All 165 derived values match separate Decimal calculations. Both packages replay offline.
The housing price series is an average transaction price, not a constant-quality price index.
The CPI evidence also identifies a method change. Both qualifications must remain visible.

The first retained probe exposed an oversized unrelated table catalogue in definition evidence.
Large documents now contribute original cited passages with surrounding context, explicitly named
as excerpts. Whitespace-normalized citations preserve original character spans, and repeated
matches preserve each context within a fixed total bound.

## Live results

| Fresh question | Raw values | Derived values | Result |
| --- | ---: | ---: | --- |
| Housing | 82 across five retained series | 25 nominal average-price indices | Partial: income inputs are ambiguous; the review budget expires before real-price compatibility can be approved. |
| Hydropower, after unit-alias correction | 140 | 70 TWh production values | Partial: production coverage is complete, but shares lack compatible definition evidence. |

Housing takes 656 seconds including interpretation, with 621 seconds inside the 600-second
workflow budget because an in-flight model call finishes after the bound. It uses 53 model calls,
three searches and 74 downloads. The deterministic nominal index still executes after discovery
stops, while an unreviewed inflation adjustment stays blocked. Finding older household-income
observations does not justify merging multiple series with different definitions or coverage.
The 82 raw values therefore do not mean 82 comparable observations satisfy the original question.

A separately labelled reprocessing of the housing sources with an additional review call also
withholds the real-price index: the model objects to the transaction-price/index interpretation
and CPI method changes. This is a model judgment, not proof that CPI-adjusted averages are
mathematically impossible. The arithmetic fixtures demonstrate that supported real indices and
deflation work; the live review remains conservative.

The first fresh hydropower run exposed a unit alias gap: the source uses “terawatt-hours”.
Explicit SI energy-unit names now recognize singular/plural, hyphenated and space-separated
spellings. A retained reprocessing check and a separate new discovery run both publish the
70 hydropower observations in TWh. Shares remain blocked because the review cannot establish
compatible production boundaries, including pumped-storage treatment, across the selected sources.
The final hydro run took 130 seconds including interpretation (100 seconds inside the data workflow).

Initial interpretation probes also classified monetary amounts as interval-scale measurements and
mismatched measurement names with parenthesized units. Scope guidance now distinguishes ratio
quantities from interval scales and requires exact references. Validation errors report the
offending name and available measurements. Fresh housing and hydro interpretations preserve their
requested calculations and appropriate scale types. This is limited probe evidence, not a general
interpretation accuracy estimate.

## Regression and implementation checks

| Reference question | Independently matched values | Offline replay |
| --- | ---: | --- |
| Life expectancy, Netherlands/Germany, female/male, 2020–2023 | 16/16 | Passed |
| Renewable electricity share, Netherlands/Germany, 2020–2023 | 8/8 | Passed |
| Mauna Loa annual CO2, 2020–2023 | 4/4 | Passed |

All three reference questions retain complete numerical coverage. These runs explicitly request
no additional calculation plan; the existing descriptive percentage-point changes remain available.

Final local suite: **1,443 passed, 24 skipped, two subtests passed; 85.20% coverage**.
The 49 focused arithmetic, provenance and browser checks also passed. Ruff, formatting,
Pyright (zero errors, 235 warnings), package build and secret scanning passed.

Independent code review identified three integrity gaps before delivery: altered analysis JSON
could bypass the sealed executed result, mutable cached approvals could bypass compatibility
checks, and unsealed documentation could enter a review. Regression tests reproduced each issue
before correction. The corrected implementation compares executed input results, ignores cached
approvals as authorization, and only loads verified manifest evidence. Review found no remaining
blocking issues. A further regression confirms that exhausting the second review budget preserves
the first approved calculation.

## Evidence and limits

Local evidence is under `data/validation_runs/calculations-20261015/`: interpretation probes,
`retained/`, `retained-fixed/`, `live/`, `live-reprocessed/`, `live-final/`, `regression/`,
runner scripts, scorecard, exact implementation patch and verification logs. Each run retains
source bytes, reviews, executed code and offline replay. Large raw artifacts are not committed.

Interpretation and source selection remain stochastic. Missing compatible definitions need
targeted acquisition; a numerical layer cannot make unrelated measures comparable. Automatic
acquisition of out-of-period baselines, open-ended calculation periods, arbitrary expressions,
monthly outputs and completeness of methodological explanations remain outside this extension.
