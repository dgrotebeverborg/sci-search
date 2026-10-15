# OpenAI Analysis Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Sci-Search run question interpretation, full-text adjudication, and grounded evidence analysis through Mistral or OpenAI, selected by `SCI_SEARCH_ANALYSIS_PROVIDER`.

**Architecture:** A new `sci_search/model_provider.py` holds two provider profiles (endpoint, default model, key and model variables, and a `prepare(body)` step) plus `configured_analyzer()`. `MistralAnalyzer` becomes a provider-aware `ModelAnalyzer` whose `complete_json` always applies `provider.prepare` before the transport, so all three call sites and all injected test transports see the OpenAI strict-schema conversion. The five direct `MISTRAL_API_KEY` reads use the factory. Provenance records the provider name.

**Tech Stack:** Python 3.11 standard library (`urllib`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-28-openai-analysis-provider-design.md`

## Global Constraints

- `SCI_SEARCH_ANALYSIS_PROVIDER` values: `mistral`, `openai`. Default `mistral`. The value is trimmed and lowercased. Any other value raises `ValueError("SCI_SEARCH_ANALYSIS_PROVIDER must be one of: mistral, openai")`.
- Defaults: Mistral model `mistral-small-latest` (`MISTRAL_MODEL`), OpenAI model `gpt-4.1-mini` (`OPENAI_MODEL`).
- Endpoints: `https://api.mistral.ai/v1/chat/completions`, `https://api.openai.com/v1/chat/completions`.
- The Mistral request body stays byte-identical to today's. Mistral `prepare` returns its input unchanged.
- No automatic failover between providers.
- `configuration.load_legacy_mistral_key` is not changed; `OPENAI_API_KEY` is never read from sci-graph.
- Method names are `f"{provider}_structured_evidence_analysis_v1"`, `f"{provider}_structured_question_interpretation_v1"`, and `f"{provider}_quote_validated_fulltext_adjudication_v1"`. The adjudication `not_needed` and `unavailable` records keep `ADJUDICATION_METHOD`.
- `PROMPT_CONTRACT_VERSION` and `SCHEMA_VERSION` do not change.
- Missing-key reasons name the selected key variable, e.g. `"OPENAI_API_KEY is not configured; deterministic extractive analysis was used"`.
- The analysis fingerprint gains a `"provider"` entry only when the provider is not Mistral. For the fixed input in Task 4 the Mistral fingerprint must stay `e1d5ac9fee8186ed3ce15911f2f764c2596af64fea315cca204da2744bf59d1b`.
- No new dependencies. No database migration.
- Run commands from the repo root with `source .venv/bin/activate`; run pytest as `python -m pytest` (as CI does).
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- `SCI_SEARCH_ANALYSIS_PROVIDER` set to ` OpenAI ` (spaces, capitals) must select OpenAI, not raise. Test in Task 1.
- An OpenAI response with `"qualification": null` on every assertion and `"cause_explanation": null` on a non-`unexplained` group must validate (qualification empty; group downgraded to `unexplained` with a note), not reject the whole analysis. Test in Task 2.
- A caller that passes its own `MistralAnalyzer("key", complete_json=...)` (every existing test and `ResearchRunManager(analyzer=...)`) must keep sending the unmodified Mistral body. Test in Task 2.
- `SCI_SEARCH_ANALYSIS_PROVIDER=openai` with only `MISTRAL_API_KEY` set must fall back with an `OPENAI_API_KEY` reason and never silently use Mistral. Test in Task 2 (analysis) and Task 3 (adjudication).
- The strict-schema conversion must not mutate the module-level `ANALYSIS_SCHEMA`, which is shared by every later request. Test in Task 1.

## File Structure

- Create `sci_search/model_provider.py`: profiles, `openai_strict_schema`, `selected_profile`, `configured_analyzer`.
- Modify `sci_search/mistral_analysis.py`: `ModelAnalyzer` (alias `MistralAnalyzer`), provider-named provenance, `analyze_if_configured`.
- Modify `sci_search/application/analysis.py`: `MistralAnalysisProvider` takes its provider name from the analyzer.
- Modify `sci_search/question_interpretation.py`, `sci_search/study_matrix.py`: factory and provider-named provenance.
- Modify `sci_search/research_runs.py` (`_analyze` fingerprint), `sci_search/infrastructure/research_execution.py` (`_manager`), `sci_search/worker_runtime.py` (secret files), `sci_search/infrastructure/observability.py` (`_PROVIDERS`).
- Modify `.env.example`, `README.md`.
- Tests: `tests/test_model_provider.py` (Tasks 1–4).

---

### Task 1: Provider profiles and strict-schema conversion

**Files:**
- Create: `sci_search/model_provider.py`
- Test: `tests/test_model_provider.py`

**Interfaces:**
- Produces:
  - `PROVIDER_VARIABLE = "SCI_SEARCH_ANALYSIS_PROVIDER"`
  - `ProviderProfile(name: str, display_name: str, endpoint: str, default_model: str, key_variable: str, model_variable: str, prepare: Callable[[dict[str, Any]], dict[str, Any]])` (frozen dataclass)
  - `PROFILES: dict[str, ProviderProfile]` with keys `"mistral"`, `"openai"`
  - `openai_strict_schema(schema: dict[str, Any]) -> dict[str, Any]`
  - `selected_profile() -> ProviderProfile`
  - `configured_analyzer() -> ModelAnalyzer | None` (implemented here, exercised in Task 2 once `ModelAnalyzer` accepts `provider`)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_model_provider.py
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
        "response_format": {"type": "json_schema", "json_schema": {"name": "n", "schema": _schema(), "strict": True}},
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_model_provider.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sci_search.model_provider'`

- [ ] **Step 3: Implement**

```python
# sci_search/model_provider.py
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
```

Note: `_strict` replaces a non-required property with a wrapper after recursing into it. On a second pass every property is already in `required`, so nothing is wrapped again; that is what makes it idempotent.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_model_provider.py -q && ruff check sci_search/model_provider.py tests/test_model_provider.py && ruff format --check sci_search/model_provider.py tests/test_model_provider.py`
Expected: all pass, no ruff findings. If the format check fails, run `ruff format` on the two files.

Note: `configured_analyzer` passes `provider=` to `ModelAnalyzer`, which does not exist until Task 2. Nothing calls it in this task. Pyright may flag the lazy import; that is resolved by Task 2.

- [ ] **Step 5: Commit**

```bash
git add sci_search/model_provider.py tests/test_model_provider.py
git commit -m "Add analysis provider profiles and OpenAI strict-schema conversion

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Provider-aware analyzer and grounded analysis

**Files:**
- Modify: `sci_search/mistral_analysis.py` (class at ~line 180, `analyze` provenance at ~line 240, `_complete_json` at ~line 262, `analyze_if_configured` at ~line 284)
- Modify: `sci_search/application/analysis.py:62-70`
- Test: `tests/test_model_provider.py` (append)

**Interfaces:**
- Consumes: `PROFILES`, `ProviderProfile`, `selected_profile`, `configured_analyzer` from Task 1.
- Produces:
  - `ModelAnalyzer(api_key: str, *, provider: ProviderProfile | None = None, model: str | None = None, complete_json: JsonCompletion | None = None)` with attributes `provider`, `api_key`, `model`, `complete_json`, and property `endpoint`
  - `MistralAnalyzer = ModelAnalyzer`
  - `MistralAnalysisProvider(analyzer).provider_name == analyzer.provider.name`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_model_provider.py`; move the new `import`/`from` lines to the top of the file with the existing imports so ruff's import rules pass)

```python
import json

from sci_search.application.analysis import MistralAnalysisProvider, analyze_evidence
from sci_search.mistral_analysis import MistralAnalyzer, ModelAnalyzer, analyze_if_configured
from sci_search.model_provider import configured_analyzer

STATEMENT = "Measured efficiency was 70% at laboratory scale."
OTHER = "Measured efficiency was 45% in the field trial."


def _evidence() -> list[dict]:
    return [
        {"id": "e1", "publication_id": "p1", "statement": STATEMENT, "passage": STATEMENT,
         "evidence_type": "laboratory_experiment"},
        {"id": "e2", "publication_id": "p2", "statement": OTHER, "passage": OTHER,
         "evidence_type": "field_study"},
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
                    {"text": "High", "evidence_ids": ["e1"],
                     "quotes": [{"evidence_id": "e1", "quote": STATEMENT}], "qualification": None},
                    {"text": "Low", "evidence_ids": ["e2"],
                     "quotes": [{"evidence_id": "e2", "quote": OTHER}], "qualification": None},
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
    assert schema["$defs"]["assertion"]["properties"]["qualification"]["anyOf"][1] == {"type": "null"}
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_model_provider.py -q`
Expected: FAIL with `ImportError: cannot import name 'ModelAnalyzer'`

- [ ] **Step 3: Make the analyzer provider-aware**

In `sci_search/mistral_analysis.py`, add after the `sci_search.domain.contradictions` import:

```python
from sci_search.model_provider import PROFILES, ProviderProfile
```

Replace the class header, `endpoint` attribute, and `__init__` (currently `class MistralAnalyzer:` … `self.complete_json = complete_json or self._complete_json`) with:

```python
class ModelAnalyzer:
    def __init__(
        self,
        api_key: str,
        *,
        provider: ProviderProfile | None = None,
        model: str | None = None,
        complete_json: JsonCompletion | None = None,
    ) -> None:
        self.provider = provider or PROFILES["mistral"]
        if not api_key.strip():
            raise ValueError(f"{self.provider.display_name} API key is required")
        self.api_key = api_key
        self.model = (
            model
            or os.environ.get(self.provider.model_variable)
            or self.provider.default_model
        )
        transport = complete_json or self._complete_json
        # Every call site goes through complete_json, so provider preparation cannot be skipped.
        self.complete_json: JsonCompletion = lambda body, headers: transport(
            self.provider.prepare(body), headers
        )

    @property
    def endpoint(self) -> str:
        return self.provider.endpoint
```

In `analyze`, replace:

```python
                "provider": "mistral",
```
```python
                "method": "mistral_structured_evidence_analysis_v1",
```

with:

```python
                "provider": self.provider.name,
```
```python
                "method": f"{self.provider.name}_structured_evidence_analysis_v1",
```

In `_complete_json`, replace `raise ValueError("Mistral response was not a JSON object")` with `raise ValueError(f"{self.provider.display_name} response was not a JSON object")` and `raise RuntimeError("Mistral request exhausted retries")` with `raise RuntimeError(f"{self.provider.display_name} request exhausted retries")`.

Directly after the class, add:

```python
MistralAnalyzer = ModelAnalyzer
```

Replace the body of `analyze_if_configured` from `selected = analyzer` up to (not including) the final `from sci_search.application.analysis import MistralAnalysisProvider, analyze_evidence` with:

```python
    selected = analyzer
    if selected is None:
        from sci_search.model_provider import configured_analyzer, selected_profile

        selected = configured_analyzer()
        if selected is None:
            from sci_search.application.analysis import fallback_analysis

            packet = select_model_evidence(evidence, adequacy or {})
            return fallback_analysis(
                packet,
                f"{selected_profile().key_variable} is not configured; "
                "deterministic extractive analysis was used",
                provider=None,
                model=None,
            ).as_dict()
```

In `sci_search/application/analysis.py`, replace the start of `MistralAnalysisProvider`:

```python
class MistralAnalysisProvider:
    provider_name = "mistral"

    def __init__(self, analyzer: MistralAnalyzer) -> None:
        self.analyzer = analyzer
        self.model_name = analyzer.model
```

with:

```python
class MistralAnalysisProvider:
    def __init__(self, analyzer: MistralAnalyzer) -> None:
        self.analyzer = analyzer
        self.provider_name = analyzer.provider.name
        self.model_name = analyzer.model
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_model_provider.py tests/application tests/test_memory_ai.py tests/test_contradiction_pipeline.py -q`
Expected: all PASS. Existing tests construct `MistralAnalyzer("secret", model=..., complete_json=...)`; they must pass unchanged.

Run: `ruff check sci_search/mistral_analysis.py sci_search/application/analysis.py tests/test_model_provider.py && ruff format sci_search/mistral_analysis.py tests/test_model_provider.py`

- [ ] **Step 5: Commit**

```bash
git add sci_search/mistral_analysis.py sci_search/application/analysis.py tests/test_model_provider.py
git commit -m "Make the analyzer provider-aware and select it from configuration

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Question interpretation and adjudication

**Files:**
- Modify: `sci_search/question_interpretation.py:73-80` and `:166-167`
- Modify: `sci_search/study_matrix.py:242-251` and `:302-306`
- Test: `tests/test_model_provider.py` (append)

**Interfaces:**
- Consumes: `configured_analyzer`, `selected_profile` (Task 1); `ModelAnalyzer.provider` (Task 2).
- Produces: question brief `provider`/`method` and adjudication `provider`/`method` named after the analyzer's provider.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_model_provider.py`; move the new `import`/`from` lines to the top of the file with the existing imports so ruff's import rules pass)

```python
from sci_search.question_interpretation import QUESTION_BRIEF_SCHEMA, interpret_question
from sci_search.study_matrix import ADJUDICATION_SCHEMA, adjudicate_uncertain_studies


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
    analyzer = ModelAnalyzer("key", provider=PROFILES["openai"], model="gpt-4.1-mini", complete_json=complete)
    brief = interpret_question("How does salinity affect tomato seed germination?", analyzer)
    assert brief["provider"] == "openai"
    assert brief["method"] == "openai_structured_question_interpretation_v1"
    assert brief["model"] == "gpt-4.1-mini"
    [body] = bodies
    assert body["response_format"]["json_schema"]["schema"] == openai_strict_schema(QUESTION_BRIEF_SCHEMA)


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
    assert body["response_format"]["json_schema"]["schema"] == openai_strict_schema(ADJUDICATION_SCHEMA)


def test_mistral_adjudication_keeps_existing_method_name() -> None:
    complete, _ = _reply({"decisions": []})
    result = adjudicate_uncertain_studies("Question", _matrix(), MistralAnalyzer("key", complete_json=complete))
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_model_provider.py -q -k "interpretation or adjudication"`
Expected: FAIL. The interpretation and OpenAI adjudication tests fail on `provider == "mistral"`; the missing-key test fails because the reason names `MISTRAL_API_KEY`.

- [ ] **Step 3: Implement**

In `sci_search/question_interpretation.py`, add `from sci_search.model_provider import configured_analyzer` to the imports. In `interpret_question`, replace:

```python
    if selected is None:
        key = os.environ.get("MISTRAL_API_KEY", "").strip()
        if key:
            selected = MistralAnalyzer(key)
```

with:

```python
    if selected is None:
        selected = configured_analyzer()
```

In `_model_interpretation`, replace:

```python
        method="mistral_structured_question_interpretation_v1",
        provider="mistral",
```

with:

```python
        method=f"{analyzer.provider.name}_structured_question_interpretation_v1",
        provider=analyzer.provider.name,
```

If `os` is no longer used in `question_interpretation.py`, remove its import (ruff reports F401).

In `sci_search/study_matrix.py`, add `from sci_search.model_provider import configured_analyzer, selected_profile` to the imports. In `adjudicate_uncertain_studies`, replace:

```python
    if selected is None:
        key = os.environ.get("MISTRAL_API_KEY", "").strip()
        if not key:
            return {
                "status": "unavailable",
                "method": ADJUDICATION_METHOD,
                "reason": "MISTRAL_API_KEY is not configured",
                "decisions": [],
            }
        selected = MistralAnalyzer(key)
```

with:

```python
    if selected is None:
        selected = configured_analyzer()
        if selected is None:
            return {
                "status": "unavailable",
                "method": ADJUDICATION_METHOD,
                "reason": f"{selected_profile().key_variable} is not configured",
                "decisions": [],
            }
```

In the `status: complete` return of the same function, replace:

```python
            "provider": "mistral",
            "model": selected.model,
            "method": ADJUDICATION_METHOD,
```

with:

```python
            "provider": selected.provider.name,
            "model": selected.model,
            "method": f"{selected.provider.name}_quote_validated_fulltext_adjudication_v1",
```

If `os` is no longer used in `study_matrix.py`, remove its import.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_model_provider.py tests/test_study_matrix.py tests/test_question_interpretation.py tests/test_fulltext_screening.py -q && ruff check sci_search/question_interpretation.py sci_search/study_matrix.py tests/test_model_provider.py && ruff format sci_search/question_interpretation.py sci_search/study_matrix.py tests/test_model_provider.py`
Expected: all PASS, no ruff findings.

- [ ] **Step 5: Commit**

```bash
git add sci_search/question_interpretation.py sci_search/study_matrix.py tests/test_model_provider.py
git commit -m "Use the configured provider for question interpretation and adjudication

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Runner, fingerprint, worker, and metrics

**Files:**
- Modify: `sci_search/research_runs.py:1378-1392` (`_analyze`)
- Modify: `sci_search/infrastructure/research_execution.py:23` and `:415-429` (`_manager`)
- Modify: `sci_search/worker_runtime.py:23`
- Modify: `sci_search/infrastructure/observability.py:74-76`
- Test: `tests/test_model_provider.py` (append)

**Interfaces:**
- Consumes: `ModelAnalyzer`, `PROFILES`, `selected_profile`, `configured_analyzer`.
- Produces: fingerprint rule (provider entry only for non-Mistral); `_manager` uses `configured_analyzer()`; `Metrics.record_provider("openai", ...)` accepted.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_model_provider.py`; move the new `import`/`from` lines to the top of the file with the existing imports so ruff's import rules pass)

```python
from pathlib import Path

from sci_search.infrastructure.observability import Metrics, ProviderOutcome
from sci_search.research_runs import ResearchRunManager

MISTRAL_FINGERPRINT = "e1d5ac9fee8186ed3ce15911f2f764c2596af64fea315cca204da2744bf59d1b"


class _Memory:
    def __init__(self) -> None:
        self.keys: list[str] = []

    def cached_analysis(self, key: str) -> dict:
        self.keys.append(key)
        return {"cached": True}


def _fingerprint(tmp_path: Path, analyzer: ModelAnalyzer) -> str:
    memory = _Memory()
    manager = ResearchRunManager(tmp_path, openalex_api_key="test", memory=memory, analyzer=analyzer)
    manager._analyze("Q", [], {})
    return memory.keys[0]


def test_mistral_fingerprint_is_unchanged(tmp_path: Path) -> None:
    analyzer = MistralAnalyzer("k", model="mistral-small-latest", complete_json=lambda b, h: {})
    assert _fingerprint(tmp_path, analyzer) == MISTRAL_FINGERPRINT


def test_openai_fingerprint_differs_even_with_the_same_model_name(tmp_path: Path) -> None:
    analyzer = ModelAnalyzer(
        "k", provider=PROFILES["openai"], model="mistral-small-latest", complete_json=lambda b, h: {}
    )
    assert _fingerprint(tmp_path, analyzer) != MISTRAL_FINGERPRINT


def test_fingerprint_without_analyzer_uses_selected_profile_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    memory = _Memory()
    manager = ResearchRunManager(tmp_path, openalex_api_key="test", memory=memory)
    manager._analyze("Q", [], {})
    openai = ModelAnalyzer("k", provider=PROFILES["openai"], complete_json=lambda b, h: {})
    assert memory.keys[0] == _fingerprint(tmp_path, openai)


def test_production_manager_uses_selected_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from sci_search.infrastructure.research_execution import _manager

    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    manager = _manager(tmp_path)
    assert manager.analyzer is not None
    assert manager.analyzer.provider.name == "openai"


def test_metrics_accept_openai_provider() -> None:
    Metrics().record_provider("openai", ProviderOutcome.SUCCEEDED)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_model_provider.py -q -k "fingerprint or production_manager or metrics"`
Expected: `test_mistral_fingerprint_is_unchanged` PASSES (it pins today's value). The other four FAIL: the OpenAI fingerprints equal Mistral's or use the Mistral model, `_manager` builds a Mistral analyzer from `MISTRAL_API_KEY` (so `analyzer` is `None`), and `record_provider` raises on `"openai"`.

- [ ] **Step 3: Implement the fingerprint rule**

In `sci_search/research_runs.py` `_analyze`, replace:

```python
        model = (
            self.analyzer.model
            if self.analyzer is not None
            else os.environ.get("MISTRAL_MODEL", "mistral-small-latest")
        )
        feedback_reader = getattr(self.memory, "feedback_events", None)
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "question": question,
                    "model": model,
```

with:

```python
        if self.analyzer is not None:
            provider, model = self.analyzer.provider, self.analyzer.model
        else:
            provider = selected_profile()
            model = os.environ.get(provider.model_variable) or provider.default_model
        feedback_reader = getattr(self.memory, "feedback_events", None)
        # Mistral keys omit the provider so caches from before provider selection stay valid.
        provider_entry = {} if provider.name == "mistral" else {"provider": provider.name}
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    **provider_entry,
                    "question": question,
                    "model": model,
```

Add `from sci_search.model_provider import selected_profile` to the imports of `research_runs.py`.

Note: `json.dumps(..., sort_keys=True)` is already used, so inserting the key does not depend on dict order; the Mistral payload is unchanged because the entry is omitted.

- [ ] **Step 4: Use the factory in the production runner, worker, and metrics**

In `sci_search/infrastructure/research_execution.py`, replace the import `from sci_search.mistral_analysis import MistralAnalyzer` with `from sci_search.model_provider import configured_analyzer`, and in `_manager` delete the line `mistral_key = os.environ.get("MISTRAL_API_KEY", "").strip()` and replace `analyzer=MistralAnalyzer(mistral_key) if mistral_key else None,` with `analyzer=configured_analyzer(),`. If `MistralAnalyzer` is referenced elsewhere in the file (`grep -n MistralAnalyzer sci_search/infrastructure/research_execution.py`), keep that import too.

In `sci_search/worker_runtime.py`, replace:

```python
for variable in ("OPENALEX_API_KEY", "MISTRAL_API_KEY"):
```

with:

```python
for variable in ("OPENALEX_API_KEY", "MISTRAL_API_KEY", "OPENAI_API_KEY"):
```

In `sci_search/infrastructure/observability.py`, replace:

```python
    {"crossref", "europe_pmc", "openalex", "scientific_memory", "mistral", "other"}
```

with:

```python
    {"crossref", "europe_pmc", "openalex", "scientific_memory", "mistral", "openai", "other"}
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_model_provider.py tests/infrastructure/test_observability.py tests/api -q && ruff check sci_search tests && ruff format --check sci_search tests`
Expected: all PASS, no ruff findings.

- [ ] **Step 6: Commit**

```bash
git add sci_search/research_runs.py sci_search/infrastructure/research_execution.py sci_search/worker_runtime.py sci_search/infrastructure/observability.py tests/test_model_provider.py
git commit -m "Select the analysis provider in runners and keep caches provider-specific

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Documentation, full verification, and live check

**Files:**
- Modify: `.env.example`
- Modify: `README.md` (the "Online scientific search" section)
- Modify: `docs/superpowers/specs/2026-09-28-openai-analysis-provider-design.md` (status line)

- [ ] **Step 1: Document the settings**

In `.env.example`, replace:

```
# Reserved for model-assisted extraction/query planning adapters.
MISTRAL_API_KEY=
MISTRAL_MODEL=mistral-small-latest
```

with:

```
# Model-assisted question interpretation, adjudication, and grounded analysis.
# Choose one provider: mistral (default) or openai. There is no automatic failover.
SCI_SEARCH_ANALYSIS_PROVIDER=mistral
MISTRAL_API_KEY=
MISTRAL_MODEL=mistral-small-latest
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
```

In `README.md`, directly after the paragraph that begins "During migration from sci-graph, if Sci-Search has no Mistral key of its own", add:

```markdown
To use OpenAI instead of Mistral, set `SCI_SEARCH_ANALYSIS_PROVIDER=openai` and `OPENAI_API_KEY` in
`.env.local` (`OPENAI_MODEL` defaults to `gpt-4.1-mini`). The same grounding validation applies to
both providers. Sci-Search never falls back from one provider to the other: if the selected
provider's key is missing or a request fails, the deterministic extractive answer is shown with the
reason. `OPENAI_API_KEY` is never read from sci-graph. Stored results record the provider and model,
and cached analyses are not shared between providers.
```

- [ ] **Step 2: Full verification**

Run: `python -m pytest -q -p no:cacheprovider --ignore=tests/integration --ignore=tests/system`
Expected: all pass (tests in `tests/integration` and `tests/system` need PostgreSQL, Redis, and S3).

Run: `ruff check sci_search tests && ruff format --check sci_search tests && pyright sci_search/model_provider.py sci_search/mistral_analysis.py sci_search/research_runs.py`
Expected: no ruff findings; pyright 0 errors.

Run: `grep -rn '"MISTRAL_API_KEY"' sci_search --include=*.py`
Expected: only `configuration.py` (legacy loader), `model_provider.py` (profile), and `worker_runtime.py` (secret files).

- [ ] **Step 3: Live check with OpenAI (manual, uses the owner's key)**

The owner's OpenAI key is in `../sci-graph/.env.local`. Pass it through the environment for this command only; do not copy it into any file.

```bash
SCI_SEARCH_ANALYSIS_PROVIDER=openai \
OPENAI_API_KEY="$(grep -E '^OPENAI_API_KEY=' ../sci-graph/.env.local | cut -d= -f2- | tr -d '"'"'"'")" \
python3 -m sci_search.cli --corpus corpora/goat_foraging research-online \
  --question "What influences goat foraging behaviour and diet selection?" \
  --per-query 10 --max-full-texts 5 --output "$SCRATCH/openai-goat.json"
```

Repeat with `--question "How does salinity affect tomato seed germination?"` and output `openai-tomato.json`. `$SCRATCH` is the session scratchpad directory.

Expected for each output: `result.ai_analysis.status == "complete"`, `provider == "openai"`, `method == "openai_structured_evidence_analysis_v1"`, `result.question_brief.provider == "openai"`. Then fill in the table in `docs/operations/contradiction-groups-quality-check.md` for every group in `result.ai_analysis.contradiction_groups`, and record the provider/model and date there.

- [ ] **Step 4: Mark the spec status and commit**

In the spec's first lines, replace `Status: design approved in conversation; awaiting written-spec review.` with `Status: implemented; live-checked with OpenAI gpt-4.1-mini on <date of Step 3>.`

```bash
git add .env.example README.md docs/superpowers/specs/2026-09-28-openai-analysis-provider-design.md docs/operations/contradiction-groups-quality-check.md
git commit -m "Document the OpenAI analysis provider and record its live check

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
