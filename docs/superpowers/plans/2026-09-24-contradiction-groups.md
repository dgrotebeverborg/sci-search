# Structured Contradiction Groups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show researchers where studies disagree, which studies stand on each side, why they probably differ, and how much it matters. Every part is grounded in exact source quotes.

**Architecture:** Mistral proposes `contradiction_groups` in the existing single analysis call. `mistral_analysis.validate_analysis` validates them deterministically: each position is a normal grounded assertion, positions are disjoint by evidence and publication, and an ungrounded cause explanation downgrades the group to `unexplained`. `literature_review.build_literature_review` then computes severity with the pure rules in `sci_search/domain/contradictions.py`, using the study matrix and the answer's evidence. The dashboard, Markdown report, and local scientific memory read those results.

**Tech Stack:** Python 3.11 standard library, pytest, vanilla ES modules in `sci_search/frontend/static`, Playwright browser tests.

**Spec:** `docs/superpowers/specs/2026-09-24-contradiction-groups-design.md`

## Global Constraints

- The domain module imports only the Python standard library.
- Nothing enters a group unless it is quoted verbatim from a supplied evidence passage. Model-supplied `publication_ids` and `dimension_ids` are ignored and always derived.
- Group status string: `model_proposed_source_verified`. UI label: "Model-proposed, source-verified — not expert-confirmed".
- `SEVERITY_RULES_VERSION = "contradiction_severity_v1"`.
- Analysis `schema_version` becomes `scientific_analysis_v2`. `PROMPT_CONTRACT_VERSION` becomes `scientific_analysis_prompt_v3`. The analysis fingerprint contract becomes `scientific_analysis_v5_contradiction_groups`.
- Primary empirical evidence-nature labels are exactly `laboratory experiment` and `field or observational study`.
- A contradiction never withholds an answer.
- Payloads without `contradiction_groups` (v1) must render without the "Where studies disagree" subsection and without errors.
- Severity is shown as text, never only as color.
- No database migration.
- Run commands from the repo root with the venv active: `source .venv/bin/activate`.
- The branch has unrelated uncommitted work. Every commit stages only the files named in its task (`git add <paths>` and `git commit -- <paths>`). Never use `git add -A` or `git commit -a`.
- Commit messages end with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Prerequisite

At plan time, `sci_search/dashboard.py`, `sci_search/frontend/static/dashboard.js`,
`tests/test_dashboard.py`, and `tests/browser/test_saved_dashboards.py` are **untracked**. They
belong to the uncommitted saved-dashboards work on this branch. `app.css`, `research_runs.py`, and
`scientific_memory.py` have uncommitted modifications. Before Task 1, the owner commits the
saved-dashboards work (their decision how). Otherwise Tasks 4–5 cannot commit only their own
changes. Confirm with `git status --porcelain` that none of the files above show `??` before
starting.

## Review Focus

- The model omits `contradiction_groups` or returns `null`. All other validated categories must survive, with groups = `[]`. Test in Task 2.
- The model returns the same group twice, or two groups with identical position evidence. Only one group with that ID is kept. Test in Task 2.
- A researcher excludes a paper and the review is rebuilt. Groups that cite evidence no longer present in `evidence` must disappear from the report, not render with dead links. Test in Task 3.
- A coverage-limited run (`answer` withheld, `status: coverage_limited`). Groups still render, and `touches_answer` comes only from main claims and agreements. Test in Task 3.
- A topic or stance containing HTML (`<img src=x onerror=...>`). It must render as literal text. Test in Task 5.

## File Structure

- Create `sci_search/domain/contradictions.py`: causes, severity enum, constants, group ID, severity rules. Pure.
- Modify `sci_search/mistral_analysis.py`: schema, prompt, `_assertion` option, `validate_contradiction_groups`, `validate_analysis`, `unavailable_analysis`, and the version string.
- Modify `sci_search/application/analysis.py`: `SCHEMA_VERSION` and `PROMPT_CONTRACT_VERSION`.
- Modify `sci_search/research_runs.py:1389`: the fingerprint contract string.
- Modify `sci_search/literature_review.py`: the assessment helper, the report keys `contradiction_groups` and `answer_contest`, and the Markdown section.
- Modify `sci_search/dashboard.py`: pass the groups and the contest to the `comparisons` and `answer` blocks.
- Modify `sci_search/frontend/static/dashboard.js` and `app.css`: rendering.
- Modify `sci_search/scientific_memory.py`: graph nodes and edges.
- Create `docs/operations/contradiction-groups-quality-check.md`: the manual quality protocol.
- Tests: `tests/domain/test_contradictions.py`, `tests/application/test_contradiction_validation.py`, `tests/test_contradiction_review.py`, `tests/test_dashboard.py`, `tests/browser/test_saved_dashboards.py`, `tests/test_memory_ai.py`, `tests/application/test_analysis_provider.py`.

---

### Task 1: Domain rules

**Files:**
- Create: `sci_search/domain/contradictions.py`
- Test: `tests/domain/test_contradictions.py`

**Interfaces:**
- Produces:
  - `ContradictionCause(StrEnum)` with the values `different_conditions`, `different_population`, `different_method`, `different_outcome_measure`, `unexplained`
  - `Severity(StrEnum)` with the values `low`, `moderate`, `high`
  - `SEVERITY_RULES_VERSION: str`
  - `GROUP_STATUS: str`
  - `PRIMARY_EMPIRICAL_NATURES: frozenset[str]`
  - `contradiction_group_id(topic: str, positions: Sequence[Iterable[str]]) -> str`
  - `assess_severity(cause: str | ContradictionCause, position_publication_ids: Sequence[Sequence[str]], *, touches_answer: bool, evidence_nature_by_publication: Mapping[str, str]) -> tuple[Severity, tuple[str, ...]]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/domain/test_contradictions.py
from __future__ import annotations

import pytest

from sci_search.domain.contradictions import (
    ContradictionCause,
    Severity,
    assess_severity,
    contradiction_group_id,
)

LAB = "laboratory experiment"
FIELD = "field or observational study"
MODEL = "simulation or model"


def test_group_id_is_independent_of_order_and_whitespace() -> None:
    first = contradiction_group_id("Salinity  effect", [["e2", "e1"], ["e3"]])
    second = contradiction_group_id("salinity effect", [["e3"], ["e1", "e2"]])
    assert first == second
    assert first.startswith("contradiction:")
    assert len(first) == len("contradiction:") + 20


def test_group_id_changes_with_membership() -> None:
    assert contradiction_group_id("t", [["e1"], ["e2"]]) != contradiction_group_id(
        "t", [["e1"], ["e3"]]
    )


@pytest.mark.parametrize(
    ("cause", "touches", "expected"),
    [
        ("different_conditions", False, Severity.LOW),
        ("different_population", False, Severity.LOW),
        ("different_outcome_measure", False, Severity.LOW),
        ("different_method", False, Severity.MODERATE),
        ("unexplained", False, Severity.HIGH),
        ("different_conditions", True, Severity.MODERATE),
        ("different_method", True, Severity.HIGH),
        ("unexplained", True, Severity.HIGH),
    ],
)
def test_base_and_answer_impact(cause: str, touches: bool, expected: Severity) -> None:
    severity, basis = assess_severity(
        cause,
        [["p1"], ["p2"]],
        touches_answer=touches,
        evidence_nature_by_publication={"p1": LAB, "p2": LAB},
    )
    assert severity is expected
    assert basis
    assert any("answer" in item for item in basis) is touches


def test_imbalance_lowers_and_clamps_at_low() -> None:
    natures = {"p1": MODEL, "p2": LAB, "p3": FIELD}
    severity, basis = assess_severity(
        ContradictionCause.DIFFERENT_CONDITIONS,
        [["p1"], ["p2", "p3"]],
        touches_answer=False,
        evidence_nature_by_publication=natures,
    )
    assert severity is Severity.LOW
    assert any(item.startswith("Lowered") for item in basis)


def test_imbalance_lowers_unexplained_to_moderate() -> None:
    natures = {"p1": "review", "p2": LAB, "p3": LAB}
    severity, _ = assess_severity(
        "unexplained",
        [["p1"], ["p2", "p3"]],
        touches_answer=False,
        evidence_nature_by_publication=natures,
    )
    assert severity is Severity.MODERATE


def test_missing_study_card_counts_as_not_primary() -> None:
    severity, _ = assess_severity(
        "unexplained",
        [["unknown"], ["p2", "p3"]],
        touches_answer=False,
        evidence_nature_by_publication={"p2": LAB, "p3": FIELD},
    )
    assert severity is Severity.MODERATE


def test_no_imbalance_when_weak_side_has_no_strong_counterpart() -> None:
    severity, _ = assess_severity(
        "unexplained",
        [["p1"], ["p2"]],
        touches_answer=False,
        evidence_nature_by_publication={"p1": MODEL, "p2": LAB},
    )
    assert severity is Severity.HIGH


def test_unknown_cause_is_rejected() -> None:
    with pytest.raises(ValueError):
        assess_severity(
            "bad_cause", [["p1"], ["p2"]], touches_answer=False, evidence_nature_by_publication={}
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/domain/test_contradictions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sci_search.domain.contradictions'`

