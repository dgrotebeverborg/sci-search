# Validation hardening audit — 2026-08-20

## Outcome

Sci-Search now has a researcher-facing, blind-by-default validation workflow for ten cross-domain questions. It is suitable for creating a genuine gold evidence set; it does **not** claim that the application is scientifically validated before those judgments exist.

The frozen paper acquisitions from the original benchmark runs were replayed with the current deterministic pipeline. External generative analysis was disabled for this replay. The replay manifest records the code fingerprint and SHA-256 hashes of every source and replay run. At the end of this pass:

- all 10 cases have a replay;
- the replay fingerprint matches the current scientific pipeline code;
- all 10 cases contain at least one negative control;
- the original baseline runs remain unchanged;
- 0 of 10 cases are evaluable and `release_ready` is false until researcher annotation.

## Current-code replay results

| Case | Acquired full texts | Included by system | Evidence passages | Answer status |
|---|---:|---:|---:|---|
| Iron-air round-trip efficiency comparability | 25 | 15 | 24 | adequate |
| Greenland observed precipitation change | 25 | 21 | 24 | partial |
| European wildfire trend | 25 | 8 | 24 | partial |
| El Niño influence on European weather | 25 | 14 | 24 | adequate |
| Goat foraging effects on vegetation | 25 | 21 | 24 | adequate |
| Wearables for atrial-fibrillation detection | 25 | 1 | 1 | partial |
| Biochar yield-effect heterogeneity | 25 | 23 | 24 | adequate |
| Iron-air LCOS assumptions | 25 | 17 | 3 | partial |
| Iron-air degradation mechanisms | 11 | 2 | 0 | insufficient |
| Current global wild-goat population | 25 | 17 | 24 | partial |
| **Total** | **236** | **139** | **172** | — |

These are pipeline outcomes, not researcher correctness judgments. In particular, the AF, LCOS, and degradation cases reveal retrieval or evidence-selection weaknesses that must remain visible during validation.

## Refinements made

1. Added immutable current-code replay tooling in `scripts/replay_validation_benchmark.py`.
2. Made source inspection first-class: reviewers can open each acquired full text and jump from an answer assertion to its cited evidence.
3. Made review blind by default; silver and system decisions are hidden until explicitly revealed.
4. Added reviewer identity, filters, keyboard navigation, progress feedback, missed-publication capture, and mandatory reasons for negative or uncertain judgments.
5. Added tri-state evidence checks so unassessed fields can never be counted as correct.
6. Added screening recall, hallucinated-value, and missing-conclusion metrics; minimum sample requirements; Wilson confidence intervals; macro and micro aggregates; and hard gates for provenance and unsupported assertions.
7. Required complete publication, assertion, evidence, and conclusion review before a case can become gold-eligible.
8. Added per-case negative controls and benchmark/replay integrity reporting.
9. Added a complete ZIP audit export and a standalone researcher guide.

## Verification performed

- Full automated suite: **116 tests passed**, with one local-socket test skipped inside the restricted test sandbox.
- The same HTTP validation workflow test was separately run with local sockets enabled and passed.
- JavaScript syntax was checked with Node.
- The replay manifest and live workspace report matching code fingerprints, all replay files present, and negative controls in every case.
- A live-server API and browser-render smoke test is performed after each restart; the final outcome is recorded in the handoff message.

## Release interpretation

Engineering checks show that the workflow is reproducible, auditable, and conservative. They do not establish scientific accuracy. A qualified researcher should annotate all ten cases, ideally followed by an independent second reviewer and adjudication of disagreements. Only then should metric thresholds inform a release decision.
