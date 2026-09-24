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
        [_group(positions=[_position("e1", LOW_SALT), _position("e2", HIGH_SALT), bad])],
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


def test_rephrased_duplicate_with_same_positions_is_rejected() -> None:
    groups, rejected = validate_contradiction_groups(
        [_group(), _group(topic="Effect of salinity on germination")], _evidence()
    )
    assert [group["topic"] for group in groups] == ["Salinity effect on germination"]
    assert rejected[0]["category"] == "contradiction_groups"
    assert rejected[0]["reason"] == f"duplicate of {groups[0]['id']}"
