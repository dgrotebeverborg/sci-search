# Energy retrieval regression — 16 October 2026

## What actually regressed

The preceding source-quality change (`8321e9c`) introduced a reproducible processing
regression. A model response identified countries using `ES`, `IT`, and `PT`, while
the statistical reader had already constructed series such as `geo=ES (Spain)`.
The new generic identity validator rejected those raw codes because they were not
the selected composite series names. Sixty available observations were rejected.
Provider failures also occurred in the live run, but do not explain this code defect.

The alternative Python extractor read the compressed TSV correctly, but the numeric
reference validator tried to decode the gzip bytes as plain text. This second failure
already existed before the preceding change.

## Repairs

Statistical tables now use the identities produced from their selected dimensions and
retained publisher code labels. They neither request nor apply additional model-generated
identity overrides. Ordinary CSV/station mappings still require their exact citations.
Measurement-definition review remains mandatory.

Numeric reference checking now uses the existing bounded gzip decoder for text, CSV,
and JSON sources. Wrong values and invalid locators still fail. Corrupt DEFLATE streams
are normalized to validation errors; expansion retains the existing 10 MB limit.
Original compressed bytes remain retained and hashed, and offline packages include
the same verification code.

## Same-source comparison

All three revisions received exactly the same retained Eurostat `nrg_ind_ren` bytes,
country/year selection, and recorded mapping response. Source SHA-256:
`7aa112c1de17a9b3c43edace39db6e3bcd045dad1ab70156ca15c2bf18dc7769`.
The experiment fixes model decisions and uses a synthetic positive meaning reviewer;
it tests processing, not fresh discovery or scientific certification.

| Processing version | Published input values | Resolved extraction references |
|---|---:|---:|
| Earlier `c0a5055` | 60 | failed |
| Regressed `8321e9c` | 0 | failed |
| Repaired | 60 | 60 |

All 60 repaired values match the separately retained Eurostat JSON reference, and the
package replays offline. This restores previous processing coverage; it does not exceed
the earlier 60-value result or establish a complete answer to the original question.

Eight earlier packages were also reprocessed with both the regressed and repaired engines:

| Retained case | Unchanged input values |
|---|---:|
| Life expectancy | 16 |
| Renewable electricity | 8 |
| CO2 | 4 |
| Rail | 144 |
| Potatoes | 167 |
| Renewable energy | 60 |
| Station temperature | 45 |
| Road fatalities | 75 |

All 519 values, series and completion classifications remain unchanged; all eight
packages replay offline on both revisions. The road package is from the earlier
successful partial run; other five-question packages are from that evaluation's
second round. Retained correctness does not certify fresh model behavior.

## Verification and measurement policy

Six added cases failed before the fixes and passed afterward. Independent review found
the corrupt-DEFLATE exception gap; its additional regression also failed before correction.
Tests exercise ordinary station identity safeguards, statistical processing and offline
export, gzip text/CSV/JSON references, wrong values, malformed streams and expansion limits.
The final full suite passed: 1,489 tests, 24 skipped, two subtests passed; 85.23% coverage.
Ruff, formatting, Pyright (zero errors), and package build passed. Independent review
confirmed the exception fix and reported no remaining blockers.

Two fresh energy searches use the original Dutch question and the existing 600-second,
80-model-call, eight-search, 100-download limits. Their outcomes, elapsed times and request
counts are retained separately under `data/validation_runs/energy-regression-20261016/`.
Actual monetary cost is not available in this harness; request counts are not a cost estimate.
These two runs cannot establish no regression across all questions.

The first fresh attempt retrieved all 60 annual inputs from `sdg_07_40` in 263.7 seconds
(including interpretation): eight research model calls, one search and 16 downloads.
All 60 matched the independent reference and the package replayed offline. The earlier
failed live attempt took 750.8 seconds and returned zero values; this observational
comparison also includes changed model/source decisions, so the same-source experiment
above provides the causal evidence for the processing fix. The second attempt's final
outcome is retained separately with the validation artifacts and PR validation notes.

Evaluate full answers separately from input coverage: the energy interpretation has
previously omitted percentage-point calculations from its executable calculation list.
Even 60 correct annual inputs must not be called a complete answer while those requested
changes remain missing. This repair does not implement that separate calculation feature.

Future comparisons should fix source bytes and decisions first, then measure repeated live
attempts separately. Report source availability, numeric correctness, missing calculations,
definition evidence, elapsed time and request counts; do not use a green test suite as a
substitute for answer quality.
