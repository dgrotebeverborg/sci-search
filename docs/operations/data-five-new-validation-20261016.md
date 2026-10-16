# Five new data questions — 16 October 2026

## Scope and method

This evaluates the data workflow; literature synthesis is a separate part of the application and
was not evaluated here. Baseline: `f805f7e`. Each round interprets the original question afresh
with Codex / `gpt-6-sol`, then runs discovery, source review, extraction and calculation.
Per question: 600 seconds, 80 model calls, eight searches and 100 downloads. An in-flight call
can finish after the time limit. Shared catalogues reduce repeated catalogue downloads.

Fresh interpretation and discovery are stochastic. This is a diagnostic exercise, not a controlled
causal benchmark or a demonstration that arbitrary research questions work. Changes in observation
counts between rounds cannot be attributed solely to the code change. Counts below are retained
observations and can include overlapping sources; they are not necessarily unique requested cells.

## Questions

- **rail:** Hoe ontwikkelde het jaarlijkse reizigersvervoer per trein zich in Nederland, België en Duitsland tussen 2000 en 2024? Geef reizigerskilometers en een index met 2000 = 100. Benoem definitiewijzigingen.
- **potatoes:** Hoe veranderde de jaarlijkse aardappelopbrengst per hectare in Nederland, Frankrijk en Polen tussen 1990 en 2024? Geef ton per hectare en controleer waar mogelijk of productie gedeeld door geoogst areaal hetzelfde resultaat oplevert.
- **renewables:** Hoe ontwikkelde het aandeel hernieuwbare energie in het totale energieverbruik zich in Spanje, Italië en Portugal tussen 2005 en 2024? Geef jaarlijkse percentages en veranderingen in procentpunten. Maak duidelijk welke definitie van energieverbruik wordt gebruikt.
- **road:** Hoe veranderde het aantal verkeersdoden per miljoen inwoners in Zweden, Nederland en Roemenië tussen 2000 en 2024? Geef ook de absolute aantallen en controleer of bevolkingscijfers en definities bij de berekening passen.
- **temperature:** Hoe ontwikkelde de gemiddelde jaarlijkse temperatuur in De Bilt, Ukkel en Potsdam zich tussen 1980 en 2024? Geef per meetstation de afwijking ten opzichte van het eigen gemiddelde over 1991–2020. Benoem ontbrekende jaren en veranderingen aan de meetstations.

## Implemented correction

Unsupported numerical requests can disappear when interpretation lists only executable operations.
The scope now retains a bounded `unresolved_calculations` list. The numerical result stays partial
when this list is nonempty, even if all raw inputs and supported calculations are complete.
Successful supported calculations remain visible. The existing dashboard displays the reason.

The fresh interpretations now explicitly retain the production/area cross-check, the road-deaths
per-population cross-check, and subtraction of each station's 1991–2020 reference mean.
This change does not implement these operations. It also does not guarantee that the model records
every requested operation: both energy interpretations describe year-on-year changes in prose,
while the engine only returns endpoint changes and no unresolved entry was recorded. The original
question asks for changes in percentage points without specifying their interval; the interpreted
scope therefore promises more than the available calculation. Keep this limitation visible.

## Results

| Question | Before: retained observations | After: retained observations | Outcome after correction |
|---|---:|---:|---|
| Rail | 75 | 144 | Partial input coverage; all three indices blocked by overlapping/ambiguous sources. |
| Potatoes | 105 | 167 | Production plus additional Dutch inputs; missing French/Polish yield/area, unsupported yield unit conversion and ratio cross-check. |
| Renewable energy | 60 | 60 | All annual percentages and endpoint percentage-point changes; no annual difference series. |
| Road fatalities | 75 | 0 | Second run exhausts time budget without a validated series; raw retrieval regressed in this sample. |
| Station temperature | 80 | 45 | Only De Bilt inputs retained; Uccle/Potsdam and requested anomalies absent. |

All ten offline replays exit successfully. No requested derived output is produced in either round
for rail, potatoes, road fatalities or station anomalies. The energy numerical contract is complete,
with the year-on-year interpretation caveat above. This is one successful numerical question and
four incomplete questions, not five passing end-to-end cases.

The 80 baseline temperature observations are two overlapping sources for De Bilt (35 CBS values
and 45 KNMI values), not two stations. In the second round the KNMI parser retains station code
260 and a station-specific measurement label; these do not match the requested station identity
and generic measurement label, so numerical completion is blocked despite 45 retained values.
The values themselves match the independent KNMI reference after applying their explicit
0.1-degree unit. DWD's independently accessible reference does not mean the workflow retrieved it.

The second crop run retains Dutch yield in the source's `1 000 kg` unit and area in hectares;
the bounded conversion engine does not establish a tonnes-per-hectare conversion from that unit.
The rail run retains more overlapping series, which still cannot be automatically spliced or chosen.

## Regression findings and second correction

Fresh interpretations of the previous life-expectancy, renewable-electricity and CO2 questions
use a smaller budget: 240 seconds, 16 model calls, two searches and 35 downloads. These check
unrelated questions rather than only the new examples.

