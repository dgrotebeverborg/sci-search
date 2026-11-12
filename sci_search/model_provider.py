"""Chat-completions provider profiles for model-assisted analysis steps."""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
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
    if prepared.get("model", "").startswith("gpt-6-"):
        legacy_limit = prepared.pop("max_tokens", None)
        # The benchmarked budget includes reasoning as well as visible JSON.
        prepared["max_completion_tokens"] = max(
            8000, prepared.get("max_completion_tokens") or legacy_limit or 8000
        )
        prepared.setdefault("reasoning_effort", "medium")
        if prepared["reasoning_effort"] != "none":
            for parameter in ("temperature", "top_p", "logprobs", "top_logprobs"):
                prepared.pop(parameter, None)
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
    "codex": ProviderProfile(
        name="codex",
        display_name="Codex (ChatGPT login)",
        endpoint="",
        default_model="gpt-6-sol",
        key_variable="",
        model_variable="SCI_SEARCH_CODEX_MODEL",
        prepare=_unchanged,
    ),
}


def selected_profile() -> ProviderProfile:
    selection = _selection.get()
    value = (
        selection["provider"]
        if selection
        else os.environ.get(PROVIDER_VARIABLE, "").strip().lower() or "mistral"
    )
    if value not in PROFILES:
        raise ValueError(f"{PROVIDER_VARIABLE} must be one of: mistral, openai, codex")
    return PROFILES[value]


def configured_analyzer() -> ModelAnalyzer | None:
    """The selected provider's analyzer, or None when its key is not configured."""
    from sci_search.mistral_analysis import ModelAnalyzer

    profile = selected_profile()
    if profile.name == "codex":
        from sci_search.codex_provider import available, complete_json

        return (
            ModelAnalyzer(
                "", provider=profile, model=configured_model(profile), complete_json=complete_json
            )
            if available()
            else None
        )
    key = _provider_key(profile)
    return ModelAnalyzer(key, provider=profile, model=configured_model(profile)) if key else None


class InvalidAnalysisSelection(ValueError):
    """A requested provider/model is not available to this installation."""


# Context variables isolate synchronous requests and worker jobs without changing
# process environment variables. Persisted selections are re-entered by each worker.

_selection: ContextVar[dict[str, str] | None] = ContextVar("analysis_selection", default=None)


@contextmanager
def analysis_scope(selection: dict[str, str] | None):
    token = _selection.set(dict(selection) if selection else None)
    try:
        yield
    finally:
        _selection.reset(token)


def configured_model(profile: ProviderProfile) -> str:
    selection = _selection.get()
    if selection and selection["provider"] == profile.name:
        return selection["model"]
    return os.environ.get(profile.model_variable) or profile.default_model


def analysis_choices() -> dict[str, Any]:
    """Server-controlled model catalogue; never return credentials."""
    extra = json.loads(os.environ.get("SCI_SEARCH_ANALYSIS_MODELS") or "{}")
    if not isinstance(extra, dict) or any(key not in PROFILES for key in extra):
        raise ValueError("SCI_SEARCH_ANALYSIS_MODELS must map providers to model-name lists")
    items = []
    for profile in PROFILES.values():
        builtins = ["gpt-6-sol", "gpt-6-luna"] if profile.name in {"openai", "codex"} else []
        models = extra.get(profile.name, builtins)
        if not isinstance(models, list) or any(
            not isinstance(model, str) or not model.strip() or len(model) > 200 for model in models
        ):
            raise ValueError("SCI_SEARCH_ANALYSIS_MODELS must map providers to model-name lists")
        default = os.environ.get(profile.model_variable) or profile.default_model
        if profile.name == "codex":
            from sci_search.codex_provider import available

            enabled = available()
        else:
            enabled = bool(_provider_key(profile))
        for model in dict.fromkeys([default, *(m.strip() for m in models)]):
            items.append(
                {
                    "provider": profile.name,
                    "model": model,
                    "available": enabled,
                }
            )
    profile = selected_profile()
    return {
        "items": items,
        "default": {"provider": profile.name, "model": configured_model(profile)},
    }


def resolve_selection(selection: dict[str, str] | None) -> dict[str, str]:
    """Validate new explicit requests; snapshot defaults for legacy clients."""
    catalog = analysis_choices()
    if selection is None:
        return catalog["default"]
    if any(
        item["available"]
        and item["provider"] == selection.get("provider")
        and item["model"] == selection.get("model")
        for item in catalog["items"]
    ):
        return {"provider": selection["provider"], "model": selection["model"]}
    raise InvalidAnalysisSelection("The selected analysis model is not configured or available.")


def _provider_key(profile: ProviderProfile) -> str:
    filename = os.environ.get(f"{profile.key_variable}_FILE", "").strip()
    if filename:
        return Path(filename).read_text(encoding="utf-8").strip()
    return os.environ.get(profile.key_variable, "").strip()
