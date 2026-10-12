import json

import pytest

from sci_search.mistral_analysis import MistralAnalyzer
from sci_search.question_interpretation import interpret_question
from sci_search.question_planning import plan_from_brief


def response_analyzer(payload):
    return MistralAnalyzer(
        "test",
        complete_json=lambda *_: {"choices": [{"message": {"content": json.dumps(payload)}}]},
    )


def test_material_clarification_survives_incomplete_executable_plan():
    question = "Does it help?"
    payload = dict(
        interpreted_question=question,
        objective="Clarify the intervention and outcome before searching.",
        ambiguity="material",
        clarification_question="What intervention and outcome do you mean?",
        evidence_scope=[],
        assumptions=[],
        exclusions=[],
        research_plan=dict(
            intent="relationship",
            subject_terms=[],
            driver_terms=[],
            geography_terms=[],
            evidence_preferences=[],
            exclusion_terms=[],
            relationship_type="unspecified",
        ),
    )
    brief = interpret_question(question, response_analyzer(payload))
    assert brief["clarification_question"] == payload["clarification_question"]
    assert brief["ambiguity"] == "material"
    assert brief["provider"] == "mistral"
    with pytest.raises(ValueError, match="Clarify"):
        plan_from_brief(question, brief)


@pytest.mark.parametrize("question", ["Does it help?", "Is this effective?", "Does it work?"])
def test_unresolved_pronouns_remain_blocked_when_model_unavailable(question):
    brief = interpret_question(question, response_analyzer(None))
    assert brief["ambiguity"] == "material"
    with pytest.raises(ValueError, match="Clarify"):
        plan_from_brief(question, brief)


def test_invalid_model_plan_cannot_silently_approve_a_different_fallback():
    question = "How does salinity affect tomato germination?"
    payload = dict(
        interpreted_question=question,
        objective="Study the relationship.",
        ambiguity="clear",
        clarification_question=None,
        evidence_scope=[],
        assumptions=[],
        exclusions=[],
        research_plan={"intent": "relationship"},
    )
    brief = interpret_question(question, response_analyzer(payload))
    assert brief["ambiguity"] == "material"
    with pytest.raises(ValueError, match="Clarify"):
        plan_from_brief(question, brief)


@pytest.mark.parametrize("question", ["Does it help?", "Is this effective?", "Does it work?"])
def test_no_model_cannot_approve_an_unspecified_subject(question, monkeypatch):
    monkeypatch.setattr("sci_search.question_interpretation.configured_analyzer", lambda: None)
    brief = interpret_question(question)
    assert brief["ambiguity"] == "material"


@pytest.mark.parametrize("structure", [None, {}])
def test_nonmaterial_response_requires_an_executable_plan(structure):
    question = "How does salinity affect tomato germination?"
    payload = dict(
        interpreted_question=question,
        objective="Study the relationship.",
        ambiguity="clear",
        clarification_question=None,
        evidence_scope=[],
        assumptions=[],
        exclusions=[],
        research_plan=structure,
    )
    assert interpret_question(question, response_analyzer(payload))["ambiguity"] == "material"


def test_demonstrative_before_named_subject_is_not_an_unresolved_pronoun(monkeypatch):
    monkeypatch.setattr("sci_search.question_interpretation.configured_analyzer", lambda: None)
    assert interpret_question("Does this biochar improve crop yields?")["ambiguity"] != "material"
