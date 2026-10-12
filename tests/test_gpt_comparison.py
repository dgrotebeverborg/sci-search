import httpx
import pytest

from scripts.run_gpt_comparison import (
    MeasuredTransport,
    interpretation_checks,
    request_body,
    token_cost,
)


def test_ceiling_blocks_network_call_before_spending(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.run_gpt_comparison.httpx.post",
        lambda *a, **k: pytest.fail("network must not be called"),
    )
    transport = MeasuredTransport(tmp_path, "test-key", 0)
    with pytest.raises(RuntimeError, match="ceiling"):
        transport.call("job", {"model": "gpt-6-astra", "messages": []})


@pytest.mark.parametrize("failure", ["invalid_json", "protocol"])
def test_unaccounted_dispatched_response_stops_further_calls(tmp_path, monkeypatch, failure):
    def respond(*args, **kwargs):
        if failure == "protocol":
            raise httpx.RemoteProtocolError("connection closed")
        return httpx.Response(200, text="not JSON")

    monkeypatch.setattr("scripts.run_gpt_comparison.httpx.post", respond)
    transport = MeasuredTransport(tmp_path, "test-key", 15)
    body = {"model": "gpt-6-sol", "messages": []}
    with pytest.raises((ValueError, httpx.RemoteProtocolError)):
        transport.call("first", body)
    assert transport.unknown == 1
    with pytest.raises(RuntimeError, match="unknown billing"):
        transport.call("second", body)


def test_reasoning_request_keeps_prompt_and_schema_but_uses_supported_controls():
    original = {
        "model": "gpt-6-sol",
        "messages": [{"role": "user", "content": "question"}],
        "temperature": 0,
        "max_tokens": 2000,
        "response_format": {"type": "json_schema"},
    }
    actual = request_body(original)
    assert actual["messages"] == original["messages"]
    assert actual["response_format"] == original["response_format"]
    assert actual["reasoning_effort"] == "medium"
    assert actual["max_completion_tokens"] == 8000
    assert "temperature" not in actual and "max_tokens" not in actual
    assert original["max_tokens"] == 2000


def test_cost_counts_cached_input_and_all_billed_output():
    usage = {
        "prompt_tokens": 100000,
        "prompt_tokens_details": {"cached_tokens": 20000},
        "completion_tokens": 10000,
        "completion_tokens_details": {"reasoning_tokens": 6000},
    }
    assert token_cost("gpt-6-sol", usage) == pytest.approx(0.264)


def test_correct_words_in_wrong_roles_fail_interpretation():
    case = {
        "expected": {
            "subject_terms": [["diabetes"]],
            "driver_terms": [["green space"]],
            "geography_terms": [],
            "ambiguity": ["clear", "minor"],
        }
    }
    brief = {
        "method": "openai_structured_question_interpretation_v1",
        "ambiguity": "clear",
        "research_plan": {
            "subject_terms": ["green space"],
            "driver_terms": ["diabetes"],
            "geography_terms": ["Europe"],
        },
    }
    checks = interpretation_checks(case, brief)
    assert not checks["subject_terms"] and not checks["driver_terms"]
    assert not checks["geography_terms"]


def test_rule_fallback_is_not_successful_model_interpretation():
    case = {"expected": {"ambiguity": ["material"]}}
    checks = interpretation_checks(case, {"method": "deterministic", "ambiguity": "material"})
    assert not checks["model_response_used"]


def test_cache_writes_use_write_rate_instead_of_normal_input():
    usage = {
        "prompt_tokens": 100000,
        "prompt_tokens_details": {"cached_tokens": 20000, "cache_write_tokens": 10000},
        "completion_tokens": 10000,
    }
    assert token_cost("gpt-6-sol", usage) == pytest.approx(0.269)


def test_completed_empty_full_run_is_reported_without_synthesis(tmp_path):
    from scripts.run_gpt_comparison import dump, summarize

    dump(
        tmp_path / "results/empty.json",
        {
            "stage": "full",
            "model": "gpt-6-sol",
            "job": "test",
            "status": "complete",
            "result": {"evidence": [], "ai_analysis": {"status": "unavailable"}},
        },
    )
    row = summarize(tmp_path)[0]
    assert row["completed_runs"] == 1
    assert row["runs_with_evidence"] == 0
    assert row["synthesis_unavailable"] == 1
    assert row["synthesis_generation_calls"] == 0
