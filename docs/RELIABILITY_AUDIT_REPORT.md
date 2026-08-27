# Sci-Search reliability audit

This report records the broad reliability audit started after the El Niño/European-weather false-positive result. It is separate from the earlier extraction refinement log because its purpose is to challenge whether Sci-Search should answer at all, not merely whether evidence records are syntactically valid.

## Audit questions

The audit separates five properties that must not be conflated:

1. **Source integrity:** Is the quotation exactly reconstructible from the retained full text and offsets?
2. **Retrieval relevance:** Does a candidate passage mention the scientific subject rather than only nearby vocabulary?
3. **Complete-scope answerability:** Does supporting evidence cover the required subject, outcome, geography, time, and relationship or comparison?
4. **Synthesis promotion:** Are only complete-scope records allowed into the answer and literature-review findings?
5. **Robustness:** Do irrelevant substitutions lose answerability, and do scientific aliases preserve broadly similar retrieval?

These are evaluated separately. A source can be quoted perfectly and still be irrelevant to the research question.

## Historical run audit

`python3 -m sci_search.reliability_audit data/research_runs` re-analyzes every persisted investigation using the current planner and adequacy gates while preserving the old artifacts for comparison.

- Persisted run directories: 30.
- Investigation artifacts audited: 28.
- Failed/incomplete runs without an investigation artifact: 2.
- Stored evidence records checked: 191.
- Exact passage/offset/statement reconstructions: **191/191 (100%)**.
- Historical artifacts that presented an answer but are withheld by current gates: **12/28**.
- Historical answer-promoted evidence records covering every currently required dimension: **37/61 (60.7%)**.
- Historical stored evidence records covering every dimension, including passages never promoted to an answer: 82/191 (42.9%). Candidate passages are now explicitly distinguished from answer evidence.

The twelve unsafe historical artifacts comprised:

- one small tomato-salinity run;
- seven undersized or overly broad goat-foraging runs;
- two European wildfire-trend runs;
- one early iron-air comparison run;
- the incorrect El Niño/European-weather run.

This result confirms that the old system's strongest property was quotation provenance. Its weakest property was deciding whether those quotations jointly answered the complete question.

## Counterfactual and paraphrase baseline

The new benchmark is `benchmarks/metamorphic_questions.json`. It contains:

- 12 negative controls that replace an essential entity, domain, or geography;
- 8 paraphrase-invariance pairs, representing 16 phrasings.

Examples include magnesium-sulfur values searched in the iron-air corpus, alpaca evidence searched in the goat corpus, Antarctic wildfire trends, pharmaceutical rebound, El Niño weather on Mars, and a deliberately invalid connection between precognitive psi and yeast prions.

The first run passed **12/20 (60%)**. Failure classes were:

- partially related passages remained visible for several counterfactuals, although the answer was withheld;
- Europe and European were treated differently when decomposing geography;
- El Niño and ENSO produced materially different result sets;
- modeled and modelled produced different plans;
- a trend-disagreement question was incorrectly routed as a temporal-trend request rather than a contradiction request.

Candidate visibility and answer promotion are now tested separately. A near-miss passage may remain inspectable, but a negative control must have no answer citations and must be judged unanswerable.

Final metamorphic result: **20/20 passed (100%)**.

## Safeguards added or strengthened

