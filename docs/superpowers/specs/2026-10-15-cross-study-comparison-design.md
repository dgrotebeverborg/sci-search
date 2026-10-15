# Cross-study comparison — design

Date: 2026-10-15. Status: draft for review. Related project: `sci-graph`
(branch `recovery/prototype-2026-07-16`).

## Goal

The researcher sees how the included studies relate to each other on the question they asked.
That means more than one summary per paper: which studies examine the same relationship, how
many support it, find no effect, or contradict it, how large the reported effects are, and which
differences in context explain the disagreements.

The target sentence on the results screen:

> 5 studies examine glacier melt → downstream river flow. 3 report a decrease after peak water,
> 1 reports no change, 1 reports an increase. The increase comes from a study ending in 2050;
> the decreases come from studies running to 2100.

Every number in that sentence is counted by rules. Every finding behind it carries a verbatim
quote from the full text.

## The problem today

Measured over the ±50 runs in the local workspace:

- Studies are screened one by one on their full text (strong), then summarised.
- The rule-based synthesis (`synthesis.py`) counts "convergence" only when two papers contain
  the identical sentence; that almost never happens. Numbers are never compared
  (`no_numerical_comparison_attempted`).
- The AI analysis (`mistral_analysis.py`) is the only cross-study step. In one call, with at most
  2 agreements and 3 contradiction groups, it produced 1 agreement, 0 contradiction groups and
  3 method differences across all runs. In every run this week it was `unavailable`.
- The study matrix (`study_matrix.py`) records why a study was included, not what it found.
- Places and subjects are matched literally, so "Southern European" does not meet "Southern
  Europe".

## What we take from sci-graph

| Building block in sci-graph | Use here |
|---|---|
| `PublicationScientificProfile`: claims with `scope`, `claim_type`, `strength`, `statement_role`, `source_fragment`, `source_section` | The finding record per study (below), extended with direction and effect size |
| `statement_quality.py`: rejects background, aim, method-section and scope-less claims; assigns roles `main_finding`, `supporting_finding`, `methodological_finding`, `background_claim` | The same deterministic filter before any comparison |
| `local_vocabulary.py`, `openalex_topic_index.py`: normalise labels to shared concepts | Normalising variables, places and populations so findings can be grouped |
| `discovery_benchmark.py` relation set: `SUPPORTS`, `CONTRADICTS`, `TESTS_CLAIM`, `EXTENDS`, `USES_DIFFERENT_CONTEXT`, `SAME_TOPIC_ONLY` | The pairwise relation vocabulary |

Lesson from sci-graph's benchmark: judging relations on title and abstract gave mostly
`SAME_TOPIC_ONLY` (18 of 24) and no `CONTRADICTS`. Here, relations are judged only between
findings that already share a normalised relationship, and always on full-text passages.

## Scope

In scope:

- Included studies only (screening decision `included`; `background` studies are context and
  are listed, not counted).
- Questions with intent `relationship`, `comparison`, `temporal_trend` and `evidence_search`.
- One comparison per requested relationship or outcome.

Not in scope:

- Meta-analysis: no pooled effect sizes, no weighting, no confidence intervals across studies.
  Numbers are placed side by side with their units and contexts, never combined.
- Risk-of-bias scoring of individual studies.
- Changing which studies are included. Comparison reads the screening result; it never
  overrides it.

## Architecture

A new package `sci_search/cross_study/` with four rule-based steps and two model steps. Each step reads
and writes JSON-compatible dicts, so the package has no dependency on run state, storage or the
web layer. That boundary is what lets sci-graph reuse it later.

```
included study cards + full texts
  1. extract   (model, quote-validated)  -> findings per study
  2. filter    (rules)                   -> findings that may be compared
  3. normalise (rules + vocabulary)      -> findings with concept ids
  4. group     (rules)                   -> comparison groups (same relationship)
  5. relate    (model, quote-validated)  -> direction agreement and explained differences
  6. tally     (rules)                   -> counts, ranges, sentence for the screen
```

The existing `comparison.py` (pairwise measurement comparability for the iron-air corpus) is
kept and reused in step 6 for numeric comparability checks.

### 1. Extract — `cross_study/extract.py`

One model call per included study, with the question, the confirmed research plan and that
study's selected passages (already in the study card). Output, per finding:

