# Requested calculations and consistent definitions — 16 October 2026

## Problem and change

The energy question requested annual percentages and percentage-point changes, but earlier
interpretations returned an empty calculation list. The instruction incorrectly implied that
percentage-point changes needed no explicit operation. The numerical completion label therefore
could not detect that missing output. A second live attempt also retained final-energy and
gross-final-energy percentages under the same broad requested measurement, leaving conflicts open.

The interpretation now inventories requested numerical transformations, linking each to executable
calculation IDs or an explicit unresolved reason. Validation rejects unassigned requests and
unaccounted plans. Fixed Python supports calendar-year differences and differences from a named
base year, including percentage-point changes with a documented percentage scale/unit. Every
result retains both input observations. Missing values, unknown scales and comparability flags
remain blockers. Model interpretation can still misunderstand a request; the inventory makes its
decisions inspectable rather than guaranteeing perfect natural-language understanding.

Definition choice is opt-in per requested measurement. When the question explicitly delegates
that choice, a single reviewed, executed source covering the complete panel may be selected.
The first qualifying source supplies all countries/years for that measurement. Its cited definition
and the alternative source indexes are recorded and displayed. Alternatives remain retained;
they do not enter the selected comparison or its calculations. Specified definitions and legacy
scopes retain strict conflict handling. No sources are spliced to manufacture a complete panel.

## Controlled comparison

Inputs are the exact two retained analyses from the preceding energy evaluation's second live
attempt: 57 OWID final-energy observations and 60 Eurostat gross-final-energy observations.
The controlled scope explicitly asks for both annual changes and changes from 2005, and permits
a documented definition choice. This is an explicit test scope, not a claim that the model always
interprets unspecified change timing this way.

The repaired engine chooses the complete Eurostat panel and produces:

| Output | Independently matched values |
|---|---:|
| Annual percentage-point changes, 2006–2024 | 57 |
| Changes from 2005, 2005–2024 | 60 |

All 117 differences match subtraction from the separately retained Eurostat JSON reference.
Raw analyses are unchanged, the OWID alternative stays separate, and the raw and derived package
replays offline. Input and calculation coverage are complete for this explicit controlled scope.
No new semantic judgment was obtained for these retained sources.

Eight earlier question packages were reprocessed under their existing scopes: 519 values and
their completion classifications remain unchanged, with successful offline replay. Those scopes
do not retroactively acquire a new interpretation or calculation inventory.

## Tests and live evaluation

Ten focused failures were observed before implementation. New tests cover arithmetic, both input
references, zero/negative baselines, missing calendar years, percentage scale/unit requirements,
comparability breaks, request-to-plan accounting, strict defaults, unreviewed sources and the ban
on assembling a definition choice across different country sources. An independent reviewer found
no blockers; common meaning across a source's series remains a source-grounded model assessment.
Full suite: 1,506 passed, 24 skipped, two subtests passed; 85.24% coverage. Ruff, formatting,
Pyright (zero errors) and package build passed.

Fresh searches use the same original Dutch questions and limits: 600 seconds, 80 research model
calls, eight searches and 100 downloads. Energy is repeated twice; rail, potatoes, road fatalities
and station temperatures are tested once each. Results, source files, request counts, timings and
independent checks are retained under `data/validation_runs/answer-completeness-20261016/`; final
outcomes are summarized in the PR validation notes. Monetary cost is not measured by the harness.

The first fresh energy attempt completed its numerical outputs in 110.0 seconds including
interpretation (five research model calls, one search, 12 downloads). Its 60 annual percentages
and 57 annual percentage-point changes matched the independent Eurostat reference; offline
replay passed. This live interpretation explicitly chose year-on-year changes, recorded that
request, and permitted a documented definition choice. One successful attempt is not evidence
of uniform retrieval performance; the repeated run and other questions remain separate checks.

The literature workflow remains separate. These changes do not add general ratios, population-rate
recomputation, multi-year temperature anomalies, definition reconciliation, or arbitrary formulas.
