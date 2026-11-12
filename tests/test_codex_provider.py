"""Exercise the CLI boundary with a real subprocess, without model/network calls."""

import json
import os
import sys
from pathlib import Path

import pytest

from sci_search.model_provider import analysis_choices, analysis_scope, configured_analyzer


@pytest.fixture
def fake_codex(tmp_path, monkeypatch):
    capture = tmp_path / "capture.json"

    def install(*, result=None, events=None, exit_code=0, delay=0, login="ChatGPT"):
        executable = tmp_path / "codex"
        executable.write_text(
            f"#!{sys.executable}\n"
            "import json, sys, time, os\nfrom pathlib import Path\n"
            f'if "login" in sys.argv:\n print("Logged in using {login}"); sys.exit(0)\n'
            f'Path({str(capture)!r}).write_text(json.dumps({{"args":sys.argv, "prompt":sys.stdin.read(), "env":dict(os.environ), "cwd":os.getcwd(), "schema":json.loads(Path(sys.argv[sys.argv.index("--output-schema")+1]).read_text())}}))\n'
            f"time.sleep({delay})\n"
            f"events={events if events is not None else [{'type': 'turn.completed', 'usage': {'input_tokens': 12, 'output_tokens': 3}}]!r}\n"
            "for event in events: print(json.dumps(event), flush=True)\n"
            f"result={json.dumps(result if result is not None else {'ok': True})!r}\n"
            'if "--output-last-message" in sys.argv:\n Path(sys.argv[sys.argv.index("--output-last-message")+1]).write_text(result)\n'
            f"sys.exit({exit_code})\n"
        )
        executable.chmod(0o700)
        return capture

    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("SCI_SEARCH_CODEX_ENABLED", "1")
    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_PROVIDER", "codex")
    monkeypatch.delenv("SCI_SEARCH_ANALYSIS_MODELS", raising=False)
    install()
    return install


def body():
    return {
        "model": "gpt-6-sol",
        "messages": [{"role": "user", "content": "Assess this evidence."}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "test",
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["ok"],
                    "properties": {"ok": {"type": "boolean"}},
                },
            },
        },
    }


def test_codex_catalog_requires_explicit_enable_and_chatgpt_login(fake_codex, monkeypatch):
    assert any(i["provider"] == "codex" and i["available"] for i in analysis_choices()["items"])
    monkeypatch.setenv("SCI_SEARCH_CODEX_ENABLED", "0")
    assert not any(i["provider"] == "codex" and i["available"] for i in analysis_choices()["items"])
    assert configured_analyzer() is None


def test_api_key_login_is_not_chatgpt_provider(fake_codex):
    fake_codex(login="an API key")
    assert configured_analyzer() is None


def test_cli_completion_preserves_contract_and_excludes_secrets(fake_codex, monkeypatch):
    capture = fake_codex()
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-cli")
    monkeypatch.setenv("MISTRAL_API_KEY", "must-not-reach-cli")
    analyzer = configured_analyzer()
    result = analyzer.complete_json(body(), {"Authorization": "Bearer must-not-reach-cli"})
    assert json.loads(result["choices"][0]["message"]["content"]) == {"ok": True}
    assert result["usage"]["prompt_tokens"] == 12
    assert result["usage"]["completion_tokens"] == 3
    request = json.loads(capture.read_text())
    assert "must-not-reach-cli" not in json.dumps(request)
    assert request["cwd"] != str(Path.cwd())
    assert "--output-schema" in request["args"]
    assert "read-only" in request["args"]
    assert 'web_search="disabled"' in request["args"]
    assert "features.shell_tool=false" in request["args"]
    assert "Assess this evidence." in request["prompt"]
    assert not Path(request["cwd"]).exists()


@pytest.mark.parametrize(
    "events,exit_code",
    [
        ([{"type": "turn.failed", "error": {"message": "private diagnostics"}}], 1),
        ([{"type": "error", "message": "private diagnostics"}], 0),
        ([], 0),
    ],
)
def test_failed_or_incomplete_cli_is_not_success(fake_codex, events, exit_code):
    fake_codex(events=events, exit_code=exit_code)
    with pytest.raises((OSError, ValueError), match="Codex") as exc:
        configured_analyzer().complete_json(body(), {})
    assert "private diagnostics" not in str(exc.value)


def test_non_object_response_rejected(fake_codex):
    fake_codex(result=["wrong"])
    with pytest.raises(ValueError, match="object"):
        configured_analyzer().complete_json(body(), {})


def test_timeout_stops_process(fake_codex, monkeypatch):
    from sci_search import codex_provider

    fake_codex(delay=5)
    monkeypatch.setattr(codex_provider, "REQUEST_TIMEOUT", 0.1)
    with pytest.raises(TimeoutError, match="Codex"):
        configured_analyzer().complete_json(body(), {})


def test_codex_search_provenance_excludes_model_only_urls(fake_codex):
    from sci_search.data_research.discovery import discover

    url = "https://example.org/official-data"
    fake_codex(
        result={
            "candidates": [
                {
                    "title": "Observed",
                    "url": url,
                    "landing_url": url,
                    "publisher": "Agency",
                    "rationale": "Annual data",
                }
            ]
        },
        events=[
            {
                "type": "item.completed",
                "item": {
                    "type": "web_search",
                    "id": "s1",
                    "action": {"type": "search", "query": "annual"},
                    "results": [{"type": "text_result", "url": url}],
                },
            },
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "https://invented.example/data"},
            },
            {"type": "turn.completed", "usage": {"input_tokens": 20, "output_tokens": 5}},
        ],
    )
    result = discover("Question", {}, analyzer=configured_analyzer())
    assert [c["url"] for c in result["candidates"]] == [url]
    assert result["observed_urls"] == [url]
    assert result["provider"] == "codex"
    assert result["search_actions"][0]["sources"] == [{"url": url}]


