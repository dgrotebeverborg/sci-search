# Structured contradiction groups

Date: 2026-09-24. Status: design approved in conversation; awaiting written-spec review.

## Product outcome

When studies in a generic research run disagree, the dashboard shows *where* they disagree, *which
studies stand on each side*, *why* they probably disagree (different conditions, population, method,
outcome measure, or unexplained), and *how much it matters* for the answer. Every part of a
contradiction group is grounded in exact source quotes and passes deterministic validation. Apparent
contradictions caused by differing context are distinguished from genuine, unexplained disagreement.

Inspiration: the Evidence Landscape of the Large Knowledge Model (arXiv 2609.27297), which groups
disagreements by members, cause, and severity. Sci-Search keeps its stricter grounding contract:
nothing enters a group that is not quoted verbatim from acquired full text.

## Scope

In scope (v1):

- The generic research path with Mistral analysis enabled.
- A standard-library domain model that the iron-air specialist path can populate later from
  `comparison.compare_pair` without changing the model.
- Deterministic validation, deterministic severity, dashboard, report, export, and local
  scientific-memory persistence.

Out of scope (v1, follow-up projects):

- Researcher review of contradiction groups (confirm/reject/correct cause). Requires a migration,
  API routes, UI, and fingerprint-based revisions following the `evidence_revisions` pattern. The v1
  group ID is already a stable content fingerprint, so review can be added without data migration.
- The specialist producer based on `MeasurementContext`.
- A separate adjudication pass (a second model call per candidate pair). Revisit only if the
  single-call quality check below is inadequate.

Without Mistral, no groups are produced. The deterministic extractive fallback never invents
contradictions.

## Current evidence from the repository

- `mistral_analysis.py` requests `contradictions` as a flat list (max 2) of assertions, validated by
  `_assertion`: known evidence IDs, quotes of at least 12 characters present in the passage and the
  selected statement, and every cited evidence ID quoted. No grouping, sides, cause, or severity.
- `literature_review.py` renders contradictions and method differences as one bullet list under
  "Contradictions, methods, and comparability".
- `study_matrix.py` assigns each study an `inferred_evidence_nature` label (for example
  `laboratory experiment`, `field or observational study`, `simulation or model`, `review`,
  `unclassified`) and per-dimension coverage.
- `comparison.py` compares `MeasurementResult` context only for specialist metrics in
  `energy.METRICS`. It is not available to the generic path.
- `scientific_memory.py` stores validated model claims as `ScientificClaim` nodes with
  `SUPPORTED_BY` edges.
- `frontend/static/dashboard.js` renders a `comparisons` block in the literature view.

## Domain model

New module `sci_search/domain/contradictions.py` (standard library only, like `risk_of_bias.py`):

```python
class ContradictionCause(StrEnum):
    DIFFERENT_CONDITIONS = "different_conditions"
    DIFFERENT_POPULATION = "different_population"
    DIFFERENT_METHOD = "different_method"
    DIFFERENT_OUTCOME_MEASURE = "different_outcome_measure"
    UNEXPLAINED = "unexplained"


class Severity(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class GroundedQuote:
    evidence_id: str
    quote: str


@dataclass(frozen=True, slots=True)
class ContradictionPosition:
    stance: str                            # at most 300 characters
    evidence_ids: tuple[str, ...]
    quotes: tuple[GroundedQuote, ...]
    publication_ids: tuple[str, ...]       # derived from evidence records, never model output


@dataclass(frozen=True, slots=True)
class ContradictionGroup:
    id: str
    topic: str
    positions: tuple[ContradictionPosition, ...]   # 2 or 3
    cause: ContradictionCause
    cause_explanation: GroundedAssertion | None    # None only when cause is UNEXPLAINED
    severity: Severity
    severity_basis: tuple[str, ...]
    severity_rules_version: str
    dimension_ids: tuple[str, ...]                 # derived from the study matrix
    status: str = "model_proposed_source_verified"
    validation_notes: tuple[str, ...] = ()
```

`GroundedAssertion` holds text, evidence IDs, and quotes, matching the validated assertion dict.
Constructors validate invariants (2–3 positions, non-empty text, explanation present unless
unexplained) and raise `ValueError`.

Group ID: `"contradiction:" + sha256(topic_normalized + "\x1f" + "|".join(sorted(
",".join(sorted(position.evidence_ids)) for position in positions)))[:20]`. The ID does not depend
on position or evidence order.

`status` is explicitly not expert confirmation. It corresponds to `silver_source_verified` for
extractive records.

## Model schema change

In `mistral_analysis.py`:

- Add the required field `contradiction_groups`: an array with at most 3 items. Each item has
  `topic` (at most 200 characters), `positions` (2–3 items, each with `stance`, `evidence_ids`
  (max 3), and `quotes` (max 3)), `cause` (a JSON-schema enum of the five causes), and an optional
  `cause_explanation` (`$ref: #/$defs/assertion`).
- Keep `contradictions` for compatibility. The prompt restricts it to isolated apparent
  contradictions that do not fit a group.
- The prompt instructs the model to prefer a context cause when quotes show differing conditions,
  populations, methods, or outcome measures, and to use `unexplained` only when no such difference
  is quotable.
- Bump `schema_version` to `scientific_analysis_v2`. Consumers treat a missing
  `contradiction_groups` field (v1 payloads and saved dashboards) as "no groups known", not as
  "no contradictions".
- `unavailable_analysis` returns `contradiction_groups: []`.
- Bump the `analysis_contract` string in the analysis fingerprint (`research_runs.py`, currently
  `scientific_analysis_v4_feedback_lifecycle`) to `scientific_analysis_v5_contradiction_groups`, so
  cached analyses without groups are not reused.

