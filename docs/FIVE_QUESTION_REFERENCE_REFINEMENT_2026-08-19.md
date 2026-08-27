# Five-question reference-set refinement — 19 August 2026

## Purpose and status

This cycle tested whether Sci-Search finds and represents the right scientific evidence, not merely whether it produces a plausible report. It covers five tasks and domains:

1. iron-air round-trip-efficiency comparison;
2. observed Greenland Ice Sheet precipitation change since 2000;
3. vegetation availability and domestic-goat foraging;
4. causes of heterogeneous biochar crop-yield effects;
5. wearable atrial-fibrillation diagnostic accuracy against clinical ECG.

The reference set is `benchmarks/researcher_five_silver_v1.json`. It is **silver, source-checked, and pending domain-researcher validation**. Its direct references are known-relevant publications, not an exhaustive bibliography. Reported recall is therefore recall of known silver references, not recall of the complete literature.

## Evaluation design

`sci_search/reference_evaluation.py` and `scripts/evaluate_reference_set.py` measure losses independently at four stages:

- publication discovered;
- publication selected during metadata screening;
- full text acquired;
- publication contributed selected evidence.

They also check known distractor use and provenance completeness. Discussion-paper and final-version DOI aliases can represent one scientific work without being counted as separate misses.

Every selected evidence record is considered provenance-complete only when it retains publication, source document, exact passage and offsets, a statement contained in that passage, and extraction method.

## Baseline diagnosis

Machine-readable baseline: `data/benchmark_results/researcher_five_silver_baseline.json`.

| Case | Discovery | Selection | Acquisition | Evidence use | Main baseline defect |
| --- | ---: | ---: | ---: | ---: | --- |
| Iron-air RTE | 100% | 100% | 100% | 100% | AI answer later proved insufficiently comparative despite valid grounding. |
| Greenland observed precipitation | 100% | 100% | 67% | 67% | Future/model passages could satisfy an observed-trend question. |
| Goat vegetation/foraging | 100% | 100% | 100% | 100% | No known-reference loss. |
| Biochar heterogeneity | 100% | 75% | 50% | 50% | A direct meta-regression with no abstract was blocked; cached studies displaced new syntheses. |
| Wearable AF accuracy | 100% | 75% | 25% | 0% | A correct acquired validation paper was reduced to an introductory sentence; the best systematic review fell outside the full-text budget. |

All baseline evidence records had complete provenance, and no labelled distractor contributed selected evidence.

## Refinements made

### Query planning

- Task-specific strategies now precede broad sensitivity variants, so the eight-query cap cannot silently remove the diagnostic, temporal, or explanatory query.
- Diagnostic questions add sensitivity, specificity, reference-standard, and validation terminology.
- Explanatory questions add heterogeneity, moderator, and meta-analysis terminology.
- Observed precipitation questions add snowfall, rainfall, accumulation, reconstruction, and surface-mass-balance terminology.

### Screening and acquisition

- A processable open full text with a strongly matching title may proceed when its abstract is missing; scientific evidence gates still operate on the acquired text.
- Four bounded early acquisition positions preserve high-ranked review/synthesis coverage without allowing reviews to dominate the corpus.
- Meta-analyses, meta-regressions, and heterogeneity studies receive a task-specific boost for explanatory questions.
- Cached documents no longer have absolute priority. Reuse receives a small bonus, while a more relevant new paper can outrank cached but weaker material.

### Evidence extraction and adequacy

- Compound entities are used for diagnostic scope: wearable devices, atrial fibrillation, and clinical/reference ECG are no longer treated as seven unrelated mandatory words.
- `clinical ECG measurements` recognizes conservative equivalents such as 12-lead reference ECG and ECG gold standard.
- Diagnostic questions require a numerical diagnostic metric tied to a clinical/reference ECG, not a generic AF-detection mention.
- Diagnostic sentence ranking prefers sensitivity, specificity, predictive value, accuracy, or AUC results over introductions.
- Temporal questions distinguish observed from projected statements and require a source-reported direction of change.
- Explanatory summaries prioritize cross-study heterogeneity and multiple moderators, and avoid filling the summary with a narrower within-study explanation when stronger synthesis statements are available.

### Model validation

- A grounded Mistral answer to a comparability question must cite at least two evidence records and actually discuss differences, context, scale, conditions, or boundaries.
- The analysis-cache contract was versioned so previously accepted but insufficiently responsive answers are not silently reused.

## Final measured result

Final live-stage evaluation: `data/benchmark_results/researcher_five_live_final_evaluation.json`.

Final replay through the current scientific gates: `data/benchmark_results/researcher_five_current_code_final_replay.json`.

| Case | Discovery | Selection | Acquisition | Evidence use | Current adequacy |
| --- | ---: | ---: | ---: | ---: | --- |
| Iron-air RTE | 100% | 100% | 100% | 100% | Adequate evidence; a one-value AI answer is now rejected as non-comparative. |
| Greenland observed precipitation | 67% | 67% | 67% | 67% | **Partial; overall answer withheld** because independent directional multi-period evidence remains insufficient. |
| Goat vegetation/foraging | 100% | 100% | 100% | 100% | Adequate. |
| Biochar heterogeneity | 100% | 100% | 75% | 75% | Adequate; the heterogeneous-yield meta-regression is now acquired and used. |
| Wearable AF accuracy | 100% | 75% | 50% | 50% | Adequate from four evidence-contributing publications, including a systematic review and clinical validation results. |

Across all five final corpora:

- no labelled distractor contributed selected evidence;
- provenance completeness was 100%;
- AF known-reference acquisition/evidence use improved from 25%/0% to 50%/50%;
- biochar selection/acquisition/evidence use improved from 75%/50%/50% to 100%/75%/75%;
- Greenland became more conservative rather than producing a confident but poorly matched summary.

## Important limitations

- The Greenland search missed one known reconstruction publication in the final live rerun. Additional query expansion did not recover it reliably within provider result limits. This remains a retrieval gap.
- Only half of the four known AF references were acquired. The final evidence base contains other directly relevant clinical studies, but known-reference acquisition remains below the 80% target.
- One of four known biochar references was not acquired. The improved corpus includes the central heterogeneous-response meta-regression, but acquisition remains below the 80% target at 75%.
- Mistral structured output was rejected for Greenland and biochar because answer-level quotes failed strict selected-statement validation. The deterministic evidence layer remained available; model prose was not accepted merely because it was fluent.
- The silver set cannot establish complete-publication recall, final scientific correctness, or expert agreement. Those require researcher review.

## Reproduction

Validate/replay the reference set:

```bash
python3 scripts/evaluate_reference_set.py \
  --replay-analysis \
  --benchmark-result data/benchmark_results/researcher_five_live_post_refinement.json \
  --benchmark-result data/benchmark_results/researcher_three_live_refined_v2.json \
  --benchmark-result data/benchmark_results/researcher_two_live_refined_v3.json \
  --benchmark-result data/benchmark_results/researcher_biochar_live_refined_v4.json
```

The next useful step is a researcher review of the five packages: confirm reference inclusions/exclusions, mark key passages and answer components, and record important missing publications. Only then should this set be promoted from silver to gold.
