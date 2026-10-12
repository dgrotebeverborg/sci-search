"""Request and selection contracts for the benchmarked GPT-6 models."""

import copy

import pytest

from sci_search.model_provider import (
    PROFILES,
    InvalidAnalysisSelection,
    analysis_choices,
    resolve_selection,
)


@pytest.mark.parametrize("model", ["gpt-6-sol", "gpt-6-luna", "gpt-6-astra"])
@pytest.mark.parametrize("token_limit,expected", [(1200, 8000), (12000, 12000)])
def test_gpt6_prepares_reasoning_requests_without_mutating_input(model, token_limit, expected):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Summarize the evidence."}],
        "max_tokens": token_limit,
        "temperature": 0.1,
        "top_p": 0.9,
        "logprobs": False,
        "top_logprobs": 0,
    }
    original = copy.deepcopy(body)
    prepared = PROFILES["openai"].prepare(body)
    assert prepared == {
        "model": model,
        "messages": original["messages"],
        "max_completion_tokens": expected,
        "reasoning_effort": "medium",
    }
    assert body == original


def test_gpt6_preserves_explicit_completion_budget_and_reasoning_effort():
    prepared = PROFILES["openai"].prepare(
        {
            "model": "gpt-6-sol",
            "max_tokens": 1200,
            "max_completion_tokens": 16000,
            "reasoning_effort": "high",
        }
    )
    assert prepared["max_completion_tokens"] == 16000
    assert prepared["reasoning_effort"] == "high"
    assert "max_tokens" not in prepared
    assert PROFILES["openai"].prepare(prepared) == prepared


@pytest.mark.parametrize(
    "provider,model",
    [
        ("openai", "gpt-4.1-mini"),
        ("mistral", "mistral-small-latest"),
    ],
)
def test_older_models_keep_existing_generation_parameters(provider, model):
    body = {"model": model, "temperature": 0.1, "max_tokens": 1200}
    assert PROFILES[provider].prepare(body) == body


@pytest.fixture
def openai_catalog(monkeypatch):
    for name in (
        "SCI_SEARCH_ANALYSIS_MODELS",
        "OPENAI_MODEL",
        "OPENAI_API_KEY_FILE",
        "MISTRAL_API_KEY_FILE",
        "MISTRAL_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")


@pytest.mark.parametrize("model", ["gpt-6-sol", "gpt-6-luna"])
def test_benchmarked_models_are_selectable_without_changing_default(openai_catalog, model):
    selection = {"provider": "openai", "model": model}
    assert resolve_selection(selection) == selection
    assert analysis_choices()["default"] == {"provider": "openai", "model": "gpt-4.1-mini"}


def test_explicit_model_catalog_and_default_are_preserved(openai_catalog, monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "custom-default")
    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_MODELS", '{"openai":["custom-extra"]}')
    catalog = analysis_choices()
    assert catalog["default"] == {"provider": "openai", "model": "custom-default"}
    assert [item["model"] for item in catalog["items"] if item["provider"] == "openai"] == [
        "custom-default",
        "custom-extra",
    ]
    with pytest.raises(InvalidAnalysisSelection):
        resolve_selection({"provider": "openai", "model": "gpt-6-sol"})


def test_default_gpt6_choices_still_require_provider_credentials(openai_catalog, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    for model in ("gpt-6-sol", "gpt-6-luna"):
        with pytest.raises(InvalidAnalysisSelection):
            resolve_selection({"provider": "openai", "model": model})
