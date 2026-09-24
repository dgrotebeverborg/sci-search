from __future__ import annotations

import json

from sci_search.application.analysis import (
    MistralAnalysisProvider,
    analyze_evidence,
)
from sci_search.mistral_analysis import MistralAnalyzer
from sci_search.research.model_evidence import select_model_evidence


def _evidence() -> list[dict[str, object]]:
    statement = "Measured efficiency was 70% at laboratory scale."
    return [
        {
            "id": "e1",
            "publication_id": "p1",
            "statement": statement,
            "passage": statement,
            "evidence_type": "laboratory_experiment",
        }
    ]


def _payload(*, evidence_id: str = "e1", quote: str | None = None) -> dict[str, object]:
    source_quote = quote or "Measured efficiency was 70% at laboratory scale."
    assertion = {
        "text": "Laboratory efficiency was reported as 70%.",
        "evidence_ids": [evidence_id],
        "quotes": [{"evidence_id": evidence_id, "quote": source_quote}],
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
    }


def _response(payload: object) -> dict[str, object]:
    return {
        "choices": [{"message": {"content": json.dumps(payload)}}],
        "usage": {"prompt_tokens": 90, "completion_tokens": 30, "total_tokens": 120},
    }


def _provider(payload: object) -> MistralAnalysisProvider:
    analyzer = MistralAnalyzer(
        "secret",
        model="mistral-contract-test",
        complete_json=lambda body, headers: _response(payload),
    )
    return MistralAnalysisProvider(analyzer)


def test_provider_success_records_reproducibility_contract() -> None:
    packet = select_model_evidence(_evidence(), {"can_answer_overall_question": True})

    result = _provider(_payload()).analyze("What efficiency was reported?", packet)

    assert result.status == "complete"
    assert result.provider == "mistral"
    assert result.model == "mistral-contract-test"
    assert result.packet_policy == "diverse_model_evidence_v1"
    assert result.prompt_contract
    assert result.schema_version == "scientific_analysis_v2"
    assert result.validator_version
    assert result.usage["total_tokens"] == 120
    assert result.analysis["answer"]["evidence_ids"] == ["e1"]


def test_provider_error_returns_explicit_deterministic_fallback() -> None:
    analyzer = MistralAnalyzer(
        "secret",
        complete_json=lambda body, headers: (_ for _ in ()).throw(TimeoutError("offline")),
    )

    result = analyze_evidence(
        "What efficiency was reported?",
        _evidence(),
        {},
        MistralAnalysisProvider(analyzer),
    )

    assert result["status"] == "unavailable"
    assert result["method"] == "deterministic_extractive_fallback"
    assert "TimeoutError" in result["fallback_reason"]
    assert result["evidence_packet"]["selected_ids"] == ["e1"]


def test_malformed_structure_is_rejected() -> None:
    result = analyze_evidence("Question", _evidence(), {}, _provider({"answer": {}}))
    assert result["status"] == "unavailable"
    assert "must be a list" in result["fallback_reason"]


def test_invalid_quote_is_rejected() -> None:
    result = analyze_evidence(
        "Question", _evidence(), {}, _provider(_payload(quote="This quote is not in the source."))
    )
    assert result["status"] == "unavailable"
    assert "source passage" in result["fallback_reason"]


def test_unknown_evidence_reference_is_rejected() -> None:
    result = analyze_evidence("Question", _evidence(), {}, _provider(_payload(evidence_id="e999")))
    assert result["status"] == "unavailable"
    assert "unknown evidence" in result["fallback_reason"]


def test_empty_grounded_result_is_rejected() -> None:
    payload = _payload()
    payload["answer"] = {"text": "Insufficient evidence", "evidence_ids": [], "quotes": []}
    payload["claims"] = []

    result = analyze_evidence("Question", _evidence(), {}, _provider(payload))

    assert result["status"] == "unavailable"
    assert "no grounded answer" in result["fallback_reason"]
