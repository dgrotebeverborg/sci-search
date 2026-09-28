# Contradiction groups: researcher quality check

Purpose: decide whether single-call contradiction grouping is good enough, or whether the separate
adjudication pass described in the
[design spec](../superpowers/specs/2026-09-24-contradiction-groups-design.md) is needed. This
check is manual and not part of CI.

## Procedure

1. With `OPENALEX_API_KEY` and the selected analysis provider's key configured, run two online
   research questions. Use `SCI_SEARCH_ANALYSIS_PROVIDER=mistral` with `MISTRAL_API_KEY`, or
   `SCI_SEARCH_ANALYSIS_PROVIDER=openai` with `OPENAI_API_KEY`.
   The local `investigate` command does not call the analysis model, so it never produces groups.

   ```bash
   python3 -m sci_search.cli --corpus corpora/goat_foraging research-online \
     --question "What influences goat foraging behaviour and diet selection?" \
     --per-query 10 --max-full-texts 5 --output /tmp/contradictions-goat.json

   python3 -m sci_search.cli --corpus corpora/goat_foraging research-online \
     --question "How does salinity affect tomato seed germination?" \
     --per-query 10 --max-full-texts 5 --output /tmp/contradictions-tomato.json
   ```

2. Read `ai_analysis.contradiction_groups` and `literature_review_report.contradiction_groups` in
   each output, or open the run's dashboard and look at the "Study comparisons" block.
3. For each group, record in the table below:
   - Genuine: do the positions actually disagree (yes/no)?
   - Cause correct: is the stated cause right given the quotes (yes/no/unexplained-but-explainable)?
   - Severity sensible: would you rank it the same (yes/higher/lower)?
4. Also record rejected groups from `ai_analysis.rejected_records` with category
   `contradiction_groups`, and any `validation_notes` downgrades.

| Run | Group ID | Genuine | Cause correct | Severity sensible | Notes |
|---|---|---|---|---|---|

## Decision rule

If more than one third of groups are not genuine disagreements or have the wrong cause, open a
follow-up to implement the separate adjudication pass. Record the outcome and date here.

## OpenAI live check — 2026-09-28

Provider: `openai`. Model: `gpt-4.1-mini`. Both CLI runs completed with
`ai_analysis.status=complete` and method `openai_structured_evidence_analysis_v1`, without an
analysis fallback. These runs used the questions and budgets above.

| Question | Run ID | Evidence passages / publications | Retained claims | Rejected records | Retained / rejected contradiction groups |
|---|---|---|---|---|---|
| Goat foraging | `20260928T083432Z-8481ce42` | 15 / 5 | 1 | 10 | 0 / 0 |
| Tomato germination | `20260928T083845Z-11236d23` | 12 / 4 | 1 | 13 | 0 / 0 |

Both the analysis and literature-review group lists were empty. There are consequently no group
rows, causes, severity assessments, or group downgrades to record. **The grouping-quality decision
is inconclusive:** zero groups do not establish that the single-call approach is good enough or
that a separate adjudication pass is unnecessary.

The source-grounding validator rejected individual records in both runs. The tomato run's proposed
answer was rejected because its quote was outside the selected result statement; the final answer
was derived from the surviving grounded claim about silicon alleviating salinity stress. A complete
analysis status therefore does not mean every generated record passed or the question was fully
answered. These checks establish provider integration, not expert-confirmed scientific quality.

Both runs retained `question_brief=null`: the CLI `research-online` path does not invoke the
interactive question-interpretation step. A separate direct call to `interpret_question` for the
tomato question succeeded at 10:40 Amsterdam time, recording provider `openai`, model
`gpt-4.1-mini`, and method `openai_structured_question_interpretation_v1`.

Full-text adjudication was `not_needed` in both runs, so that model call was not exercised live.
Its retained `mistral_quote_validated_fulltext_adjudication_v1` label is the existing no-call method
identifier, not evidence of a Mistral request. Injected-transport tests cover OpenAI adjudication.

The completed run artifacts were inspected when resuming the interrupted session; the paid runs
were not repeated. Local artifacts are retained under `data/research_runs/<run-id>/`; original CLI
outputs were `openai-goat.json` and `openai-tomato.json` in the session scratchpad. They contain
research data and are not committed.

Verification on 2026-09-28: `python -m pytest -q -p no:cacheprovider --ignore=tests/integration
--ignore=tests/system` passed with 453 tests, 15 skips, and 2 subtests. Integration/system and
opt-in retained-corpus checks were not run. Ruff lint and formatting passed; targeted Pyright
checks reported 0 errors and 22 existing warnings. Independent code review found no blocking
provider-integration issues.
