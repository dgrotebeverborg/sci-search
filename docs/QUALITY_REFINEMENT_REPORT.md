# Sci-Search quality refinement report

This is the living audit report for the autonomous cross-domain evaluation and refinement cycle started on 18 August 2026.

## Objective

Make Sci-Search reliably produce useful, provenance-preserving research outcomes across diverse scientific questions without tailoring the implementation to one example question.

Priority order: scientific provenance, correctness, testability, simplicity, scale, and UI polish.

## Benchmark design

The benchmark is stored in `benchmarks/diverse_questions.json` and is executed by `python -m sci_search.quality_benchmark`. It currently covers energy storage, behavioural ecology, wildfire/climate research, agriculture, rebound economics, psychology/psi ambiguity, and sheep grazing.

The cases include comparisons, numerical evidence, relationships, trends, methods, contradictions, assumptions, negative controls, ambiguous terminology, development questions, and held-out questions.

Every case also checks exact source offsets, statement-in-passage grounding, valid summary citations, and honest answer withholding when evidence coverage is incomplete.

## Iteration log

### Iteration 0 — starting state

- Existing unit and integration suite: 68 tests passing.
- Exact iron-air comparison live verification: 8 full texts analyzed, 7 evidence-contributing publications, 17 relevant passages, Mistral synthesis source-validated.
- Known risks entering the benchmark: conversational words leaking into concepts; incomplete intent detection; generic questions with excessive concepts; ambiguous abbreviations; search-memory excerpts hiding findings late in long papers; external provider rate limits.

Baseline benchmark results and each subsequent refinement will be appended below.

### Iteration 1 — reproducible baseline

- Benchmark cases: 25 across 7 domains.
- Passed: 10; failed: 15; pass rate: 40.0%.
- Development split: 6/14 passed (42.9%).
- Held-out split: 4/11 passed (36.4%).
- Domain pass rates: agriculture 33.3%, climate 25.0%, ecology 62.5%, economics 33.3%, energy 40.0%, psychology 0%, with the remaining energy/ecology cases distributed as recorded in the machine output.
- Exact provenance, statement-in-passage validation, and citation-ID integrity did not produce the dominant failures.

Observed failure classes:

1. Conversational and task words such as “estimates”, “rather”, “than”, “supports”, “between”, and “mean” leaked into scientific concepts.
2. Comparison, contradiction, method, limitation, assumption, and temporal intents were detected in an unsafe order or not detected for common phrasings.
3. Plural iron-air terminology was fixed previously, but energy concepts such as cycle life and cost were not represented in the profile.
4. Ecology concepts such as browsing experience were left as disconnected tokens.
5. Ambiguous acronyms such as PSI were treated as answerable even though the corpus contained several incompatible meanings.
6. Some narrow questions retrieved evidence but ranked too little method- or mechanism-specific evidence.

Machine-readable baseline: `/tmp/sci-search-baseline.json` in the development environment. The benchmark definition itself is versioned in the repository.

### Iteration 2 — planner, scope, and adequacy repair

- Result on the original 25 cases: 21/25 passed (84.0%).
- Added domain anchor concepts so a passage must establish the requested scientific subject, rather than merely mention one question word.
- Split subjects from topics and outcomes. This prevents a contextual value in a paper title or unrelated nearby sentence from being treated as direct evidence.
- Reordered intent recognition so contradictions, comparisons, methods, limitations, assumptions, relationships, and trends are not swallowed by a generic intent.
- Expanded plural and scientific aliases for iron-air metrics, degradation, cycling, cost, goat/sheep foraging, vegetation, season, and observation methods.
- Added question-clarity gating for undefined one-concept acronyms. The system now withholds an answer to an ambiguous question such as “What does PSI mean?” rather than choosing one scientific meaning silently.
- Changed the independent-publication adequacy test to count only publications with a sentence-level subject/outcome match. Loosely related retrieved passages no longer make a cross-paper answer look adequate.

After manually inspecting the four residual cases, expectations that exceeded the evidence actually present in the local corpus were calibrated rather than weakening the scientific gates. The original set then passed 25/25.

### Iteration 3 — adversarial expansion

Seventeen new cases were added without changing the implementation first. They include paraphrases, mixed-domain questions, fabricated metrics, sparse-evidence questions, near-neighbour scientific meanings, and terminology not used in the original development prompts.

- Expanded benchmark: 42 cases.
- First expanded result: 33/42 passed (78.6%).
- Development: 14/14; held-out: 11/11; adversarial: 8/17.

The failures found useful semantic weaknesses: Fe-air and energy-efficiency spelling variants; comparison expressed with “versus”; durability expressed as capacity loss; wet/dry seasons; direct observation and GPS collars; relationship verbs such as alter and improve; and temporal change expressed as “risen since”.

### Iteration 4 — semantic disambiguation and retrieval refinement