```json
{
  "finding_id": "finding:<publication>:<n>",
  "publication_id": "publication:…",
  "statement": "Glacier melt contribution to Indus flow peaks around 2050 and declines afterwards.",
  "quote": "exact text from the passage",
  "passage_id": "study-passage:…",
  "section": "results",
  "role": "main_finding",
  "relationship": {"driver": "glacier melt", "outcome": "river flow"},
  "direction": "decrease",
  "effect": {"value": -12.5, "unit": "%", "comparison": "2071–2100 vs 1971–2000", "text": "−12.5%"},
  "scope": {"place": "Indus basin", "population": null, "period": "1971–2100",
            "scenario": "SSP5-8.5", "scale": "basin"},
  "design": "model_projection",
  "uncertainty": "range across 7 GCMs: −20% to −4%"
}
```

- `direction` is one of `increase`, `decrease`, `no_effect`, `mixed`, `positive_association`,
  `negative_association`, `not_stated`.
- `design` uses the existing evidence natures (`laboratory experiment`, `field or observational
  study`, `simulation or model`, `review`), with `model_projection` added for scenario
  projections, which are never counted as observations (same rule as the data meaning review).
- `effect` is optional; when present, `text` must occur in the quote.
- At most 6 findings per study. Prompt rules follow sci-graph's: findings come from results,
  discussion or conclusion; aims, background and method descriptions are not findings.

Validation (deterministic, fail closed per finding): the quote must occur in the passage (the
existing whitespace-insensitive check); `effect.text` must occur in the quote; the publication
must be included; unknown enum values drop the finding. A study whose call fails keeps its
inclusion and is reported as "findings could not be extracted".

### 2. Filter — `cross_study/quality.py`

A port of sci-graph's `assess_claim_statement` and `claim_statement_role`: findings from
introduction or methods, aim statements, background cues ("remains unclear", "little is known")
and findings without any scope are dropped with their reason. Only `main_finding` and
`supporting_finding` are compared; `methodological_finding` is listed separately.

### 3. Normalise — `cross_study/concepts.py`

Each `relationship.driver`, `relationship.outcome`, `scope.place` and `scope.population` gets a
concept id:

1. The confirmed research plan's terms are the anchors: a label equal to, or containing, a plan
   term (after case folding, plural and hyphen normalisation) takes that term's id.
2. A small place table resolves names, adjectives and regions to one id: "Southern European" →
   `place:southern-europe`; "Indus", "Indus basin", "upper Indus" → `place:indus` with a scale
   note. ISO countries come from the existing country table.
3. Otherwise, a model-proposed mapping to a plan term is accepted only when it is recorded with
   its reason; labels that match nothing stay their own concept and are shown as "other".

The same module is meant to replace the literal place and subject matching in screening later;
that change is a separate design.

### 4. Group — `cross_study/groups.py`

A comparison group is all compared findings with the same `(driver concept, outcome concept)`
for relationship questions, or the same `outcome concept` for trend and evidence questions.
Groups with findings from only one publication are listed as "single-study findings", not
compared. Findings from the same publication count once per group (the most specific one is
the representative; the others stay visible).

### 5. Relate — `cross_study/relate.py`

For each group with two or more publications, one model call receives the group's findings with
their quotes and scopes and returns:

- per pair of publications: `SUPPORTS`, `CONTRADICTS`, `USES_DIFFERENT_CONTEXT` or
  `SAME_TOPIC_ONLY` (sci-graph's vocabulary; `TESTS_CLAIM` and `EXTENDS` collapse into these
  because both findings are already about the same relationship);
- for each `CONTRADICTS` or `USES_DIFFERENT_CONTEXT`: the cause, using the existing
  `ContradictionCause` values (`different_conditions`, `different_population`,
  `different_method`, `different_outcome_measure`, `unexplained`), with one quote from each side
  that shows the difference.

Rules decide what the model may not:

- The direction of each finding comes from step 1, not from this call. A `SUPPORTS` between an
  `increase` and a `decrease` finding is rejected and recorded.
- Severity is computed by the existing `domain/contradictions.assess_severity`.
- A projection and an observation are always `USES_DIFFERENT_CONTEXT`.

### 6. Tally — `cross_study/tally.py`

Per group, with no model call:

- counts by direction, by design (observations versus projections separately) and by place;
- numeric effects side by side, grouped by unit and comparison; values with different units or
  baselines are not placed in the same column, and `comparison.compare_pair`-style checks flag
  differing contexts;
- a consistency label: `consistent` (all compared findings point the same way), `mostly
  consistent` (at least ¾), `mixed`, `contradictory` (an unexplained contradiction with severity
  high), or `single study`;
- the screen sentence, built from a template from these counts.

## Output and presentation

The investigation gets a `cross_study_comparison` block:

```json
{
  "method": "cross_study_comparison_v1",
  "groups": [{"id": "…", "driver": "…", "outcome": "…", "publications": 5,
              "directions": {"decrease": 3, "no_effect": 1, "increase": 1},
              "consistency": "mixed", "sentence": "…", "effects": […],
              "relations": […], "findings": […]}],
  "single_study_findings": […],
  "dropped_findings": [{"finding_id": "…", "reason": "background_section_claim"}],
  "extraction_failures": […]
}
```

Results screen (`dashboard.js`, `result_summary.py`):

- **Answer tab:** under the literature part, one line per comparison group with its consistency
  label and sentence. The certainty rule in `result_summary.py` gains one input: a `mixed` or
  `contradictory` main group caps certainty at "Moderate evidence".
- **Details tab:** a "How the studies compare" section per group: a table with one row per study
  (place, period, design, direction, effect, quote on hover), the explained differences, and the
  dropped findings with their reasons.
- The existing AI analysis keeps writing the prose answer. It receives the tallies as input and
  may not state a count that differs from them.

## Where it runs

In `research_runs.py`, after full-text screening and the study matrix, before the AI analysis.
It runs when at least two studies are included. Results are cached by the hash of the inputs, in
the same way as the AI analysis, so a rebuild without new studies costs no model calls. Saved
runs without the block show the screen as today.

## Cost and limits

- Extraction: one call per included study (at most 25 per run with the current target).
- Relations: one call per group with two or more publications (at most 6 groups).
- A run with 25 included studies costs about 31 extra calls. Calls run with the run's selected
  provider and model.

## Error handling

- A failed extraction or relation call never fails the run: the block records the failure and the
  screen says which studies or groups could not be compared.
- An invalid quote drops only that finding.
- A rejected relation (contradicting the extracted directions) is recorded with the rule that
  rejected it.

## Testing

- `tests/test_cross_study_extract.py`: quote and effect validation; unknown enums dropped; failed
  call keeps the study.
- `tests/test_cross_study_quality.py`: sci-graph's rejection rules, ported with their cases.
- `tests/test_cross_study_concepts.py`: "Southern European" and "Southern Europe" share a concept;
  "Indus basin" and "upper Indus" share a place with different scale; unknown labels stay
  separate.
- `tests/test_cross_study_groups.py`: one publication counts once; single-study groups are not
  compared.
- `tests/test_cross_study_relate.py`: a `SUPPORTS` between opposite directions is rejected;
  projection versus observation is always a context difference; severity comes from the rules.
- `tests/test_cross_study_tally.py`: counts, consistency labels and the sentence; values with
  different units are not combined.
- `tests/browser/test_results_screen.py`: the comparison line on the Answer tab and the table on
  the Details tab.
- One live check on a question known to have conflicting literature, with the result recorded in
  `docs/operations/`.

## Sharing with sci-graph

The package takes `{question, plan, studies: [{publication_id, passages}]}` and returns the
block above; it imports nothing from run management, storage or the API. sci-graph can call it
with an organisation's publications and a topic in place of a question. Moving the package to a
shared library is a later decision, after it has worked in sci-search.

## Phases

1. Steps 1–2 and the Details table per study (findings visible, nothing compared yet).
2. Steps 3–4 and 6 with directions only: groups and counts on the Answer tab.
3. Step 5 and the explained differences; certainty cap.
4. Numeric effects side by side.

Each phase is usable on its own.

## Open questions

- Why the AI analysis was `unavailable` in every run this week should be established first; the
  comparison needs at least two included studies, and the runs this week had 0–3.
- Whether `background` studies should be counted as a separate column instead of only listed.
- Whether the place table should start from a fixed list or be built from OpenAlex and Wikidata
  identifiers.