- Unicode scientific terms and diacritics are retained.
- El Niño, El Nino, and ENSO normalize to one concept.
- Location aliases such as Europe/European and Antarctica/Antarctic share one explicit geographic dimension.
- Contradiction intent takes precedence when a question asks why trend studies disagree.
- Task words and inflections such as methodological, conflicting, modelled, changed, and differences no longer become scientific subjects.
- Unknown counterfactual entities cannot be ignored merely because two familiar concepts match.
- Complete-scope answerability now requires all topic and scope dimensions in the supporting passage.
- For relationship, contradiction, and limitation questions, the first and last core scientific concepts must also occur in the selected result statement. Requested geography must be present at statement level for causal/comparative answers.
- Quantitative comparisons may use an explicit technology anchor from the same retained passage when the adjacent result sentence contains the requested metric, value, and conditions. This preserves valid scientific prose such as an iron-air introduction followed by an `82.9% at 550 °C and 0.2 C` result, without detaching the value from its context.
- Domain anchors such as goat, sheep, and iron-air remain mandatory where applicable.
- Candidate passages are separate from answer-qualified evidence.
- Coverage-limited results have no answer citations and do not promote deterministic near-matches into literature-review findings.
- The interface labels incomplete material as topic-matched candidate passages and explicitly says when an overall answer is withheld.
- Research-landscape metadata counts are displayed separately from acquired full texts.
- Highly relevant metadata records blocked by full-text availability are explicitly reported as a full-text gap.

## Current automated verification

- Scientific question benchmark: **43/43**.
- Metamorphic counterfactual/paraphrase benchmark: **20/20**.
- Complete unit and integration suite with resource warnings treated as errors: **87/87**.
- Defined question executions across those suites: 71 (43 ordinary cases, 12 counterfactuals, and 16 alias/paraphrase phrasings).
- Historical artifacts independently re-analyzed: 28.
- Exact provenance audit: 191/191 stored records.

The automated regression suite runs both benchmarks and specifically verifies that the historical El Niño artifact is detected as unsafe while the corrected run is withheld without losing source integrity.

## Greenland precipitation incident and refinement

The question “What has been the change in precipitation over the Greenland Ice Sheet during the 21st century?” initially acquired 23 full texts but found only two contributing publications, despite highly relevant open literature being readily discoverable. The trace identified several independent faults:

- `over` was incorrectly treated as a scientific concept and the question was routed as a relationship rather than a temporal trend;
- `Greenland Ice Sheet` was fragmented rather than retained as a compound subject;
- Crossref open-access PDF URLs, including Copernicus URLs marked with an `unspecified` content type, were discarded;
- two-column PDF layout extraction interleaved scientific prose;
- preprint and final-version DOIs pointing to one identical PDF were counted independently;
- Mistral could inspect candidate passages that had not passed the answer-evidence gate;
- an assertion could quote a future-projection sentence elsewhere in the same passage while the selected statement described present-day observations.

The corrected high-recall run acquired 36 unique full texts with 36 unique source documents, found 24 relevant passages across 14 publications, and passed the deterministic adequacy gate with nine contributing publications. The displayed summary now separates observed-to-date regional evidence from future model evidence. Model assertions are restricted to answer-qualified evidence and their quotes must occur inside the selected result statement, not merely somewhere in the surrounding passage. Invalid model synthesis is withheld in favor of the extractive evidence summary.

## Remaining limitations

This is still a silver reliability evaluation, not expert certification.

- Most questions use corpora already accumulated during development; this does not measure exhaustive recall over the entire scientific literature.
- Counterfactual tests can demonstrate useful invariants, but cannot prove that a nuanced scientific interpretation is correct.
- Exact quotation validation proves that a source said something, not that the study is methodologically sound or that Sci-Search interpreted it correctly.
- Mistral is used only after deterministic evidence selection and every retained assertion must quote known evidence. A second model pass is not an independent scientific expert.
- No formal risk-of-bias assessment, meta-analysis, or researcher-created gold annotations exist yet.
- The current domain profiles cover energy storage and behavioural ecology better than arbitrary unseen disciplines.

The responsible product description remains: **experimental provenance-aware scientific evidence discovery with conservative answer withholding**.

## Small future expert task

When a researcher becomes available, the highest-value contribution is not reviewing every run. It is labeling a locked set of 10–20 papers and approximately 20 questions with:

- essential question dimensions;
- relevant and irrelevant passages;
- correct claim–condition associations;
- values and units;
- comparability decisions;
- whether an overall conclusion is justified.

Those annotations would convert the strongest silver cases into a genuine gold evaluation set.