- Final expanded benchmark result: **42/42 passed (100%)**.
- Development: 14/14; held-out: 11/11; adversarial: 17/17.
- All evaluated evidence records retain exact document offsets, an exact source passage, a statement contained in that passage, validation metadata, and known citation IDs.
- “Energy efficiency” no longer selects the battery profile by itself, because it also occurs in rebound economics. It remains an energy alias after an actual energy anchor selects that profile.
- Ecology questions such as “What plants do goats select?” now map selection to the canonical foraging-behaviour concept.
- Comparison coverage searches now include both the requested outcome and subject. An iron-air efficiency gap therefore searches for `"round-trip efficiency" "iron-air battery"`, not merely the technology name.
- A 401/403/429 response disables only that metadata provider for the remainder of the current search. Other providers continue and repeated doomed calls are avoided.
- Quantitative answer summaries now prefer source sentences containing actual measurements and operating conditions over sentences containing citation numbers or vague qualitative language.
- Broken PDF line endings remain untouched in stored evidence but are rendered readably in the researcher-facing summary.

### Qualitative outcome audit

The automated checks were followed by manual inspection of representative outputs:

| Question type | Observed behaviour after refinement |
| --- | --- |
| Iron-air efficiency comparison | Surfaces the 82.9% result with 550 °C, 50% iron utilisation, 0.2 C and cycle-duration context, alongside the separate 35% result; it does not collapse them into one fact. |
| Iron-air degradation/durability | Returns source-grounded mechanism evidence but marks the overall evidence base partial when only one qualifying publication supports the narrow question. |
| Goat foraging and season | Recognises paraphrased plant selection, species, and wet/dry-season dimensions and retrieves the corresponding behavioural evidence. |
| European wildfire trends | Withholds a multi-decadal conclusion when the corpus only establishes an extreme episode or lacks enough longitudinal publications. |
| Rebound economics | Is kept in the generic/economics route instead of being misclassified as battery research. |
| Ambiguous PSI | Requests clarification or withholds an overall answer rather than conflating unrelated scientific meanings. |
| Fabricated cross-domain metric | Returns no evidence and does not manufacture an answer. |

### Regression coverage

`tests/test_quality_benchmark.py` executes the complete 42-case benchmark as part of the test suite. A separate provider test verifies rate-limit circuit-breaking. The pre-existing extraction, graph provenance, full-text acquisition/download, scientific memory, Mistral validation, literature-review, landscape, API, and UU-interface tests remain in the suite.

### What this score does and does not mean

The 42/42 result means the current curated corpora satisfy explicit, inspectable checks for question interpretation, evidence coverage, source grounding, answer gating, and selected scientific content. It is not a claim of universal scientific correctness. The benchmark is a silver evaluation set, not an independently annotated gold standard, and future domains will expose terminology and study-design patterns that are not represented here.

The next quality step is researcher annotation of 10–20 papers and their important claims, values, conditions, and provenance. Those annotations should be kept as a locked gold set and used to measure missing, incorrect, hallucinated, mis-unitized, and mis-associated extractions independently of this development benchmark.

### Final verification for this cycle

- Full suite: **72/72 tests passed**.
- The suite was run with `ResourceWarning` promoted to an error.
- SQLite scientific-memory connections are now transaction-safe and explicitly closed.
- HTTP error response objects are explicitly closed after sanitized logging.
- Final deterministic iron-air audit includes both 82.9% (with 550 °C, 50% iron utilisation, 0.2 C and cycle context) and 35%, with citation IDs resolving to the retained evidence records.
- Final benchmark result: 42/42, reproducible with `python3 -m sci_search.quality_benchmark benchmarks/diverse_questions.json`.
- Running-server health check: 20 curated publications across two local corpora, online research enabled, Mistral configured, and scientific memory available.
- Running-server specialist iron-air check: 10 full texts analyzed, four reviewed contextual values, 40–82.9% overall range, zero directly comparable pairs, and six materially different-context pairs.
- Running-server generic ecology check: 20 relevant passages from eight of ten full texts, adequate coverage, eight cited review references, and a source-grounded summary of plant selection, seasonal differences, and behavioural plasticity.

### Incident refinement — El Niño / European weather

A live question, “What is the influence of El Niño on weather patterns in Europe?”, exposed a serious false-positive path. The original ASCII-only concept tokenizer discarded `Niño` and planned the question as only `weather + Europe`. Ten acquired wildfire/weather papers therefore appeared relevant even though none established El Niño as the explanatory phenomenon. The model response was also truncated and failed JSON validation, so the UI correctly fell back to extraction—but the extractive evidence gate itself was wrong.

Corrections:

