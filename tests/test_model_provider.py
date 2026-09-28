from __future__ import annotations

import copy
import json

import pytest

from sci_search.application.analysis import MistralAnalysisProvider, analyze_evidence
from sci_search.mistral_analysis import (
    ANALYSIS_SCHEMA,
    MistralAnalyzer,
    ModelAnalyzer,
    analyze_if_configured,
)
from sci_search.model_provider import (
    PROFILES,
    configured_analyzer,
    openai_strict_schema,
    selected_profile,
)
from sci_search.question_interpretation import QUESTION_BRIEF_SCHEMA, interpret_question
from sci_search.study_matrix import ADJUDICATION_SCHEMA, adjudicate_uncertain_studies


def _schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["a"],
        "properties": {
            "a": {"type": "string"},
            "b": {"$ref": "#/$defs/item"},
            "c": {"type": "array", "items": {"$ref": "#/$defs/item"}},
        },
        "$defs": {
            "item": {
                "type": "object",
                "additionalProperties": False,
                "required": ["x"],
                "properties": {"x": {"type": "string"}, "y": {"type": "string"}},
            }
        },
    }


def test_optional_properties_become_required_and_nullable() -> None:
    converted = openai_strict_schema(_schema())
    assert converted["required"] == ["a", "b", "c"]
    assert converted["properties"]["a"] == {"type": "string"}
    assert converted["properties"]["b"] == {"anyOf": [{"$ref": "#/$defs/item"}, {"type": "null"}]}
    assert converted["properties"]["c"]["anyOf"][1] == {"type": "null"}
    item = converted["$defs"]["item"]
    assert item["required"] == ["x", "y"]
    assert item["properties"]["y"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}


def test_conversion_is_idempotent_and_does_not_mutate_input() -> None:
    original = _schema()
    snapshot = copy.deepcopy(original)
    once = openai_strict_schema(original)
    assert original == snapshot
    assert openai_strict_schema(once) == once


def test_analysis_schema_converts_exactly_the_two_optional_fields() -> None:
    before = copy.deepcopy(ANALYSIS_SCHEMA)
    converted = openai_strict_schema(ANALYSIS_SCHEMA)
    assert ANALYSIS_SCHEMA == before
    assertion = converted["$defs"]["assertion"]
    group = converted["$defs"]["contradiction_group"]
    assert assertion["properties"]["qualification"]["anyOf"][1] == {"type": "null"}
    assert group["properties"]["cause_explanation"]["anyOf"][1] == {"type": "null"}
    assert set(group["required"]) == set(group["properties"])


def test_openai_prepare_converts_body_schema_without_mutating_body() -> None:
    body = {
        "model": "m",
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "n", "schema": _schema(), "strict": True},
        },
        "messages": [],
    }
    snapshot = copy.deepcopy(body)
    prepared = PROFILES["openai"].prepare(body)
    assert body == snapshot
    assert prepared["response_format"]["json_schema"]["schema"]["required"] == ["a", "b", "c"]
    assert prepared["messages"] == []


def test_mistral_prepare_returns_body_unchanged() -> None:
    body = {"response_format": {"json_schema": {"schema": _schema()}}}
    assert PROFILES["mistral"].prepare(body) is body


