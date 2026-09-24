# Contradiction groups: researcher quality check

Purpose: decide whether single-call contradiction grouping is good enough, or whether the separate
adjudication pass described in the
[design spec](../superpowers/specs/2026-09-24-contradiction-groups-design.md) is needed. This
check is manual and not part of CI.

## Procedure

1. With `OPENALEX_API_KEY` and `MISTRAL_API_KEY` configured, run two online research questions.
   The local `investigate` command does not call Mistral, so it never produces groups.

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