- [ ] **Step 3: Implement**

```python
# sci_search/domain/contradictions.py
"""Deterministic identity and severity for model-proposed contradiction groups."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum

SEVERITY_RULES_VERSION = "contradiction_severity_v1"
GROUP_STATUS = "model_proposed_source_verified"
PRIMARY_EMPIRICAL_NATURES = frozenset({"laboratory experiment", "field or observational study"})


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


_ORDER = (Severity.LOW, Severity.MODERATE, Severity.HIGH)
_CONTEXT = "Apparent contradiction explained by differing context"
_BASE = {
    ContradictionCause.DIFFERENT_CONDITIONS: (Severity.LOW, _CONTEXT),
    ContradictionCause.DIFFERENT_POPULATION: (Severity.LOW, _CONTEXT),
    ContradictionCause.DIFFERENT_OUTCOME_MEASURE: (Severity.LOW, _CONTEXT),
    ContradictionCause.DIFFERENT_METHOD: (
        Severity.MODERATE,
        "Differing methods; which method is appropriate is unresolved",
    ),
    ContradictionCause.UNEXPLAINED: (
        Severity.HIGH,
        "No grounded explanation for the disagreement",
    ),
}


def contradiction_group_id(topic: str, positions: Sequence[Iterable[str]]) -> str:
    normalized = " ".join(topic.casefold().split())
    members = sorted(",".join(sorted(set(ids))) for ids in positions)
    digest = hashlib.sha256(f"{normalized}\x1f{'|'.join(members)}".encode()).hexdigest()
    return f"contradiction:{digest[:20]}"


def assess_severity(
    cause: str | ContradictionCause,
    position_publication_ids: Sequence[Sequence[str]],
    *,
    touches_answer: bool,
    evidence_nature_by_publication: Mapping[str, str],
) -> tuple[Severity, tuple[str, ...]]:
    base, reason = _BASE[ContradictionCause(cause)]
    level = _ORDER.index(base)
    basis = [reason]
    if touches_answer:
        level += 1
        basis.append("Raised: the contested evidence supports the answer or a main finding")
    if _imbalanced(position_publication_ids, evidence_nature_by_publication):
        level -= 1
        basis.append(
            "Lowered: one side rests on a single non-empirical study while another side "
            "has at least two primary empirical studies"
        )
    return _ORDER[max(0, min(level, len(_ORDER) - 1))], tuple(basis)


def _imbalanced(
    positions: Sequence[Sequence[str]], natures: Mapping[str, str]
) -> bool:
    def primary(publication_id: str) -> bool:
        return natures.get(publication_id, "unclassified") in PRIMARY_EMPIRICAL_NATURES

    weak = any(len(ids) == 1 and not primary(ids[0]) for ids in positions)
    strong = any(sum(primary(item) for item in ids) >= 2 for ids in positions)
    return weak and strong
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/domain/test_contradictions.py -v && ruff check sci_search/domain/contradictions.py tests/domain/test_contradictions.py && ruff format --check sci_search/domain/contradictions.py tests/domain/test_contradictions.py`
Expected: all PASS, no ruff findings. If the format check fails, run `ruff format` on the two files.

- [ ] **Step 5: Commit**

```bash
git add sci_search/domain/contradictions.py tests/domain/test_contradictions.py
git commit -m "Add contradiction group identity and severity rules

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- sci_search/domain/contradictions.py tests/domain/test_contradictions.py
```

---

### Task 2: Model schema and grounded validation

**Files:**
- Modify: `sci_search/mistral_analysis.py` (schema at lines 21–80, `validate_analysis` at 281, `unavailable_analysis` at 347, `_assertion` at 407, `_system_prompt` at 613, version string at 217)
- Modify: `sci_search/application/analysis.py:15-17`
- Modify: `sci_search/research_runs.py:1389`
- Modify: `tests/application/test_analysis_provider.py:74`
- Test: `tests/application/test_contradiction_validation.py`

**Interfaces:**
- Consumes: `ContradictionCause`, `GROUP_STATUS`, `contradiction_group_id` from Task 1.
- Produces:
  - `validate_contradiction_groups(values: Any, evidence: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]` (groups, rejections)
  - `validate_analysis(...)` output gains the key `"contradiction_groups"`
  - `unavailable_analysis(...)` output gains `"contradiction_groups": []`
  - The validated group dict shape is specified in the spec's "Domain model" section: keys `id`, `topic`, `cause`, `positions[{stance, evidence_ids, quotes, publication_ids}]`, `cause_explanation`, `status`, `validation_notes`

- [ ] **Step 1: Write the failing tests**