## Validation

`validate_contradiction_groups(raw_groups, evidence_by_id, study_matrix)` runs after model output
and before any group reaches a report, dashboard, or memory. Each group is checked in this order.
Any failure rejects the entire group, and the reason is appended to `rejected_records` with
category `contradiction_groups`. Groups are never partially repaired, with one exception (rule 5).

1. Each position passes the existing `_assertion` checks (using `stance` as text).
2. At least two valid positions remain.
3. Positions are disjoint: no evidence ID and no publication ID appears in two positions. A study
   cannot disagree with itself, so intra-study variation is not presented as cross-study conflict.
4. If the cause is not `unexplained`, `cause_explanation` must pass `_assertion` and must quote
   evidence from at least two different positions.
5. If rule 4 fails, the group is downgraded to `unexplained` with no explanation, and a note is
   added to `validation_notes`. The disagreement itself is grounded; only its explanation is not.
   This is the only permitted repair.
6. `publication_ids` and `dimension_ids` are derived from the evidence records and the study matrix.
   Model-supplied values for these fields are ignored.

After validation, severity is computed (next section) and groups are sorted by severity (high to
low), then publication count (descending), then ID.

## Severity rules

Pure function `assess_severity(group, *, answer_evidence_ids, evidence_nature_by_publication)`
returns `(Severity, basis)`. `SEVERITY_RULES_VERSION = "contradiction_severity_v1"`.

1. Base by cause:

   | Cause | Base | Basis text |
   |---|---|---|
   | `different_conditions`, `different_population`, `different_outcome_measure` | low | Apparent contradiction explained by differing context |
   | `different_method` | moderate | Differing methods; which method is appropriate is unresolved |
   | `unexplained` | high | No grounded explanation for the disagreement |

2. Answer impact (+1): any group evidence ID appears in `answer.evidence_ids` or in a validated
   `claims` or `agreements` assertion.
3. Imbalance (−1): the weakest position consists of one publication whose evidence nature is
   `simulation or model`, `review`, `systematic review`, `literature review`, or `unclassified`,
   while another position has at least two publications with primary empirical evidence
   (`laboratory experiment`, `field or observational study`, `field study`, `observational`).
   The exact label sets are constants in the domain module and are covered by tests.
4. Clamp to low…high.

Each applied step adds one basis string.

Answer consequence: if any high-severity group satisfies rule 2, set `contested = true` on the
run's `answer_adequacy` (from `coverage.assess_answer_adequacy`), after analysis completes. Adequacy
is computed before analysis and is an input to the analysis fingerprint, so this flag is added
afterwards and never feeds back into that fingerprint. Also add the qualification "Studies disagree
on <topic>; see the contradiction group." with a link to the group ID. A contradiction never
withholds an answer.

## Persistence

- Run artifact and dashboard payload: `analysis.contradiction_groups` is serialized with the rest
  of the analysis, so it flows into PostgreSQL-backed saved dashboards and ZIP exports with no new
  table.
- Local scientific memory (`scientific_memory.py`): each validated group becomes a
  `ContradictionGroup` node (canonical key = group ID) with edges `run:<id> PRODUCED_CONTRADICTION
  group` and `group POSITION_SUPPORTED_BY evidence` with properties `{position: i}`. The rules for
  persisting validated claims apply.

## Presentation

Dashboard (`dashboard.py`, `frontend/static/dashboard.js`, comparisons block):

- New subsection "Where studies disagree" at the top of the comparisons block, in sorted order.
- Each group shows the topic, a severity label (text and color, never color alone), a cause label,
  and the positions side by side on wide screens and stacked on narrow screens. Each position shows
  its stance, quotes, and links to evidence passages and publications.
- The cause explanation is shown with its quotes, or "No grounded explanation found" for
  `unexplained`.
- An expandable detail shows `severity_basis`, the rules version, validation notes, and the label
  "Model-proposed, source-verified — not expert-confirmed".
- The answer block shows the contested qualification with a link to the group.
- Payloads without `contradiction_groups` omit the subsection entirely (no empty-state claim).

Report (`literature_review.py`): the "Contradictions, methods, and comparability" section lists
groups first (topic, severity, cause, stance per position with citations), then the existing
isolated contradiction and method-difference items.

## Testing

Unit tests (no network):

- Validation, one test per rule: fabricated quote; publication in two positions; only one valid
  position; explanation quoting only one position (downgrade to `unexplained` with note); unknown
  evidence ID; model-supplied publication IDs ignored.
- Severity: a table test over cause × answer impact × imbalance, including clamping at both ends.
- Group ID stable under reordering of positions and evidence IDs.
- Domain constructor invariants.

Integration tests:

- A generic pipeline run with a stubbed Mistral completion produces groups in the analysis,
  literature review, dashboard payload, and memory graph.
- A v1 payload without the field renders a dashboard and report without error and without the
  subsection.
- The dashboard API route returns groups for a completed run.

Browser test (existing Playwright suite): the subsection renders positions and severity, and the
answer block links to a contested group.

Quality check (manual, not in CI, recorded under `docs/operations/`): on the goat-foraging corpus
and one new question, a researcher records for each group whether the positions genuinely disagree
and whether the cause is correct. If more than a third of groups are wrong, reconsider the separate
adjudication pass.

## Compatibility and rollback

No database migration. Rolling back the code leaves stored v2 analyses containing an extra field
that older code ignores. Saved v1 dashboards remain readable by the new code.
