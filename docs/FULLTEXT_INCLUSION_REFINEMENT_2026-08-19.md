# Full-text inclusion refinement — 2026-08-19

## Purpose

Downloading a paper is no longer treated as evidence that it belongs in a review. Sci-Search now performs a question-specific check over the parsed full text after acquisition and before analysis, scientific-memory ingestion, or packaging.

Decisions are `included`, `background`, `uncertain`, or `excluded`. Included and relevant-background records enter the active corpus. Uncertain and excluded records remain in the screening ledger and can be overridden by a researcher.

## Failure cases used during refinement

- A downloaded Greenland paper behind goat-foraging metadata was excluded from the active corpus and package.
- Dairy-goat, ozone, dental, and unrelated hydrology papers in a Greenland run were excluded or held as uncertain because the Greenland Ice Sheet was not their substantive focus.
- A Holocene Greenland precipitation study was excluded for a question restricted to change since 2000.
- Snow-leopard and little-owl foraging papers were excluded from a domestic-goat vegetation review because goats were not the study focus or the requested relationship was absent.
- All acquired direct goat-foraging references in the silver set remained included.
- The acquired all-iron and iron-flow distractors were excluded from the iron-air review.

## Five-question silver-set audit

The audit command is:

```bash
python3 scripts/audit_fulltext_screening.py
```

Observed decisions for acquired papers after refinement:

| Case | Included | Background | Uncertain | Excluded |
|---|---:|---:|---:|---:|
| Iron-air RTE comparability | 13 | 2 | 5 | 5 |
| Greenland precipitation since 2000 | 21 | 0 | 1 | 3 |
| Goat vegetation and foraging | 13 | 8 | 2 | 2 |
| Biochar crop-yield heterogeneity | 24 | 0 | 1 | 0 |
| Wearable AF versus clinical ECG | 1 | 0 | 20 | 4 |

For the acquired labelled references, all four direct goat papers, both acquired direct biochar papers, the acquired direct Greenland paper, and three of four acquired direct iron-air papers were included. The remaining direct iron-air paper was conservatively marked uncertain. Known acquired distractors were excluded or marked uncertain rather than silently included.

## Interpretation

This gate intentionally prefers withholding to false inclusion. The wearable-AF case demonstrates the trade-off: many records are uncertain because the full text and available metadata do not jointly establish all three requested comparison entities. These papers remain visible for researcher adjudication instead of disappearing.

This is an automated relevance check, not dual independent screening or a risk-of-bias assessment. Its decisions and reasons are exported in `data/full-text-screening.json` and in the literature-review appendix.
