# Sci-Search researcher benchmark

## Purpose

The locked benchmark in `benchmarks/researcher_questions_v1.json` contains 24 questions selected before the next retrieval refinements. It covers energy, climate, ecology, agriculture, materials, environmental science, public health, and medicine. The set includes 16 core questions, four difficult synthesis questions, and four boundary questions where a safe system may need to qualify or withhold an answer.

The question text and expected interpretation are immutable within lock version 1. A change to a question requires a new lock version. Implementation code must not contain case-specific conclusions or expected numerical answers.

## What is recorded for every question

- expected intent and required scientific concepts;
- the answer policy, such as requiring multiple contextual results or rejecting a universal ranking;
- distinctions the synthesis must preserve, such as observed versus projected or measured versus assumed;
- discovery, screening, acquisition, analysis, and model-validation diagnostics;
- contributing publications, selected passages, answer adequacy, and citation-ID integrity;
- the complete research-run artifact for later source appraisal.

## Validation levels

The current benchmark is **silver, pending researcher validation**. Sci-Search can automatically validate its interpretation contract, exact source linkage, citation integrity, pipeline coverage, and answer gating. It cannot establish that the retrieved corpus is scientifically complete merely by checking its own output.

A case is promoted to gold only after a researcher records:

1. publications that must be retrieved;
2. publications that look relevant but should be excluded;
3. key supported conclusions and important counterevidence;
4. required distinctions and context;
5. whether a conclusion should be answerable from the available literature.

This separation prevents retrieval results from becoming their own ground truth.

## Reproducible commands

Validate all 24 question contracts without using the network:

```bash
python3 -m unittest tests.test_quality_benchmark.QualityBenchmarkTests.test_locked_researcher_question_benchmark_is_valid_and_plannable -v
```

Run one complete live case:

```bash
python3 scripts/run_researcher_benchmark.py \
  --case climate-greenland-observed \
  --max-full-texts 25 \
  --output data/benchmark_results/greenland-observed.json
```

Run a tier or the complete locked set by selecting `--tier core`, `--tier hard`, `--tier boundary`, or `--all`. Results are written after every case so an interrupted long run retains completed work.
Reusing the same output path resumes from its completed cases after verifying the locked-question digest.

## Step 1–3 implementation record — 2026-08-19

1. **Locked benchmark:** the 24 proposed questions, their answer policies, and necessary scientific distinctions are machine-readable and contract-tested. A separate live runner preserves each end-to-end artifact. No case has been falsely labelled gold.
2. **Pipeline diagnostics:** every live run now records a stage ledger plus provider failures, screening outcomes, unavailable full texts, acquisition failures, contributing publications, selected passages, answer adequacy, missing requirements, model status, and rejected model records. The clean interface displays a compact version only inside the collapsed Research details section.
3. **Generic entity recognition:** known domain concepts and unknown compound scientific entities are represented separately. Atomic concepts preserve high-recall screening; phrases such as `fine particulate matter`, `soil organic carbon`, and `plant species diversity` provide precise query variants. Domain profiles now require an anchor or two independent concept matches, preventing words such as `temperature`, `degradation`, or `grazing` from selecting an unrelated specialist profile.

The legacy 43-question corpus benchmark remains independent and must continue passing. It protects source-grounded extraction and previously corrected regressions while the new benchmark evaluates broader researcher behaviour.
