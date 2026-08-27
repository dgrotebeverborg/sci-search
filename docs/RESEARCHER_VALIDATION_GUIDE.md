# Sci-Search researcher validation guide

## Purpose

This review measures Sci-Search; it is not a request to improve the answer while reviewing it. Record what the saved replay actually retrieved and stated. Use **Blind review** for the first pass so system and silver labels do not influence your judgment.

Estimated time is 25–45 minutes per question, depending on the number and complexity of evidence passages. Save a case as in progress whenever you stop; the workspace reopens the first unfinished case.

## 1. Publication relevance

- **Relevant:** directly provides evidence needed to answer the complete question.
- **Background:** scientifically relevant context, but does not directly answer every requested dimension.
- **Irrelevant:** wrong subject, outcome, population, geography, period, technology, or evidence type.
- **Uncertain:** full text or specialist knowledge is insufficient to decide.

Check every acquired publication and every silver reference. Add the DOI of any important publication that is absent from the retrieval ledger. This is essential: otherwise literature-search recall cannot be measured.

## 2. Answer assertions

- **Supported:** the cited evidence justifies the statement at its stated scope and strength.
- **Unsupported:** the evidence does not justify the statement, contradicts it, or has been generalized beyond its scope.
- **Unclear:** support cannot be decided from the available material.

An exact quote can still be scientifically insufficient. Check population, method, time, geography, evidence type, and causal language—not only word overlap.

## 3. Evidence records

- **Result:** the passage actually states the extracted scientific result.
- **Value:** the numerical value or range is transcribed correctly.
- **Unit:** the unit and any scale or denominator are correct.
- **Provenance:** publication, passage, section/page, and source association are correct.
- **Context:** conditions, population, experimental or modeled nature, scale, and assumptions are attached to the right result.

Choose **not assessed** for genuinely non-applicable numerical fields. It is excluded from the denominator and is never counted as correct. Any incorrect field requires a short reason.

## 4. Important conclusions

Mark whether the final review covers each question-specific component. “Covered” means the component is addressed responsibly; a justified statement that evidence is insufficient can count as covered.

## Completion and adjudication

A case can only be completed after all required publication decisions, answer assertions, evidence records, and important conclusions have been assessed. Provenance below 100% and any unsupported answer assertion are hard failures.

For formal evaluation, two researchers should independently review each case. Resolve disagreements in a separate adjudication pass without overwriting either original review. The current local workspace records one active reviewer per annotation; exported packages preserve reviewer names, timestamps, reasons, replay fingerprints, and all machine-readable records.

## Export

Use **Export** in the validation header. The ZIP contains the benchmark specification, replay manifest, scorecard, complete case views, annotations, and this guide. Keep exports as dated audit snapshots.