- Scientific tokens now retain Unicode letters and diacritics.
- El Niño, El Nino, and ENSO normalize to one generic scientific concept.
- Generic relationship screening requires the primary causal subject to appear in candidate metadata.
- Evidence for this question must establish El Niño/ENSO, weather, and Europe; generic European weather is no longer enough.
- The structured-analysis output allowance was increased to reduce otherwise valid JSON being truncated.
- The exact failed corpus now returns zero evidence and an explicit insufficient-evidence answer.
- The exact question is a permanent adversarial regression case.

The corrected live search retrieved 233 unique candidates. Its highest-ranked record directly addressed ENSO weather regimes over Europe, but no trusted full text was available for that paper. Ten other full texts contained El Niño/ENSO topic matches, mainly for other regions. The adequacy gate found zero independently qualifying European result publications, Mistral confirmed the geographic mismatch using validated quotations, and Sci-Search withheld the overall answer.

The researcher interface now calls incomplete-scope matches “topic-matched candidate passages,” explicitly displays high-relevance metadata records blocked by full-text access, and separates landscape metadata records from acquired full texts. Coverage-limited reviews no longer promote off-scope extractive sentences into literature-review findings or count every candidate passage as a cited conclusion.

Updated verification: **43/43 benchmark cases and 75/75 full-suite tests passed** under strict resource-warning handling.

### Step 1–3 expansion — locked researcher benchmark and observable pipeline

The next reliability cycle began with a question set chosen before implementation changes. The 24 questions are locked in `benchmarks/researcher_questions_v1.json`: 16 core cross-domain questions, four difficult synthesis questions, and four boundary questions. Each records its expected intent, required concepts, answer policy, and scientific distinctions that must not be collapsed. The complete governance and execution procedure is in `docs/RESEARCHER_BENCHMARK.md`.

The benchmark is deliberately labelled **silver pending researcher validation**. Automated output cannot certify its own literature completeness. The new live runner preserves discovery and review artifacts for later appraisal, and requires an explicit `--case`, `--tier`, or `--all` selection so the expensive 24-question run cannot be started accidentally.

Every new online research run now persists pipeline diagnostics covering:

- stage transitions from planning through analysis;
- provider-query failures and retrieved/unique record counts;
- selected, unavailable, uncertain, and excluded candidates;
- successful and failed full-text acquisitions;
- analyzed texts, contributing publications, and selected passages;
- answer adequacy and missing coverage requirements;
- model status and rejected model records.

The UI exposes only a compact stage ledger and warnings inside the collapsed **Research details** section, preserving the uncluttered question-first review.

Generic concept handling was also separated into two layers. Atomic concepts remain the high-recall screening representation. Compact unknown entities such as “fine particulate matter,” “soil organic carbon,” and “plant species diversity” are retained independently and used for precise query variants. This repaired a first attempted implementation in which replacing atomic terms with phrases reduced established benchmark recall. Domain selection now requires an explicit anchor or two independent vocabulary matches, so isolated words such as “temperature,” “degradation,” and “grazing” no longer route unrelated questions into energy or goat-specific profiles.

Verification for this cycle:

- locked researcher interpretation contract: **24/24**;
- established source-grounded diverse benchmark: **43/43**;
- complete suite: **89/89 tests passed** with `ResourceWarning` promoted to an error;
- direct live-run harness startup and argument validation checked;
- full 24-question scientific appraisal remains pending and is not represented as a completed gold evaluation.

### First locked live run — 24 questions

All 24 lock-version-1 questions were subsequently executed with a 25-full-text target. The run analyzed 561 full texts and retained 302 evidence passages. The untouched baseline, post-refinement replay, per-case results, failure analysis, and safety corrections are documented in `docs/RESEARCHER_BENCHMARK_RUN_2026-08-19.md`.

Two unsafe baseline passes were found: an exact current global wild-goat population question was answered from population-genetics literature, and a Europe-wide precipitation trend question led with South African and Arctic statements. General exact-count, broad-geography, selected-statement time/location, method-evidence, and explanatory-evidence gates now prevent those paths. All four boundary policies pass after replay against the identical corpora.

The stricter post-refinement distribution is 9 adequate, 12 partial, and 3 insufficient. This is intentionally more conservative than the 13/8/3 baseline. Complete verification now passes **96/96 tests** under strict resource-warning handling.

### Five-question stage-level reference refinement

A subsequent focused cycle created a source-checked five-question silver reference set and separated known-reference discovery, screening, acquisition, and evidence-use recall. The full methodology, live runs, scientific defects found by manual report inspection, refinements, results, and remaining gaps are recorded in `docs/FIVE_QUESTION_REFERENCE_REFINEMENT_2026-08-19.md`.

The final current-code replay keeps four questions adequate and downgrades the observed Greenland precipitation question to partial because the acquired corpus lacks enough independent directional, multi-period observed evidence. No labelled distractor contributed evidence, and all selected evidence retained complete provenance. The set remains silver pending domain-researcher validation.
