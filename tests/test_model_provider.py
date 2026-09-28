from __future__ import annotations

import copy

import pytest

from sci_search.mistral_analysis import ANALYSIS_SCHEMA
from sci_search.model_provider import PROFILES, openai_strict_schema, selected_profile


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
