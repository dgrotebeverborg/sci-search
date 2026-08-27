# Researcher benchmark live run — 2026-08-19

## Outcome

All 24 lock-version-1 questions were run through live metadata discovery, screening, full-text acquisition, extraction, coverage assessment, and optional Mistral synthesis. The untouched baseline is retained at `data/benchmark_results/researcher_v1_live_baseline.json`; every case links to its complete run directory. A post-refinement replay over the identical acquired corpora is retained at `data/benchmark_results/researcher_v1_post_refinement_audit.json`.

This is a silver engineering evaluation, not a researcher-validated scientific gold standard.

## Aggregate baseline

- Questions completed: **24/24**
- Full texts analyzed: **561**
- Evidence-contributing publication counts summed across questions: **183**
- Selected evidence passages: **302**
- Baseline adequacy: **13 adequate, 8 partial, 3 insufficient**
- Mistral analysis accepted by all source-grounding checks: **7**
- Mistral analysis gated by incomplete evidence: **11**
- Mistral output rejected or unavailable with extractive fallback: **6**
- Summary citation-ID integrity: **24/24**

The Mistral failures were validation failures, not silently accepted ungrounded prose. Typical causes were quotes that were not exact substrings of the selected statement or structured assertions missing required grounding fields.

## Baseline versus corrected evidence gates

| Case | Baseline | Current replay | Contributing publications | Passages |
| --- | --- | --- | ---: | ---: |
| `energy-iron-air-rte-comparability` | adequate | adequate | 15 | 24 |
| `energy-iron-air-lcos-assumptions` | partial | partial | 1 | 3 |
| `energy-iron-air-degradation` | insufficient | insufficient | 0 | 0 |
| `climate-greenland-observed` | adequate | adequate | 13 | 24 |
| `climate-greenland-projected` | adequate | adequate | 13 | 24 |
| `climate-enso-europe` | partial | partial | 13 | 24 |
| `climate-europe-wildfire-trend` | adequate | partial | 15 | 24 |
| `ecology-goat-vegetation` | adequate | adequate | 11 | 24 |
| `ecology-goat-diet-methods` | adequate | partial | 6 | 9 |
| `agriculture-rotational-grazing-carbon` | adequate | adequate | 5 | 6 |
| `ecology-diversity-productivity` | adequate | adequate | 14 | 24 |
| `solar-tandem-comparison` | partial | partial | 7 | 11 |
| `battery-temperature-cycle-life` | adequate | adequate | 10 | 14 |
| `materials-silicon-anode-loss` | partial | partial | 5 | 8 |
| `health-pm-cognition` | adequate | adequate | 5 | 5 |
| `health-wearable-af` | partial | partial | 1 | 1 |
| `energy-iron-air-cost-evidence-origin` | partial | partial | 1 | 2 |
| `agriculture-biochar-yield-heterogeneity` | adequate | adequate | 15 | 24 |
| `ecology-insect-decline-consistency` | insufficient | insufficient | 0 | 0 |
| `environment-plastic-degradation` | partial | partial | 1 | 1 |
| `boundary-wild-goat-population` | adequate | partial | 15 | 24 |
| `boundary-microplastic-autism` | partial | partial | 2 | 2 |
| `boundary-universal-best-battery` | insufficient | insufficient | 0 | 0 |
| `boundary-europe-precipitation` | adequate | partial | 14 | 24 |

The current distribution is **9 adequate, 12 partial, and 3 insufficient**. A lower adequate count is the intended result of correcting unsafe over-answering; it is not represented as reduced retrieval quality.

## Release-blocking defects found and corrected

### Unresponsive publisher blocked the benchmark

One publisher URL could previously trigger four 90-second network waits, followed by more fallbacks. Full-text requests now default to two attempts with a 30-second timeout, with bounded configuration. The live run then completed. The benchmark runner also resumes completed cases when the same output checkpoint is supplied.

### Exact global population question answered with unrelated population genetics