```python
# tests/application/test_contradiction_validation.py
from __future__ import annotations

from typing import Any

from sci_search.mistral_analysis import (
    ANALYSIS_SCHEMA,
    unavailable_analysis,
    validate_analysis,
    validate_contradiction_groups,
)

LOW_SALT = "Germination fell to 40% at 150 mM NaCl in growth chambers."
HIGH_SALT = "Germination was unaffected at 150 mM NaCl in field plots."
THIRD = "Germination declined sharply under saline irrigation."
LOW_PASSAGE = f"Seeds were incubated at 25 °C. {LOW_SALT}"
HIGH_PASSAGE = f"Seeds were sown under field temperatures. {HIGH_SALT}"


def _evidence() -> dict[str, dict[str, Any]]:
    return {
        "e1": {"id": "e1", "publication_id": "p1", "statement": LOW_SALT, "passage": LOW_PASSAGE},
        "e2": {"id": "e2", "publication_id": "p2", "statement": HIGH_SALT, "passage": HIGH_PASSAGE},
        "e3": {"id": "e3", "publication_id": "p1", "statement": THIRD, "passage": THIRD},
    }


def _position(evidence_id: str, quote: str, stance: str = "A stance") -> dict[str, Any]:
    return {
        "text": stance,
        "evidence_ids": [evidence_id],
        "quotes": [{"evidence_id": evidence_id, "quote": quote}],
    }


def _group(**overrides: Any) -> dict[str, Any]:
    group: dict[str, Any] = {
        "topic": "Salinity effect on germination",
        "positions": [
            _position("e1", LOW_SALT, "Salinity reduces germination"),
            _position("e2", HIGH_SALT, "Salinity does not reduce germination"),
        ],
        "cause": "different_conditions",
        "cause_explanation": {
            "text": "One study used growth chambers, the other field plots.",
            "evidence_ids": ["e1", "e2"],
            "quotes": [
                {"evidence_id": "e1", "quote": "Seeds were incubated at 25 °C."},
                {"evidence_id": "e2", "quote": "Seeds were sown under field temperatures."},
            ],
        },
    }
    group.update(overrides)
    return group


def test_valid_group_is_kept_with_derived_publications() -> None:
    groups, rejected = validate_contradiction_groups([_group()], _evidence())
    assert rejected == []
    [group] = groups
    assert group["id"].startswith("contradiction:")
    assert group["cause"] == "different_conditions"
    assert group["status"] == "model_proposed_source_verified"
    assert [p["publication_ids"] for p in group["positions"]] == [["p1"], ["p2"]]
    assert group["positions"][0]["stance"] == "Salinity reduces germination"
    assert group["cause_explanation"]["evidence_ids"] == ["e1", "e2"]
    assert group["validation_notes"] == []


def test_model_supplied_publication_ids_are_ignored() -> None:
    position = _position("e1", LOW_SALT)
    position["publication_ids"] = ["forged"]
    groups, _ = validate_contradiction_groups(
        [_group(positions=[position, _position("e2", HIGH_SALT)])], _evidence()
    )
    assert groups[0]["positions"][0]["publication_ids"] == ["p1"]


def test_fabricated_quote_rejects_group() -> None:
    bad = _position("e1", "Germination fell to 10% at 150 mM NaCl.")
    groups, rejected = validate_contradiction_groups(
        [_group(positions=[bad, _position("e2", HIGH_SALT)])], _evidence()
    )
    assert groups == []
    assert rejected[0]["category"] == "contradiction_groups"


def test_one_invalid_position_rejects_three_position_group() -> None:
    bad = _position("e999", HIGH_SALT)
    groups, rejected = validate_contradiction_groups(
        [
            _group(
                positions=[_position("e1", LOW_SALT), _position("e2", HIGH_SALT), bad]
            )
        ],
        _evidence(),
    )
    assert groups == []
    assert "unknown evidence" in rejected[0]["reason"]


def test_single_position_rejects_group() -> None:
    groups, rejected = validate_contradiction_groups(
        [_group(positions=[_position("e1", LOW_SALT)])], _evidence()
    )
    assert groups == []
    assert "two positions" in rejected[0]["reason"]


def test_same_publication_on_two_sides_rejects_group() -> None:
    groups, rejected = validate_contradiction_groups(
        [_group(positions=[_position("e1", LOW_SALT), _position("e3", THIRD)])], _evidence()
    )
    assert groups == []
    assert "must not share" in rejected[0]["reason"]


def test_missing_publication_id_rejects_group() -> None:
    evidence = _evidence()
    evidence["e2"]["publication_id"] = None
    groups, rejected = validate_contradiction_groups([_group()], evidence)
    assert groups == []
    assert "publication" in rejected[0]["reason"]


def test_explanation_quoting_one_side_downgrades_to_unexplained() -> None:
    explanation = {
        "text": "Only chamber conditions are described.",
        "evidence_ids": ["e1"],
        "quotes": [{"evidence_id": "e1", "quote": "Seeds were incubated at 25 °C."}],
    }
    groups, rejected = validate_contradiction_groups(
        [_group(cause_explanation=explanation)], _evidence()
    )
    assert rejected == []
    [group] = groups
    assert group["cause"] == "unexplained"
    assert group["cause_explanation"] is None
    assert "two positions" in group["validation_notes"][0]


def test_missing_explanation_downgrades_to_unexplained() -> None:
    group = _group()
    del group["cause_explanation"]
    groups, _ = validate_contradiction_groups([group], _evidence())
    assert groups[0]["cause"] == "unexplained"


def test_unexplained_cause_ignores_explanation() -> None:
    groups, _ = validate_contradiction_groups([_group(cause="unexplained")], _evidence())
    assert groups[0]["cause_explanation"] is None
    assert groups[0]["validation_notes"] == []


def test_unknown_cause_rejects_group() -> None:
    groups, rejected = validate_contradiction_groups([_group(cause="weather")], _evidence())
    assert groups == []
    assert "cause" in rejected[0]["reason"]


def test_duplicate_groups_are_kept_once() -> None:
    groups, _ = validate_contradiction_groups([_group(), _group()], _evidence())
    assert len(groups) == 1


def test_non_list_is_treated_as_empty() -> None:
    assert validate_contradiction_groups(None, _evidence()) == ([], [])


def test_validate_analysis_survives_missing_groups_field() -> None:
    claim = _position("e1", LOW_SALT, "Salinity reduced germination in chambers.")
    payload = {
        "answer": claim,
        "claims": [claim],
        "agreements": [],
        "contradictions": [],
        "method_differences": [],
        "limitations": [],
        "uncertainties": [],
        "assumptions": [],
        "knowledge_gaps": [],
        "entities": [],
        "measurements": [],
    }
    evidence = list(_evidence().values())
    result = validate_analysis(payload, evidence)
    assert result["contradiction_groups"] == []
    assert result["answer"]["evidence_ids"] == ["e1"]
    payload["contradiction_groups"] = [_group()]
    assert len(validate_analysis(payload, evidence)["contradiction_groups"]) == 1


def test_schema_and_fallback_declare_groups() -> None:
    assert "contradiction_groups" in ANALYSIS_SCHEMA["required"]
    cause = ANALYSIS_SCHEMA["$defs"]["contradiction_group"]["properties"]["cause"]
    assert set(cause["enum"]) == {
        "different_conditions",
        "different_population",
        "different_method",
        "different_outcome_measure",
        "unexplained",
    }
    assert unavailable_analysis("x")["contradiction_groups"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/application/test_contradiction_validation.py -v`
Expected: FAIL with `ImportError: cannot import name 'validate_contradiction_groups'`

- [ ] **Step 3: Add the import and extend the schema**

At the top of `sci_search/mistral_analysis.py`, after the `EvidencePacket` import:

```python
from sci_search.domain.contradictions import (
    GROUP_STATUS,
    ContradictionCause,
    contradiction_group_id,
)
```

In `ANALYSIS_SCHEMA`, append `"contradiction_groups"` to the `"required"` list. Add this entry to `"properties"`, after `"knowledge_gaps"`:

```python
        "contradiction_groups": {
            "type": "array",
            "maxItems": 3,
            "items": {"$ref": "#/$defs/contradiction_group"},
        },
```

Add this entry to `"$defs"`, next to `"assertion"`:

```python
        "contradiction_group": {
            "type": "object",
            "required": ["topic", "positions", "cause"],
            "additionalProperties": False,
            "properties": {
                "topic": {"type": "string", "maxLength": 200},
                "positions": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 3,
                    "items": {"$ref": "#/$defs/assertion"},
                },
                "cause": {"type": "string", "enum": [item.value for item in ContradictionCause]},
                "cause_explanation": {"$ref": "#/$defs/assertion"},
            },
        },
```

- [ ] **Step 4: Let `_assertion` accept quotes outside the selected statement**

Change the signature and the statement check in `_assertion` (line 407). The existing behavior stays the default:

```python
def _assertion(
    value: Any,
    evidence: dict[str, dict[str, Any]],
    category: str,
    *,
    require_statement: bool = True,
) -> dict[str, Any]:
```

```python
        if require_statement and source_quote not in selected_statement:
            raise ValueError(f"{category} quote is outside the selected result statement")
```

- [ ] **Step 5: Add group validation**

Add these functions directly after `_assertion`:

```python
def validate_contradiction_groups(
    values: Any, evidence: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(values[:3] if isinstance(values, list) else []):
        try:
            group = _contradiction_group(item, evidence)
        except ValueError as exc:
            rejected.append(
                {"category": "contradiction_groups", "index": index, "reason": str(exc)}
            )
            continue
        if group["id"] not in seen:
            seen.add(group["id"])
            groups.append(group)
    return groups, rejected


def _contradiction_group(value: Any, evidence: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("contradiction group must be an object")
    topic = " ".join(str(value.get("topic") or "").split())
    if not topic:
        raise ValueError("contradiction group requires a topic")
    try:
        cause = ContradictionCause(str(value.get("cause") or ""))
    except ValueError:
        raise ValueError("contradiction group has an unknown cause") from None
    raw_positions = value.get("positions")
    if not isinstance(raw_positions, list) or len(raw_positions) < 2:
        raise ValueError("contradiction group requires at least two positions")
    positions: list[dict[str, Any]] = []
    seen_evidence: set[str] = set()
    seen_publications: set[str] = set()
    for raw in raw_positions[:3]:
        position = _assertion(raw, evidence, "contradiction position")
        publications = [
            str(evidence[item].get("publication_id") or "") for item in position["evidence_ids"]
        ]
        if not all(publications):
            raise ValueError("contradiction position evidence lacks a publication")
        publication_ids = sorted(set(publications))
        if seen_evidence & set(position["evidence_ids"]) or seen_publications & set(
            publication_ids
        ):
            raise ValueError("contradiction positions must not share evidence or publications")
        seen_evidence.update(position["evidence_ids"])
        seen_publications.update(publication_ids)
        positions.append(
            {
                "stance": position["text"],
                "evidence_ids": position["evidence_ids"],
                "quotes": position["quotes"],
                "publication_ids": publication_ids,
            }
        )
    explanation = None
    notes: list[str] = []
    if cause is not ContradictionCause.UNEXPLAINED:
        try:
            explanation = _assertion(
                value.get("cause_explanation"),
                evidence,
                "contradiction explanation",
                require_statement=False,
            )
            quoted = {
                index
                for index, position in enumerate(positions)
                if set(position["evidence_ids"]) & set(explanation["evidence_ids"])
            }
            if len(quoted) < 2:
                raise ValueError("cause explanation must quote at least two positions")
        except ValueError as exc:
            explanation = None
            cause = ContradictionCause.UNEXPLAINED
            notes.append(f"cause downgraded to unexplained: {exc}")
    return {
        "id": contradiction_group_id(topic, [item["evidence_ids"] for item in positions]),
        "topic": topic,
        "cause": cause.value,
        "positions": positions,
        "cause_explanation": explanation,
        "status": GROUP_STATUS,
        "validation_notes": notes,
    }
```

- [ ] **Step 6: Wire the groups into `validate_analysis` and `unavailable_analysis`**

In `validate_analysis`, directly after the loop over assertion categories ends (before `result["claims"] = all_claims`):

```python
    groups, group_rejections = validate_contradiction_groups(
        payload.get("contradiction_groups"), by_id
    )
    result["contradiction_groups"] = groups
    rejected.extend(group_rejections)
```

In `unavailable_analysis`, add `"contradiction_groups": [],` after `"knowledge_gaps": [],`.

- [ ] **Step 7: Update the prompt and the versions**

In `_system_prompt`, insert this sentence before `"Extract entities only when..."`:

```python
        "Group genuine cross-study disagreements in contradiction_groups: each group has a topic, two or three positions "
        "citing different publications (one publication may appear in only one position), and a cause. Prefer "
        "different_conditions, different_population, different_method, or different_outcome_measure when the passages show "
        "such a difference, and support that cause with a cause_explanation quoting at least two positions; the explanation's "
        "quotes may come from anywhere in the passage. Use unexplained only when no such difference is quotable. Use "
        "contradictions only for apparent contradictions that do not fit a group. "
```

In `sci_search/mistral_analysis.py`, replace both occurrences of `"scientific_analysis_v1"` (lines 217 and 352) with `"scientific_analysis_v2"`.

In `sci_search/application/analysis.py`:

```python
PROMPT_CONTRACT_VERSION = "scientific_analysis_prompt_v3"
VALIDATOR_VERSION = "exact_source_grounding_v2"
SCHEMA_VERSION = "scientific_analysis_v2"
```

In `sci_search/research_runs.py:1389`, replace `"scientific_analysis_v4_feedback_lifecycle"` with `"scientific_analysis_v5_contradiction_groups"`.

In `tests/application/test_analysis_provider.py:74`, change the expected value to `"scientific_analysis_v2"`.

- [ ] **Step 8: Run the tests**

Run: `pytest tests/application tests/test_memory_ai.py -v`
Expected: all PASS. The existing `_assertion` tests in `test_memory_ai.py` must still pass, because `require_statement` defaults to `True`.

Run: `grep -rn "scientific_analysis_v1\|scientific_analysis_prompt_v2\|v4_feedback_lifecycle" sci_search tests`
Expected: no output.

- [ ] **Step 9: Lint and commit**

```bash
ruff check sci_search/mistral_analysis.py sci_search/application/analysis.py sci_search/research_runs.py tests/application
ruff format sci_search/mistral_analysis.py tests/application/test_contradiction_validation.py
git add sci_search/mistral_analysis.py sci_search/application/analysis.py sci_search/research_runs.py tests/application/test_contradiction_validation.py tests/application/test_analysis_provider.py
git commit -m "Validate model-proposed contradiction groups against exact sources

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- sci_search/mistral_analysis.py sci_search/application/analysis.py sci_search/research_runs.py tests/application/test_contradiction_validation.py tests/application/test_analysis_provider.py
```

Note: `research_runs.py` and `test_analysis_provider.py` may already contain other uncommitted edits from this branch. Before committing, run `git diff sci_search/research_runs.py tests/application/test_analysis_provider.py`. If the diff contains hunks other than the one-line changes above, stage only your hunk with `git add -p <file>` (answer `y` only for your hunk) and commit without the `-- <paths>` suffix.

---

### Task 3: Severity assessment in the literature review

**Files:**
- Modify: `sci_search/literature_review.py` (the return dict ends around line 347, `render_review_markdown` "Contradictions" section around line 538)
- Test: `tests/test_contradiction_review.py`

**Interfaces:**
- Consumes: `assess_severity`, `SEVERITY_RULES_VERSION` from Task 1. The validated group dicts from Task 2, found at `investigation["ai_analysis"]["contradiction_groups"]`.
- Produces: `build_literature_review(...)` output gains these keys:
  - `"contradiction_groups": list[dict] | None`. `None` means the analysis has no such field (v1). Each group dict gains `severity`, `severity_basis` (list), `severity_rules_version`, `touches_answer`, `dimension_ids`, and per-position `citations` (list[int]). The list is sorted by severity (high first), then publication count (descending), then id.
  - `"answer_contest": {"contested": bool, "group_ids": list[str], "qualifications": list[str]}`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_contradiction_review.py
from __future__ import annotations

from typing import Any

from sci_search.literature_review import build_literature_review, render_review_markdown