def test_selected_profile_defaults_to_mistral(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SCI_SEARCH_ANALYSIS_PROVIDER", raising=False)
    assert selected_profile().name == "mistral"


def test_selected_profile_normalizes_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_PROVIDER", " OpenAI ")
    profile = selected_profile()
    assert profile.name == "openai"
    assert profile.default_model == "gpt-4.1-mini"
    assert profile.endpoint == "https://api.openai.com/v1/chat/completions"
    assert profile.key_variable == "OPENAI_API_KEY"


def test_invalid_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_PROVIDER", "claude")
    with pytest.raises(ValueError, match="must be one of: mistral, openai"):
        selected_profile()


STATEMENT = "Measured efficiency was 70% at laboratory scale."
OTHER = "Measured efficiency was 45% in the field trial."


def _evidence() -> list[dict]:
    return [
        {
            "id": "e1",
            "publication_id": "p1",
            "statement": STATEMENT,
            "passage": STATEMENT,
            "evidence_type": "laboratory_experiment",
        },
        {
            "id": "e2",
            "publication_id": "p2",
            "statement": OTHER,
            "passage": OTHER,
            "evidence_type": "field_study",
        },
    ]


def _payload() -> dict:
    assertion = {
        "text": "Laboratory efficiency was reported as 70%.",
        "evidence_ids": ["e1"],
        "quotes": [{"evidence_id": "e1", "quote": STATEMENT}],
        "qualification": None,
    }
    return {
        "answer": assertion,
        "claims": [assertion],
        "agreements": [],
        "contradictions": [],
        "method_differences": [],
        "limitations": [],
        "uncertainties": [],
        "assumptions": [],
        "knowledge_gaps": [],
        "entities": [],
        "measurements": [],
        "contradiction_groups": [
            {
                "topic": "Efficiency level",
                "positions": [
                    {
                        "text": "High",
                        "evidence_ids": ["e1"],
                        "quotes": [{"evidence_id": "e1", "quote": STATEMENT}],
                        "qualification": None,
                    },
                    {
                        "text": "Low",
                        "evidence_ids": ["e2"],
                        "quotes": [{"evidence_id": "e2", "quote": OTHER}],
                        "qualification": None,
                    },
                ],
                "cause": "different_conditions",
                "cause_explanation": None,
            }
        ],
    }


class _Recorder:
    def __init__(self) -> None:
        self.bodies: list[dict] = []

    def __call__(self, body: dict, headers: dict) -> dict:
        self.bodies.append(body)
        return {"choices": [{"message": {"content": json.dumps(_payload())}}], "usage": {}}


def test_openai_analyzer_sends_converted_schema_and_records_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    recorder = _Recorder()
    analyzer = ModelAnalyzer("key", provider=PROFILES["openai"], complete_json=recorder)
    result = analyze_evidence("Question", _evidence(), {}, MistralAnalysisProvider(analyzer))
    [body] = recorder.bodies
    assert body["model"] == "gpt-4.1-mini"
    schema = body["response_format"]["json_schema"]["schema"]
    assert schema["$defs"]["assertion"]["properties"]["qualification"]["anyOf"][1] == {
        "type": "null"
    }
    assert result["status"] == "complete"
    assert result["provider"] == "openai"
    assert result["method"] == "openai_structured_evidence_analysis_v1"
    assert result["claims"][0]["qualification"] == ""
    [group] = result["contradiction_groups"]
    assert group["cause"] == "unexplained"
    assert group["validation_notes"]


def test_default_analyzer_keeps_the_mistral_body_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISTRAL_MODEL", raising=False)
    recorder = _Recorder()
    analyzer = MistralAnalyzer("key", complete_json=recorder)
    analyzer.analyze("Question", _evidence())
    [body] = recorder.bodies
    assert body["model"] == "mistral-small-latest"
    assert body["response_format"]["json_schema"]["schema"] == ANALYSIS_SCHEMA
    assert analyzer.endpoint == "https://api.mistral.ai/v1/chat/completions"
    assert MistralAnalysisProvider(analyzer).provider_name == "mistral"


def test_openai_model_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5-mini")
    assert ModelAnalyzer("key", provider=PROFILES["openai"]).model == "gpt-5-mini"


def test_configured_analyzer_uses_selected_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_PROVIDER", "openai")
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert configured_analyzer() is None
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    analyzer = configured_analyzer()
    assert analyzer is not None
    assert analyzer.provider.name == "openai"
    assert analyzer.api_key == "openai-key"


def test_missing_openai_key_falls_back_with_openai_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    # No Mistral key either: before the change this must not reach the network.
    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_PROVIDER", "openai")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = analyze_if_configured("Question", _evidence())
    assert result["status"] == "unavailable"
    assert result["fallback_reason"] == (
        "OPENAI_API_KEY is not configured; deterministic extractive analysis was used"
    )


def _reply(payload: dict):
    bodies: list[dict] = []

    def complete(body: dict, headers: dict) -> dict:
        bodies.append(body)
        return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    return complete, bodies


def test_question_interpretation_records_openai_provider() -> None:
    complete, bodies = _reply(
        {
            "interpreted_question": "How does salinity affect tomato germination?",
            "objective": "Summarize salinity effects on germination.",
            "evidence_scope": [],
            "assumptions": [],
            "exclusions": [],
            "ambiguity": "clear",
            "clarification_question": None,
        }
    )
    analyzer = ModelAnalyzer(
        "key", provider=PROFILES["openai"], model="gpt-4.1-mini", complete_json=complete
    )
    brief = interpret_question("How does salinity affect tomato seed germination?", analyzer)
    assert brief["provider"] == "openai"
    assert brief["method"] == "openai_structured_question_interpretation_v1"
    assert brief["model"] == "gpt-4.1-mini"
    [body] = bodies
    assert body["response_format"]["json_schema"]["schema"] == openai_strict_schema(
        QUESTION_BRIEF_SCHEMA
    )


def _matrix() -> dict:
    return {
        "studies": [
            {
                "publication_id": "p1",
                "title": "Uncertain study",
                "screening": {"decision": "uncertain"},
                "dimension_coverage": [],
                "selected_passages": [],
            }
        ]
    }


def test_adjudication_records_openai_provider() -> None:
    complete, bodies = _reply({"decisions": []})
    analyzer = ModelAnalyzer("key", provider=PROFILES["openai"], complete_json=complete)
    result = adjudicate_uncertain_studies("Question", _matrix(), analyzer)
    assert result["status"] == "complete"
    assert result["provider"] == "openai"
    assert result["method"] == "openai_quote_validated_fulltext_adjudication_v1"
    [body] = bodies
    assert body["response_format"]["json_schema"]["schema"] == openai_strict_schema(
        ADJUDICATION_SCHEMA
    )


def test_mistral_adjudication_keeps_existing_method_name() -> None:
    complete, _ = _reply({"decisions": []})
    result = adjudicate_uncertain_studies(
        "Question", _matrix(), MistralAnalyzer("key", complete_json=complete)
    )
    assert result["provider"] == "mistral"
    assert result["method"] == "mistral_quote_validated_fulltext_adjudication_v1"


def test_adjudication_without_selected_key_names_that_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # No Mistral key either: before the change this must not reach the network.
    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_PROVIDER", "openai")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = adjudicate_uncertain_studies("Question", _matrix())
    assert result["status"] == "unavailable"
    assert result["reason"] == "OPENAI_API_KEY is not configured"
