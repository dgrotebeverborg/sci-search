# Targeted source recovery — 12 November 2026

This experiment investigates two retained silver-reference gaps without changing
the benchmark labels, historical runs or production acquisition budgets. The DOIs
were known in advance; this is targeted recovery, not a blind discovery benchmark.

## Acquisition diagnosis

Both studies were already selected in the historical runs. Each run acquired its
25 permitted full texts before reaching the target. The biochar reference was
68th among selected candidates; the wearable reference was 37th. Reordering the
same snapshots with current code puts them at positions 37 and 47, respectively,
so current prioritization alone does not guarantee either fits a 25-paper budget.
Absence of an attempt was a budget/ranking outcome, not a failed download.

Live acquisition now succeeds using the existing acquisition implementation and
the retained candidate metadata, without an API key:

| Reference | Acquisition | Screening after repair | Selected evidence from recovered source |
| --- | --- | --- | --- |
| `10.1007/s42773-022-00138-1` | Springer OA PDF, 2,753,349 bytes | included | 3 records |
| `10.2196/82475` | Europe PMC XML, 114,070 bytes | included | 0 records |

The biochar PDF yields 76,487 extracted characters. All three selected statements
occur in their source passages and the stored offsets reproduce those passages
exactly. In the combined retained-plus-recovered biochar corpus, all four known
direct references now contribute evidence, compared with three previously. This
does not establish completeness of the literature or scientific correctness.

## Vocabulary repair

The wearable XML yields 34,979 parsed document characters. Initially, screening
marked it uncertain: metadata uses “wearable ECG”, while the requested “wearable
devices” scope lacked that explicit device subtype. The primary-subject rule
requires a metadata match as well as a body match; repeated mentions in the body
alone do not establish focus.

The scope alias list now also accepts “wearable ECG” and “wearable
electrocardiogram”. This is a general device synonym change, with no DOI or
benchmark-specific production rule. Required atrial-fibrillation and clinical ECG
reference scope remain in force. Tests cover both synonyms and reject controls
missing the wearable device, arrhythmia or reference context.

The recovered wearable source passes full-text screening without an override,
but currently contributes no selected answer evidence. Acquisition, inclusion and
answer support are separate stages; this source must not be counted as used merely
because it was downloaded. Its later passage/answer-scope gap remains unresolved.

## Artifacts and limits

`data/validation_runs/source-recovery-20261112/` contains `acquisition.json`,
`analysis.json`, each recovered corpus, screening decisions and combined
investigations. `acquire.py` reproduces the two bounded live downloads; `replay.py`
reproduces the screening and combined-corpus analysis. Existing source documents
are loaded from the original baseline corpus, while recovered source documents
are loaded from the separate recovery corpus; both roots are recorded in
`analysis.json`.

Ruff and targeted Pyright pass with zero errors or warnings. A separate code
review found no blocking issues. The full suite passes with the isolated integration
services: 1,646 passed, 24 skipped and 27 subtests passed in 139.24 seconds.

`baseline-references5.json` replays the unchanged five baseline corpora with the
new aliases. Known-reference use remains 15/19, no known reference is lost and all
five adequacy labels remain unchanged. The wearable baseline now supplies seven
evidence records instead of four, all seven passing the provenance-field checks.
All other reference-report fields remain identical. This baseline replay is
separate from the targeted biochar recovery described above.

The retained scientific suite reports 38 passed,
5 subtests passed and the same existing failure:
`QualityBenchmarkTests.test_diverse_question_benchmark_passes_with_exact_provenance`,
case `rebound-time-comparison` (expects partial, receives adequate).

The PDF parser still emits its existing missing-fontTools warnings. Exact passage
grounding checks verify the extracted text, not fidelity of every glyph or a
scientific interpretation. No model synthesis or independent human scientific
validation was performed. A future general acquisition-policy experiment should
compare review budgets on fresh questions; these targeted recoveries do not by
themselves justify raising the default or prioritizing known benchmark DOIs.