def _group(group_id: str, cause: str, left: list[str], right: list[str]) -> dict[str, Any]:
    def position(ids: list[str]) -> dict[str, Any]:
        return {
            "stance": f"Stance {ids}",
            "evidence_ids": ids,
            "quotes": [{"evidence_id": item, "quote": f"quote {item}"} for item in ids],
            "publication_ids": [f"p{item[1:]}" for item in ids],
        }

    return {
        "id": group_id,
        "topic": f"Topic {group_id}",
        "cause": cause,
        "positions": [position(left), position(right)],
        "cause_explanation": None,
        "status": "model_proposed_source_verified",
        "validation_notes": [],
    }


def _investigation(groups: list[dict[str, Any]] | None, **ai: Any) -> dict[str, Any]:
    evidence = [
        {
            "id": f"e{n}",
            "publication_id": f"p{n}",
            "statement": f"s{n}",
            "passage": f"s{n}",
            "scope_dimension_ids": [f"d{n}"],
        }
        for n in range(1, 5)
    ]
    analysis: dict[str, Any] = {
        "status": "complete",
        "answer": {"text": "Answer", "evidence_ids": ["e1"], "quotes": []},
        "claims": [],
        **ai,
    }
    if groups is not None:
        analysis["contradiction_groups"] = groups
    return {
        "question": "Q",
        "evidence": evidence,
        "research_run": {"active_publication_ids": ["p1", "p2", "p3", "p4"]},
        "ai_analysis": analysis,
        "study_matrix": {
            "studies": [
                {"publication_id": f"p{n}", "inferred_evidence_nature": {"label": "laboratory experiment"}}
                for n in range(1, 5)
            ]
        },
        "answer_adequacy": {"can_answer_overall_question": True},
    }


def test_groups_get_severity_citations_and_order() -> None:
    report = build_literature_review(
        _investigation(
            [
                _group("contradiction:low", "different_conditions", ["e3"], ["e4"]),
                _group("contradiction:high", "unexplained", ["e1"], ["e2"]),
            ]
        )
    )
    groups = report["contradiction_groups"]
    assert [g["id"] for g in groups] == ["contradiction:high", "contradiction:low"]
    high = groups[0]
    assert high["severity"] == "high"
    assert high["touches_answer"] is True
    assert high["severity_rules_version"] == "contradiction_severity_v1"
    assert high["dimension_ids"] == ["d1", "d2"]
    assert high["positions"][0]["citations"] == [1]
    assert groups[1]["severity"] == "low"
    assert groups[1]["touches_answer"] is False


def test_high_group_touching_answer_contests_it() -> None:
    report = build_literature_review(
        _investigation([_group("contradiction:high", "unexplained", ["e1"], ["e2"])])
    )
    contest = report["answer_contest"]
    assert contest["contested"] is True
    assert contest["group_ids"] == ["contradiction:high"]
    assert contest["qualifications"] == [
        "Studies disagree on Topic contradiction:high; see the contradiction group."
    ]


def test_moderate_group_does_not_contest_answer() -> None:
    report = build_literature_review(
        _investigation([_group("contradiction:m", "different_conditions", ["e1"], ["e2"])])
    )
    assert report["contradiction_groups"][0]["severity"] == "moderate"
    assert report["answer_contest"]["contested"] is False


def test_v1_analysis_without_field_yields_none() -> None:
    report = build_literature_review(_investigation(None))
    assert report["contradiction_groups"] is None
    assert report["answer_contest"]["contested"] is False
    assert "Where studies disagree" not in render_review_markdown(report)


def test_group_citing_removed_evidence_is_dropped() -> None:
    investigation = _investigation(
        [_group("contradiction:gone", "unexplained", ["e1"], ["e2"])]
    )
    investigation["evidence"] = [e for e in investigation["evidence"] if e["id"] != "e2"]
    report = build_literature_review(investigation)
    assert report["contradiction_groups"] == []


def test_coverage_limited_run_uses_claims_for_answer_impact() -> None:
    investigation = _investigation(
        [
            _group("contradiction:a", "unexplained", ["e1"], ["e2"]),
            _group("contradiction:b", "different_conditions", ["e3"], ["e4"]),
        ],
        claims=[
            {"text": "Main", "evidence_ids": ["e3"], "quotes": [], "category": "claims"},
        ],
    )
    investigation["ai_analysis"].update(status="coverage_limited", answer=None)
    report = build_literature_review(investigation)
    by_id = {g["id"]: g for g in report["contradiction_groups"]}
    assert by_id["contradiction:a"]["touches_answer"] is False
    assert by_id["contradiction:b"]["touches_answer"] is True


def test_markdown_lists_groups_before_isolated_items() -> None:
    report = build_literature_review(
        _investigation([_group("contradiction:high", "unexplained", ["e1"], ["e2"])])
    )
    markdown = render_review_markdown(report)
    section = markdown[markdown.index("## Contradictions, methods, and comparability") :]
    assert "### Where studies disagree" in section
    assert "**Topic contradiction:high** — severity: high; cause: Unexplained." in section
    assert "  - Stance ['e1'] [1]" in section
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_contradiction_review.py -v`
Expected: FAIL with `KeyError: 'contradiction_groups'`

- [ ] **Step 3: Implement the assessment helper**

Add this import at the top of `sci_search/literature_review.py`:

```python
from sci_search.domain.contradictions import SEVERITY_RULES_VERSION, assess_severity
```

Add these module-level helpers above `_cited`:

```python
_SEVERITY_RANK = {"high": 0, "moderate": 1, "low": 2}


def _assess_contradictions(
    raw: Any,
    evidence_by_id: dict[str, dict[str, Any]],
    study_matrix: dict[str, Any],
    answer_evidence_ids: set[str],
    reference_number: dict[str, int],
) -> list[dict[str, Any]] | None:
    if not isinstance(raw, list):
        return None
    natures = {
        str(card.get("publication_id")): str(
            (card.get("inferred_evidence_nature") or {}).get("label") or "unclassified"
        )
        for card in study_matrix.get("studies", [])
        if isinstance(card, dict)
    }
    assessed: list[dict[str, Any]] = []
    for group in raw:
        if not isinstance(group, dict):
            continue
        positions = [item for item in group.get("positions", []) if isinstance(item, dict)]
        evidence_ids = {str(e) for item in positions for e in item.get("evidence_ids", [])}
        if len(positions) < 2 or not evidence_ids <= set(evidence_by_id):
            continue
        touches = bool(evidence_ids & answer_evidence_ids)
        try:
            severity, basis = assess_severity(
                str(group.get("cause")),
                [[str(p) for p in item.get("publication_ids", [])] for item in positions],
                touches_answer=touches,
                evidence_nature_by_publication=natures,
            )
        except (KeyError, ValueError):
            continue
        assessed.append(
            {
                **group,
                "positions": [
                    {
                        **item,
                        "citations": sorted(
                            {
                                reference_number[str(p)]
                                for p in item.get("publication_ids", [])
                                if str(p) in reference_number
                            }
                        ),
                    }
                    for item in positions
                ],
                "severity": severity.value,
                "severity_basis": list(basis),
                "severity_rules_version": SEVERITY_RULES_VERSION,
                "touches_answer": touches,
                "dimension_ids": sorted(
                    {
                        str(dimension)
                        for e in evidence_ids
                        for dimension in evidence_by_id[e].get("scope_dimension_ids") or []
                    }
                ),
            }
        )
    assessed.sort(
        key=lambda g: (
            _SEVERITY_RANK[g["severity"]],
            -sum(len(item.get("publication_ids", [])) for item in g["positions"]),
            str(g.get("id")),
        )
    )
    return assessed


