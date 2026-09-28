"""Chat-completions provider profiles for model-assisted analysis steps."""

from __future__ import annotations

import copy
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sci_search.mistral_analysis import ModelAnalyzer

PROVIDER_VARIABLE = "SCI_SEARCH_ANALYSIS_PROVIDER"


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    name: str
    display_name: str
    endpoint: str
    default_model: str
    key_variable: str
    model_variable: str
    prepare: Callable[[dict[str, Any]], dict[str, Any]]


def openai_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """OpenAI strict mode requires every property; optional ones become nullable."""
    return _strict(copy.deepcopy(schema))


def _strict(node: Any) -> Any:
    if isinstance(node, list):
        return [_strict(item) for item in node]
    if not isinstance(node, dict):
        return node
    properties = node.get("properties")
    if isinstance(properties, dict):
        required = set(node.get("required", []))
        for name, value in list(properties.items()):
            value = _strict(value)
            if name not in required:
                value = {"anyOf": [value, {"type": "null"}]}
            properties[name] = value
        node["required"] = list(properties)
    for key, value in node.items():
        if key != "properties":
            node[key] = _strict(value)
    return node


def _unchanged(body: dict[str, Any]) -> dict[str, Any]:
    return body


def _openai_prepare(body: dict[str, Any]) -> dict[str, Any]:
    prepared = copy.deepcopy(body)
    holder = (prepared.get("response_format") or {}).get("json_schema")
    if isinstance(holder, dict) and isinstance(holder.get("schema"), dict):
        holder["schema"] = openai_strict_schema(holder["schema"])
    return prepared


PROFILES: dict[str, ProviderProfile] = {
    "mistral": ProviderProfile(
        name="mistral",
        display_name="Mistral",
        endpoint="https://api.mistral.ai/v1/chat/completions",
        default_model="mistral-small-latest",
        key_variable="MISTRAL_API_KEY",
        model_variable="MISTRAL_MODEL",
        prepare=_unchanged,
    ),
    "openai": ProviderProfile(
        name="openai",
        display_name="OpenAI",
        endpoint="https://api.openai.com/v1/chat/completions",
        default_model="gpt-4.1-mini",
        key_variable="OPENAI_API_KEY",
        model_variable="OPENAI_MODEL",
        prepare=_openai_prepare,
    ),
}


def selected_profile() -> ProviderProfile:
    value = os.environ.get(PROVIDER_VARIABLE, "").strip().lower() or "mistral"
    if value not in PROFILES:
        raise ValueError(f"{PROVIDER_VARIABLE} must be one of: mistral, openai")
    return PROFILES[value]


def configured_analyzer() -> ModelAnalyzer | None:
    """The selected provider's analyzer, or None when its key is not configured."""
    from sci_search.mistral_analysis import ModelAnalyzer

    profile = selected_profile()
    key = os.environ.get(profile.key_variable, "").strip()
    return ModelAnalyzer(key, provider=profile) if key else None