The first life-expectancy run exposed an existing alias bug: requested `women`/`men` did not match
retained `female`/`male` identities. Coverage now normalizes equivalent values only within the sex
dimension; unrelated categories and geographic names are preserved. Tests also reject a combined
female-and-male source as evidence for either separate series. Re-evaluating the exact retained
run now recognizes all four country/sex cells and their four years, while preserving differences
between its two Eurostat source tables as explicit conflicts. No raw data are changed.

The demographic life-expectancy table matches all 16 earlier reference values. The additional
tps00208 table has different values in 11 cells and is not graded as though it were the same
reference series. The renewable-electricity run matches all eight references and completes its
numerical contract. CO2 matches all four references. After the alias correction, a new full
interpretation/discovery run for life expectancy completes all 16 requested values and matches
the reference. All four regression runs replay offline, including the earlier blocked life run.
The final successful set therefore matches 28/28 reference values. Renewable-electricity and CO2
were run before the sex-only correction and have no sex breakdown; the fresh life run uses it.
This does not establish a general no-regression guarantee for arbitrary live discovery.

The sex-alias correction was added after the five-question rerun; none of those five scopes has
a sex breakdown. Its regression test failed in all three alias variants before the change and
passes afterward. Separate review found no blocker in either correction.

## Independent checks

Fresh primary-source downloads are parsed independently of the application connectors. Eurostat
comparisons require matching year and selected dimensions. The separately downloaded OWID CSVs
match all 105 retained potato-production values and all 68 OWID rail values in each round.
Eurostat matches all 60 renewable-energy values in each round and all 75 baseline road counts.
The KNMI reference independently matches 45 De Bilt values in each round, respecting their units.
The other seven baseline and 76 second-round rail values, 62 additional second-round crop
values and 35 baseline CBS temperature values have not been independently checked against a
separate extraction. Offline replay checks execution and retained evidence, not scientific validity.

Reference sources and interpretation constraints:

- [Eurostat rail passenger transport](https://ec.europa.eu/eurostat/databrowser/product/view/rail_pa_total?lang=en):
  the reference selection provides 43 values in the requested period and does not cover the whole
  2000–2024 panel. It is not a complete benchmark for older rail observations.
- [Eurostat crop metadata](https://ec.europa.eu/eurostat/cache/metadata/en/apro_cp_esms.htm):
  distinguish thousand hectares, thousand tonnes and tonnes per hectare, as well as moisture bases.
  FAOSTAT/OWID observations are not treated as identical to Eurostat crop observations.
- [Eurostat renewable energy shares](https://ec.europa.eu/eurostat/databrowser/view/nrg_ind_ren/default/table):
  the benchmark uses REN / PC, gross final energy consumption, rather than electricity alone.
- [Eurostat road-fatality metadata](https://ec.europa.eu/eurostat/cache/metadata/en/sdg_11_40_esmsip2.htm):
  the RT series is per 100,000 inhabitants; per million requires a factor of ten. Check the
  30-day fatality definition and population basis before recomputing rates.
- [DWD annual historical observations](https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/annual/kl/historical/):
  station 03987 (Potsdam), JA_TT, provides 45 annual observations for 1980–2024. The independent
  equally weighted mean of its 1991–2020 annual values is 9.790666666666663 °C. A differently
  defined published normal must not silently replace this requested reference mean.

## Remaining priorities

1. Separate whether a published input matches its definition from whether a downstream cross-check
   has been executed. The baseline rejected a usable potato-yield candidate partly because the
   production/area comparison was absent. Rejecting the input for an unavailable derived operation
   loses useful data.
2. Improve metadata acquisition and code/unit selection, with bounded retries that change strategy.
   The rail, crop and road runs spend much of their budgets revisiting sources and definitions.
3. Extend the bounded calculation contract with dimensional ratios, population-scaled rates,
   differences and reference-period anomalies. Define units, time alignment, denominator rules,
   reference-period completeness and source compatibility before enabling them.
4. Check interpretation against the original requested outputs, including promises added to prose.
   `unresolved_calculations` is a useful declaration, not an independent completeness check.
5. Preserve source-backed station identities and the requested measurement identity through
   extraction; a valid station code should not leave the requested station unmatched.
6. Keep regression examples across unrelated topics and compare both numerical correctness and
   successful retrieval; replay alone cannot demonstrate that unrelated questions still work.

## Verification and retained evidence

The focused regression failed before the correction and passed afterward. The full suite reports
1,455 passed, 24 skipped and two subtests passed, with 85.20% coverage. Ruff, formatting, Pyright
(zero errors) and package build passed. A separate code review found no blocking issue.

Local raw evidence: `data/validation_runs/five-new-20261016/` (untracked): manifest, original
questions, before/after scopes, progress logs, source snapshots, executed extraction scripts,
sealed results, offline replay, direct reference downloads and scorecards. Large downloaded
artifacts and model logs are not committed. They retain retrieval timestamps and source hashes.
