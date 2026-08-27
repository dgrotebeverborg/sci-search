# Scientific validation workspace — 2026-08-20

## What was built

Sci-Search now contains a versioned ten-question benchmark connected to ten completed research runs. Each run has a separate, reproducible replay under `data/validation_replays/v1/`; the acquired paper files are preserved while derived screening, extraction, and synthesis artifacts are rebuilt with the recorded code fingerprint. It spans energy, climate, ecology, medicine, agriculture, and one deliberately unanswerable boundary question.

The benchmark begins as **silver**, not gold. Five cases contain source-checked relevant, contextual, and distractor publications from the existing silver reference set. The other five begin without reference labels. Automated system output is never copied into researcher-confirmed truth.

The browser’s **Validate quality** workspace is blind by default and lets a researcher review:

1. publication relevance and full-text screening decisions;
2. every answer assertion for support, lack of support, or uncertainty;
3. extracted result, value, unit, provenance, and context correctness;
4. coverage of question-specific important conclusions;
5. case-level notes and completion status.

Annotations are stored separately under `data/validation_annotations/`. Baseline run artifacts are not rewritten. Reviewers can search and filter publications, open the acquired full text, jump from assertions to exact evidence, record missed publications, and export a complete audit package.

## Scorecard and release gates

The scorecard calculates:

- relevant-publication recall;
- full-text screening precision;
- evidence-result correctness;
- numerical-value correctness;
- unit correctness;
- provenance correctness;
- context-association correctness;
- important-conclusion coverage;
- unsupported answer assertions.

Unassessed fields are excluded from denominators and shown as pending. They are never counted as correct. Provenance below 100% and any unsupported answer assertion are hard release failures.

A case is gold-eligible only when a researcher marks it complete and no hard gate fails. The complete benchmark is release-ready only when all ten cases are gold-eligible.

## Seed audit

The five source-checked cases contain 25 silver publication labels. All 25 were present in their baseline discovery ledgers; 19 had acquired full text. These labels remain pending until explicitly confirmed in the validation workspace.

The final current-code replays contain 236 acquired full texts, 139 system-included full texts, and 172 selected evidence passages in total. One deliberately difficult degradation-mechanism run contains no extracted evidence, which is retained as a useful failure case rather than silently replaced. The wearable-atrial-fibrillation case contains only one selected evidence passage, and the LCOS case contains three; both expose serious recall limitations for human review.

## Running the scorecard

Open Sci-Search and choose **Validate quality** in the header, or export the current machine-readable scorecard:

```bash
python3 scripts/validation_scorecard.py --output data/validation-scorecard.json
```

Before researcher annotation, the correct aggregate result is `0` evaluable cases and `release_ready: false`.

Use **Export audit** in the validation workspace to download the benchmark specification, replay manifest, scorecard, all case material, all annotations, and the researcher guide in one ZIP file. See [RESEARCHER_VALIDATION_GUIDE.md](RESEARCHER_VALIDATION_GUIDE.md) for the labeling protocol and [VALIDATION_HARDENING_2026-08-20.md](VALIDATION_HARDENING_2026-08-20.md) for the implementation and test audit.