def test_search_without_tool_provenance_does_not_accept_urls(fake_codex):
    from sci_search.data_research.discovery import discover

    fake_codex(result={"candidates": [{"url": "https://invented.example/data"}]})
    result = discover("Question", {}, analyzer=configured_analyzer())
    assert result["candidates"] == []
    assert result["rejected"][0]["reason"] == "URL was not observed by the search tool"


def test_provider_selection_is_scoped_and_accepted_by_api(fake_codex, monkeypatch):
    from sci_search.api.schemas import AnalysisSelection

    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_PROVIDER", "mistral")
    selection = AnalysisSelection(provider="codex", model="gpt-6-sol").model_dump()
    with analysis_scope(selection):
        assert configured_analyzer().provider.name == "codex"
    assert analysis_choices()["default"]["provider"] == "mistral"


def test_production_does_not_use_personal_codex_login(fake_codex, monkeypatch):
    monkeypatch.setenv("SCI_SEARCH_ENVIRONMENT", "production")
    assert configured_analyzer() is None


def test_missing_cli_is_unavailable(monkeypatch):
    monkeypatch.setenv("SCI_SEARCH_CODEX_ENABLED", "1")
    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_PROVIDER", "codex")
    monkeypatch.setenv("PATH", "/nonexistent-sci-search-test")
    assert configured_analyzer() is None


def test_search_budget_is_enforced(fake_codex):
    from sci_search.codex_provider import search_datasets

    fake_codex(
        events=[
            {"type": "item.started", "item": {"type": "web_search", "id": str(i)}} for i in range(6)
        ]
    )
    with pytest.raises(ValueError, match="web-search budget"):
        search_datasets("Find data", "gpt-6-sol")


def test_codex_evidence_still_rejects_invented_quotes(fake_codex):
    from tests.test_model_provider import _evidence, _payload

    payload = _payload()
    payload["answer"]["quotes"][0]["quote"] = (
        "An invented quotation that is not present in the evidence."
    )
    fake_codex(result=payload)
    with pytest.raises(ValueError, match="quote is not present"):
        configured_analyzer().analyze("What was the measured efficiency?", _evidence())


def test_optional_schema_fields_are_nullable_and_required_for_codex(fake_codex):
    capture = fake_codex()
    request = body()
    schema = request["response_format"]["json_schema"]["schema"]
    schema["properties"]["note"] = {"type": "string"}
    configured_analyzer().complete_json(request, {})
    sent = json.loads(capture.read_text())["schema"]
    assert sent["required"] == ["ok", "note"]
    assert sent["properties"]["note"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert schema["required"] == ["ok"]


def test_capacity_failure_is_actionable_in_question_brief(fake_codex):
    from sci_search.question_interpretation import interpret_question

    fake_codex(
        events=[
            {
                "type": "turn.failed",
                "error": {
                    "message": "Selected model is at capacity. Please try a different model."
                },
            }
        ],
        exit_code=1,
    )
    brief = interpret_question("How does salinity affect tomato germination?")
    assert brief["ambiguity"] == "material"
    assert "capacity" in brief["clarification_question"]
    assert "Analysis model" in brief["clarification_question"]


def test_invalid_codex_plan_gets_one_validated_repair_attempt():
    from sci_search.mistral_analysis import ModelAnalyzer
    from sci_search.model_provider import PROFILES
    from sci_search.question_interpretation import interpret_question

    payload = {
        "interpreted_question": "How have electricity shares changed and what factors are associated?",
        "objective": "Compare changes and associated factors.",
        "ambiguity": "clear",
        "research_plan": {
            "intent": "temporal_trend",
            "relationship_type": "association",
            "subject_terms": ["renewable electricity share"],
            "driver_terms": ["associated factors"],
            "geography_terms": ["Netherlands", "Germany", "Denmark"],
            "exclusion_terms": [],
            "evidence_preferences": [],
        },
    }
    requests = []

    def complete(body, headers):
        requests.append(body)
        if len(requests) == 2:
            payload["research_plan"]["intent"] = "relationship"
        return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    analyzer = ModelAnalyzer("", provider=PROFILES["codex"], complete_json=complete)
    brief = interpret_question(
        "How have renewable electricity shares changed in the Netherlands, Germany, and Denmark since 2000, and what factors are associated?",
        analyzer,
    )
    assert brief["provider"] == "codex"
    assert brief["research_plan"]["intent"] == "relationship"
    assert brief["research_plan"]["geography_terms"] == ["Netherlands", "Germany", "Denmark"]
    assert len(requests) == 2
    assert "separate factor and outcome" in requests[1]["messages"][1]["content"]


def test_invalid_codex_plan_repair_is_bounded():
    from sci_search.mistral_analysis import ModelAnalyzer
    from sci_search.model_provider import PROFILES
    from sci_search.question_interpretation import interpret_question

    requests = []

    def complete(body, headers):
        requests.append(body)
        return {"choices": [{"message": {"content": "{}"}}]}

    brief = interpret_question(
        "How does salinity affect tomato germination?",
        ModelAnalyzer("", provider=PROFILES["codex"], complete_json=complete),
    )
    assert brief["ambiguity"] == "material"
    assert brief["provider"] is None
    assert len(requests) == 2