def _answer_contest(groups: list[dict[str, Any]] | None) -> dict[str, Any]:
    contested = [g for g in groups or [] if g["severity"] == "high" and g["touches_answer"]]
    return {
        "contested": bool(contested),
        "group_ids": [str(g.get("id")) for g in contested],
        "qualifications": [
            f"Studies disagree on {g.get('topic')}; see the contradiction group."
            for g in contested
        ],
    }
```

- [ ] **Step 4: Compute the groups inside `build_literature_review`**

Directly before the final `return {` of `build_literature_review` (after `study_matrix` and `reference_number` are defined), add:

```python
    answer_evidence_ids: set[str] = set()
    if ai_complete:
        answer_evidence_ids.update(
            str(item) for item in (ai.get("answer") or {}).get("evidence_ids", [])
        )
        answer_evidence_ids.update(
            str(evidence_id)
            for item in ai.get("claims", [])
            if isinstance(item, dict) and item.get("category") in {"claims", "agreements"}
            for evidence_id in item.get("evidence_ids", [])
        )
    contradiction_groups = _assess_contradictions(
        ai.get("contradiction_groups") if ai_complete else None,
        evidence_by_id,
        study_matrix,
        answer_evidence_ids,
        reference_number,
    )
```

Add two keys to the returned dict, directly after `"thematic_findings": categories,`:

```python
        "contradiction_groups": contradiction_groups,
        "answer_contest": _answer_contest(contradiction_groups),
```

Note: `ai.get("answer")` is `None` for coverage-limited runs, so `(… or {})` guards it. The claims in `ai["claims"]` carry `category` because `validate_analysis` sets it.

- [ ] **Step 5: Render the groups in Markdown**

In `render_review_markdown`, replace:

```python
    lines += ["## Contradictions, methods, and comparability", ""]
```

with:

```python
    lines += ["## Contradictions, methods, and comparability", ""]
    if report.get("contradiction_groups"):
        lines += ["### Where studies disagree", ""]
        for group in report["contradiction_groups"]:
            lines.append(
                f"- **{group['topic']}** — severity: {group['severity']}; "
                f"cause: {_label(str(group['cause']))}."
            )
            for position in group["positions"]:
                lines.append(
                    "  - "
                    + _cited(
                        {"text": position["stance"], "citations": position.get("citations", [])}
                    )
                )
        lines.append("")
```

- [ ] **Step 6: Run the tests**

Run: `pytest tests/test_contradiction_review.py tests/test_literature_review.py tests/test_generic_reporting.py -v`
Expected: all PASS

- [ ] **Step 7: Lint and commit**

```bash
ruff check sci_search/literature_review.py tests/test_contradiction_review.py
ruff format sci_search/literature_review.py tests/test_contradiction_review.py
git diff --stat sci_search/literature_review.py
git add sci_search/literature_review.py tests/test_contradiction_review.py
git commit -m "Assess contradiction severity in the literature review

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- sci_search/literature_review.py tests/test_contradiction_review.py
```

`literature_review.py` has no pre-existing uncommitted edits on this branch (check: it is absent from `git status` at plan time). If `git diff` shows unrelated hunks anyway, use `git add -p` as described in Task 2.

---

### Task 4: Dashboard payload

**Files:**
- Modify: `sci_search/dashboard.py:61-89`
- Test: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: `report["contradiction_groups"]` and `report["answer_contest"]` from Task 3 (stored as `investigation["literature_review_report"]`).
- Produces: `comparisons` block data key `contradiction_groups` (list or None). `answer` block data key `answer_contest` (dict or None).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_dashboard.py`)

```python
def test_contradiction_groups_and_contest_reach_blocks():
    group = {"id": "contradiction:x", "topic": "T", "severity": "high", "positions": []}
    contest = {"contested": True, "group_ids": ["contradiction:x"], "qualifications": ["q"]}
    dashboard = build_dashboard(
        {
            "question": "Q",
            "literature_review_report": {
                "executive_summary": {"text": "A", "evidence_ids": []},
                "contradiction_groups": [group],
                "answer_contest": contest,
            },
        },
        run_id="r",
        revision=1,
    )
    blocks = {b["id"]: b for b in dashboard["blocks"]}
    assert blocks["comparisons"]["data"]["contradiction_groups"] == [group]
    assert blocks["comparisons"]["status"] == "ready"
    assert blocks["answer"]["data"]["answer_contest"] == contest


def test_v1_review_without_groups_keeps_comparisons_empty():
    dashboard = build_dashboard(
        {"question": "Q", "literature_review_report": {"executive_summary": {"text": "A"}}},
        run_id="r",
        revision=1,
    )
    blocks = {b["id"]: b for b in dashboard["blocks"]}
    assert blocks["comparisons"]["data"]["contradiction_groups"] is None
    assert blocks["comparisons"]["status"] == "empty"
    assert blocks["answer"]["data"]["answer_contest"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_dashboard.py -v`
Expected: the two new tests FAIL with `KeyError: 'contradiction_groups'`

- [ ] **Step 3: Implement**

In `sci_search/dashboard.py`, in the `add("answer", {...})` dict, add after `"synthesis": synthesis,`:

```python
            "answer_contest": review.get("answer_contest"),
```

In the `add("comparisons", {...})` dict, add as the first key:

```python
            "contradiction_groups": review.get("contradiction_groups"),
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_dashboard.py tests/test_dashboard_repository.py tests/test_dashboard_import.py tests/api/test_saved_local_dashboards.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add sci_search/dashboard.py tests/test_dashboard.py
git commit -m "Expose contradiction groups in saved dashboards

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- sci_search/dashboard.py tests/test_dashboard.py
```

---

### Task 5: Dashboard rendering

**Files:**
- Modify: `sci_search/frontend/static/dashboard.js` (helpers near line 94, `answer` branch near line 231, `comparisons` branch near line 260)
- Modify: `sci_search/frontend/static/app.css` (append)
- Test: `tests/browser/test_saved_dashboards.py` (append)

**Interfaces:**
- Consumes: the `comparisons.data.contradiction_groups` and `answer.data.answer_contest` from Task 4. Existing helpers `element`, `fields`, `expandable`, `evidenceLinks`, `label`, `showView`.
- Produces: DOM `section#dashboard-comparisons .contradiction-groups` with one `article.contradiction-group[id="contradiction-<sanitized id>"][data-severity]` per group, and `#dashboard-answer .contest-note a` links.

- [ ] **Step 1: Write the failing browser test** (append to `tests/browser/test_saved_dashboards.py`)

