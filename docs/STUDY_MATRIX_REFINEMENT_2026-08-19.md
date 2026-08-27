# Question-specific study matrix refinement — 2026-08-19

## Goal

Make every acquired full text inspectable at study level before it contributes to a cross-paper answer. The matrix complements the evidence-passage graph; it does not replace it and does not turn an acquired document into included evidence automatically.

## Implemented

- One question-specific card per acquired publication.
- Exact selected passages with publication ID, section, page where recoverable, and character offsets into parsed source text.
- Required-question-dimension coverage with supporting passage IDs.
- Extractive methods, results, limitations, and assumptions; no generated text is stored as source evidence.
- Conservative evidence-nature inference with the matched cues retained.
- Optional Mistral adjudication only for deterministic `uncertain` decisions.
- Strict adjudication schema and exact-quote validation. An `include` proposal is downgraded unless all required dimensions have validated support; deterministic exclusions are never AI-promoted.
- Researcher overrides for include, relevant background, and exclude.
- Collapsed UI review queue with coverage, missing dimensions, a source passage, and override controls.
- Matrix in investigation JSON, cited review, and complete research-package ZIP (`data/study-matrix.json`).

## Tests and refinements

Automated tests cover exact passage offsets, question-dimension linkage, successful promotion with complete exact-quote support, rejection of a hallucinated quote, package inclusion, UI presence and safe escaping, and the complete pre-existing regression suite.

An existing 50-paper Greenland Ice Sheet run was rebuilt as a migration check. It produced 50 study cards and 300 selected passages while retaining the prior screening distribution: 38 included/background, 6 excluded, and 6 uncertain. The complete package contained the matrix and a PDF review; no screening decision changed simply because the matrix was added.

## Current boundary

The matrix is an auditable screening and evidence-orientation layer, not a formal risk-of-bias instrument. Evidence-nature labels are cue-based and explicitly marked as inferred. AI adjudication improves review throughput when configured, but source grounding is not equivalent to expert scientific validation; uncertain cases remain visible for researcher review.