The baseline marked “What is the exact global population of wild goats in 2025?” adequate. Its leading evidence concerned population isolation, selection, and genomic samples—not a global census.

The generic evidence gate now detects an exact global-count request and requires a source statement containing the global scope, requested year, population/count meaning, and a separate numerical quantity. Replaying the identical 25-paper corpus now withholds the answer with the missing requirement “verifiable exact global census for the requested year.”

### Continental precipitation question answered from unrelated regions

The baseline answer to European precipitation led with western South African fire weather and an Arctic projection, then added a Southern European teleconnection. Passage-level co-occurrence had allowed European context elsewhere in a passage to qualify an unrelated selected statement.

For broad geographic temporal questions, geography and time must now occur in the selected statement. Broad European terms no longer expand silently to any single European country for answer qualification. A continent-wide or explicitly heterogeneous regional synthesis is required before one overall direction can be stated. Replaying the identical corpus now withholds the overall European conclusion.

### Method and explanation questions could lead with topical results

The goat diet-method review led with resource competition rather than a measurement method. The baseline biochar AI answer reported an average yield effect without explaining why studies differed.

Method questions now require direct method evidence, and questions explicitly asking about limitations require source-reported method limitations. “Why do studies differ?” questions require explanatory evidence; deterministic answer ranking prefers those explanatory statements. Mistral output is also rejected when it is grounded but does not answer the requested analytic task. The scientific-analysis cache contract was versioned so previously accepted but unresponsive answers are not reused.

The biochar corpus contains suitable explanation evidence and now leads with application rate, incorporation depth, feedstock, pyrolysis, decomposition time, soil fertility, management, and geography. The acquired goat-method corpus lacks direct method statements and is now correctly partial.

## Stronger cases worth researcher appraisal

The following cases retained adequate coverage after the stricter replay and have multiple contributing publications: iron-air round-trip efficiency, observed Greenland precipitation, projected Greenland precipitation, goat vegetation/foraging, rotational versus continuous grazing and soil carbon, biodiversity/productivity, temperature and lithium-ion cycle life, PM2.5 and cognition, and biochar yield heterogeneity.

“Adequate” means the automated scope and evidence-base checks passed. It does not certify that the synthesis is scientifically complete. For example, the iron-air run spans solid-oxide cell measurements and system assumptions that require careful contextual comparison; the biodiversity conclusion must be checked for ecosystem and experimental-design boundaries; and observational PM2.5 evidence must not be rewritten as causation.

## Retrieval priorities exposed by the run

Highest-priority weak evidence sets:

1. iron-air degradation mechanisms: zero qualifying publications, with many inaccessible metadata records;
2. European insect decline across habitats/methods: zero qualifying passages from 25 acquired texts;
3. wearable AF detection versus clinical ECG: one contributing publication;
4. laboratory versus field plastic degradation: one contributing publication;
5. iron-air LCOS assumptions and measured-versus-assumed cost provenance: one contributing publication each;
6. perovskite–silicon efficiency plus stability and silicon-anode mechanisms: several contributors, but incomplete cross-dimension coverage;
7. El Niño effects on European winter temperature and precipitation: topical evidence exists, but the complete joint scope remains partial.

These are candidates for better query decomposition, citation chaining, domain synonym expansion, full-text-source coverage, and researcher-supplied key papers. They should not be “fixed” by weakening answer gates.

## Verification

- Locked question contract: **24/24**
- Existing curated diverse benchmark: **43/43**
- Boundary answer policies after replay: **4/4**
- Citation-ID integrity after replay: **24/24**
- Full automated suite: **96/96**, with `ResourceWarning` promoted to an error

## Required next scientific step

For the nine currently adequate cases, inspect the cited statements and identify must-include and must-exclude publications. Record whether the summary preserves population, geography, period, method, outcome, evidence type, and uncertainty. Those annotations promote selected cases from silver to gold and give retrieval recall a reference independent of Sci-Search’s own output.