```python
def test_contradiction_groups_render_and_answer_links_to_them(
    live_browser_url: str, chromium_browser: Browser
):
    page = chromium_browser.new_page(viewport={"width": 390, "height": 844})
    hostile = "<img src=x onerror=window.__xss=1>"
    group = {
        "id": "contradiction:abc123",
        "topic": f"Salinity {hostile}",
        "cause": "different_conditions",
        "severity": "high",
        "severity_basis": ["No grounded explanation for the disagreement"],
        "severity_rules_version": "contradiction_severity_v1",
        "touches_answer": True,
        "status": "model_proposed_source_verified",
        "validation_notes": [],
        "cause_explanation": None,
        "positions": [
            {"stance": "Reduces germination", "evidence_ids": ["e1"], "publication_ids": ["p1"],
             "quotes": [{"evidence_id": "e1", "quote": "Germination fell to 40%."}], "citations": [1]},
            {"stance": "No effect", "evidence_ids": ["e2"], "publication_ids": ["p2"],
             "quotes": [{"evidence_id": "e2", "quote": "Germination was unaffected."}], "citations": [2]},
        ],
    }
    snapshot = build_dashboard(
        {
            "question": "Contradiction question",
            "literature_review_report": {
                "executive_summary": {"text": "Qualified answer", "evidence_ids": ["e1"]},
                "contradiction_groups": [group],
                "answer_contest": {
                    "contested": True,
                    "group_ids": [group["id"]],
                    "qualifications": ["Studies disagree on Salinity; see the contradiction group."],
                },
            },
        },
        run_id="A",
        revision=1,
    )
    page.route("**/runs?*", lambda route: route.fulfill(json={"items": [], "next_cursor": None}))
    page.route(
        "**/runs/A/dashboard**",
        lambda route: route.fulfill(json={**snapshot, "role": "owner", "current_revision": 1}),
    )
    page.route("**/runs/A/revisions", lambda route: route.fulfill(json={"items": [{"revision": 1}]}))
    page.request.post(f"{live_browser_url}/auth/development")
    page.goto(f"{live_browser_url}/app?project=development-project&run=A&revision=1")
    expect(page.locator("#dashboard-question")).to_have_text("Contradiction question")
    link = page.locator("#dashboard-answer .contest-note a")
    expect(link).to_have_text("Studies disagree on Salinity; see the contradiction group.")
    link.click()
    card = page.locator("#contradiction-contradiction-abc123")
    expect(card).to_be_visible()
    expect(card).to_have_attribute("data-severity", "high")
    expect(card.locator(".severity-badge")).to_have_text("High severity")
    expect(card.locator("h4")).to_have_text(f"Salinity {hostile}")
    expect(card.locator(".contradiction-position")).to_have_count(2)
    expect(card).to_contain_text("No grounded explanation found.")
    expect(card).to_contain_text("not expert-confirmed")
    assert page.evaluate("window.__xss") is None
    width = page.evaluate("document.documentElement.scrollWidth")
    assert width <= 390


def test_v1_dashboard_has_no_disagreement_section(
    live_browser_url: str, chromium_browser: Browser
):
    page = chromium_browser.new_page()
    snapshot = build_dashboard(
        {
            "question": "Old question",
            "literature_review_report": {"executive_summary": {"text": "A", "evidence_ids": []}},
        },
        run_id="A",
        revision=1,
    )
    page.route("**/runs?*", lambda route: route.fulfill(json={"items": [], "next_cursor": None}))
    page.route(
        "**/runs/A/dashboard**",
        lambda route: route.fulfill(json={**snapshot, "role": "owner", "current_revision": 1}),
    )
    page.route("**/runs/A/revisions", lambda route: route.fulfill(json={"items": [{"revision": 1}]}))
    page.request.post(f"{live_browser_url}/auth/development")
    page.goto(f"{live_browser_url}/app?project=development-project&run=A&revision=1")
    expect(page.locator("#dashboard-question")).to_have_text("Old question")
    expect(page.locator(".contradiction-groups")).to_have_count(0)
    expect(page.locator(".contest-note")).to_have_count(0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/browser/test_saved_dashboards.py -k "contradiction or v1_dashboard" -v`
Expected: `test_contradiction_groups_render...` FAILS (no `.contest-note`). `test_v1_dashboard...` may already pass; that is fine.

- [ ] **Step 3: Add the rendering helpers**

In `dashboard.js`, add directly after the `expandable` function:

```js
const severityText = {high: 'High severity', moderate: 'Moderate severity', low: 'Low severity'};
const contradictionAnchor = (id) => `contradiction-${String(id).replace(/[^a-zA-Z0-9-]/g, '-')}`;
function contradictionGroups(groups, parent) {
  const wrap = element('div', '', 'contradiction-groups');
  wrap.append(element('h3', 'Where studies disagree'));
  for (const group of groups) {
    const article = element('article', '', 'contradiction-group');
    article.id = contradictionAnchor(group.id);
    article.dataset.severity = group.severity || '';
    const header = element('div', '', 'contradiction-header');
    header.append(
      element('h4', group.topic || ''),
      element('span', severityText[group.severity] || label(String(group.severity || 'unknown')), `severity-badge severity-${group.severity}`),
      element('span', label(String(group.cause || 'unexplained')), 'study-chip'),
    );
    article.append(header);
    const sides = element('div', '', 'contradiction-positions');
    for (const position of group.positions || []) {
      const side = element('div', '', 'contradiction-position');
      side.append(element('p', position.stance || '', 'contradiction-stance'));
      for (const quote of position.quotes || []) side.append(element('blockquote', quote.quote || ''));
      side.append(evidenceLinks(position.evidence_ids || []));
      sides.append(side);
    }
    article.append(sides);
    if (group.cause_explanation) {
      const why = element('div', '', 'contradiction-explanation');
      why.append(element('h5', 'Why they may differ'));
      fields(group.cause_explanation, why);
      article.append(why);
    } else article.append(element('p', 'No grounded explanation found.', 'help'));
    article.append(expandable('How this was assessed', {
      status: 'Model-proposed, source-verified — not expert-confirmed',
      severity_basis: group.severity_basis,
      severity_rules_version: group.severity_rules_version,
      validation_notes: group.validation_notes,
    }));
    wrap.append(article);
  }
  parent.append(wrap);
}
function contestNote(contest, parent) {
  if (!contest?.contested) return;
  const note = element('div', '', 'contest-note');
  (contest.qualifications || []).forEach((text, index) => {
    const link = element('a', text);
    const anchor = contradictionAnchor(contest.group_ids?.[index] || '');
    link.href = `#${anchor}`;
    link.addEventListener('click', (event) => {
      event.preventDefault();
      showView('literature');
      document.getElementById(anchor)?.scrollIntoView({block: 'start'});
    });
    note.append(link);
  });
  parent.append(note);
}
```

- [ ] **Step 4: Call the helpers from the block renderer**

In the `answer` branch, directly after `if (adequacy.status) section.append(...)`:

```js
        contestNote(data.answer_contest, section);
```

Replace the start of the `comparisons` branch:

```js
      } else if (block.id === 'comparisons') {
        if (data.contradiction_groups?.length) contradictionGroups(data.contradiction_groups, section);
        if (data.comparison_groups?.length) fields(data.comparison_groups, section);
        else if (!data.contradiction_groups?.length) section.append(element('p', 'The retained evidence does not establish a cross-study comparison.', 'section-intro'));
```

The existing `section.append(expandable('Comparability and measurement details', ...))` line stays unchanged.

- [ ] **Step 5: Add styles** (append to `sci_search/frontend/static/app.css`)

```css
.contradiction-group { border: 1px solid #d8ddd9; border-radius: 8px; padding: .8rem; margin: .8rem 0; }
.contradiction-header { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; }
.contradiction-header h4 { margin: 0; flex: 1 1 100%; overflow-wrap: anywhere; }
.contradiction-positions { display: grid; gap: .8rem; margin-top: .6rem; grid-template-columns: repeat(auto-fit, minmax(min(100%, 16rem), 1fr)); }
.contradiction-position { border-left: 3px solid #9aa9a1; padding-left: .6rem; min-width: 0; overflow-wrap: anywhere; }
.contradiction-position blockquote { margin: .4rem 0; font-style: italic; }
.severity-badge { font-size: .75rem; font-weight: 700; padding: .15rem .55rem; border-radius: 20px; }
.severity-high { background: #fbe4e1; color: #8a1c10; }
.severity-moderate { background: #fdf0d5; color: #7a4b00; }
.severity-low { background: #ecf1ee; color: #395949; }
.contest-note { margin: .6rem 0; padding: .5rem .7rem; border-left: 3px solid #8a1c10; background: #fdf4f2; }
.contest-note a { display: block; }
```

- [ ] **Step 6: Run the tests**

Run: `pytest tests/browser/test_saved_dashboards.py -v`
Expected: all PASS. The 13-block count in `test_saved_dashboard_history_refresh_and_feedback` is unchanged because no block is added.

- [ ] **Step 7: Commit**

`app.css` and `dashboard.js` may contain unrelated uncommitted edits (`app.css` does at plan time). Run `git diff sci_search/frontend/static/app.css sci_search/frontend/static/dashboard.js`. If there are hunks other than yours, stage only yours with `git add -p`. Then:

```bash
git add tests/browser/test_saved_dashboards.py
git commit -m "Render contradiction groups and contested answers in the dashboard

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Scientific memory persistence

**Files:**
- Modify: `sci_search/scientific_memory.py` (inside `ingest_run`, after the measurements loop near line 599, before `connection.commit()`)
- Test: `tests/test_memory_ai.py` (add a method to `ScientificMemoryTests`)

**Interfaces:**
- Consumes: validated groups at `investigation["ai_analysis"]["contradiction_groups"]` (Task 2 shape).
- Produces: nodes of type `ContradictionGroup` (canonical key = group id). Edges `run:<id> -PRODUCED_CONTRADICTION-> group` and `group -POSITION_SUPPORTED_BY-> evidence` with properties `{"position": i}`.

- [ ] **Step 1: Write the failing test** (add inside `class ScientificMemoryTests`)

```python
    def test_validated_contradiction_groups_become_graph_nodes(self) -> None:
        corpus = ROOT / "fixtures" / "iron_air_pilot"
        report = (
            GenericResearchEngine(load_corpus(corpus))
            .investigate("What round-trip efficiency is reported?")
            .to_dict()
        )
        first = report["evidence"][0]
        other = next(
            item for item in report["evidence"] if item["publication_id"] != first["publication_id"]
        )
        group = {
            "id": "contradiction:test",
            "topic": "Round-trip efficiency",
            "cause": "unexplained",
            "positions": [
                {"stance": "A", "evidence_ids": [first["id"]], "quotes": [],
                 "publication_ids": [first["publication_id"]]},
                {"stance": "B", "evidence_ids": [other["id"]], "quotes": [],
                 "publication_ids": [other["publication_id"]]},
            ],
            "cause_explanation": None,
            "status": "model_proposed_source_verified",
            "validation_notes": [],
        }
        report["ai_analysis"] = {"claims": [], "contradiction_groups": [group, "not-a-group"]}
        report["research_run"] = {"candidates": [], "review_decisions": {}}
        with tempfile.TemporaryDirectory() as temporary:
            memory = ScientificMemory(Path(temporary) / "memory")
            memory.ingest_run("run-c", "Question", corpus, report)
            snapshot = memory.graph_snapshot(limit=5000)
        nodes = [n for n in snapshot["nodes"] if n["type"] == "ContradictionGroup"]
        self.assertEqual([n["id"] for n in nodes], ["contradiction:test"])
        edges = {
            (e["source"], e["relation"], e["target"]): e["properties"] for e in snapshot["edges"]
        }
        self.assertIn(("run:run-c", "PRODUCED_CONTRADICTION", "contradiction:test"), edges)
        self.assertEqual(
            edges[("contradiction:test", "POSITION_SUPPORTED_BY", other["id"])], {"position": 1}
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_memory_ai.py -k contradiction -v`
Expected: FAIL (`[] != ['contradiction:test']`)

- [ ] **Step 3: Implement** (after the measurements loop, before `connection.commit()`)

```python
            for group in ai.get("contradiction_groups", []) if isinstance(ai, dict) else []:
                if not isinstance(group, dict) or not group.get("id"):
                    continue
                group_id = str(group["id"])
                self._node(connection, group_id, "ContradictionGroup", group_id, group)
                for index, position in enumerate(group.get("positions", [])):
                    if not isinstance(position, dict):
                        continue
                    for evidence_id in position.get("evidence_ids", []):
                        self._edge(
                            connection,
                            group_id,
                            "POSITION_SUPPORTED_BY",
                            str(evidence_id),
                            {"position": index},
                        )
                self._edge(connection, f"run:{run_id}", "PRODUCED_CONTRADICTION", group_id, {})
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_memory_ai.py tests/integration -v`
Expected: all PASS. `sql_memory.py` subclasses `ScientificMemory` and needs no change.

- [ ] **Step 5: Commit**

`scientific_memory.py` has pre-existing uncommitted edits on this branch. Use `git add -p sci_search/scientific_memory.py` and stage only your hunk. Then:

```bash
git add tests/test_memory_ai.py
git commit -m "Persist validated contradiction groups in scientific memory

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

If `tests/test_memory_ai.py` also shows unrelated hunks, stage it with `git add -p` too.

---

### Task 7: Quality protocol and full verification

**Files:**
- Create: `docs/operations/contradiction-groups-quality-check.md`
- Modify: `docs/superpowers/specs/2026-09-24-contradiction-groups-design.md` (status line)

- [ ] **Step 1: Write the protocol**

```markdown
# Contradiction groups: researcher quality check

Purpose: decide whether single-call contradiction grouping is good enough, or whether the separate
adjudication pass described in the spec is needed. This check is manual and not part of CI.

## Procedure

1. Run two questions with `MISTRAL_API_KEY` configured:
   - the goat-foraging corpus: `python3 -m sci_search.cli --corpus corpora/goat_foraging investigate --question "<question from corpora/goat_foraging>"`
   - one new online question via `research-online` with `--max-full-texts 5`.
2. Open each dashboard's "Study comparisons" block, or read `contradiction_groups` in the run JSON.
3. For each group, record in the table below:
   - Genuine disagreement: do the positions actually disagree (yes/no)?
   - Cause correct: is the stated cause right given the quotes (yes/no/unexplained-but-explainable)?
   - Severity sensible: would you rank it the same (yes/higher/lower)?
4. Also record rejected groups from `rejected_records` with category `contradiction_groups`.

| Run | Group ID | Genuine | Cause correct | Severity sensible | Notes |
|---|---|---|---|---|---|

## Decision rule

If more than one third of groups are not genuine disagreements or have the wrong cause, open a
follow-up to implement the separate adjudication pass. Record the outcome and date here.
```

- [ ] **Step 2: Mark the spec status**

In the spec's first lines, replace `Status: design approved in conversation; awaiting written-spec review.` with `Status: implemented; researcher quality check pending (docs/operations/contradiction-groups-quality-check.md).`

- [ ] **Step 3: Run the full verification**

Run: `pytest -q`
Expected: all PASS (retained-corpus tests are skipped unless you pass `--run-retained-corpus`)

Run: `ruff check sci_search tests && ruff format --check sci_search tests && pyright sci_search/domain/contradictions.py sci_search/mistral_analysis.py sci_search/literature_review.py`
Expected: no errors. If `pyright` reports new warnings in the touched files, fix them. Pre-existing warnings elsewhere are out of scope.

- [ ] **Step 4: Commit**

```bash
git add docs/operations/contradiction-groups-quality-check.md docs/superpowers/specs/2026-09-24-contradiction-groups-design.md
git commit -m "Document contradiction group quality check

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- docs/operations/contradiction-groups-quality-check.md docs/superpowers/specs/2026-09-24-contradiction-groups-design.md
```
