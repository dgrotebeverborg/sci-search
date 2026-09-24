"""Provider-neutral orchestration for grounded scientific analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from sci_search.mistral_analysis import MistralAnalyzer, unavailable_analysis
from sci_search.research.model_evidence import (
    EvidencePacket,
    EvidenceSelectionLimits,
    select_model_evidence,
)

PROMPT_CONTRACT_VERSION = "scientific_analysis_prompt_v3"
VALIDATOR_VERSION = "exact_source_grounding_v2"
SCHEMA_VERSION = "scientific_analysis_v2"


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Validated model analysis plus the data needed to reproduce and audit it."""

    status: str
    analysis: dict[str, Any]
    provider: str | None
    model: str | None
    packet_policy: str
    prompt_contract: str
    schema_version: str
    validator_version: str
    usage: dict[str, Any] = field(default_factory=dict)
    rejected_records: tuple[dict[str, Any], ...] = ()
    fallback_reason: str | None = None
    evidence_packet: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = dict(self.analysis)
        payload.update(
            {
                "status": self.status,
                "provider": self.provider,
                "model": self.model,
                "schema_version": self.schema_version,
                "prompt_contract": self.prompt_contract,
                "validator_version": self.validator_version,
                "packet_policy": self.packet_policy,
                "usage": dict(self.usage),
                "rejected_records": [dict(item) for item in self.rejected_records],
                "fallback_reason": self.fallback_reason,
                "evidence_packet": dict(self.evidence_packet),
            }
        )
        return payload


class AnalysisProvider(Protocol):
    provider_name: str
    model_name: str

    def analyze(self, question: str, packet: EvidencePacket) -> AnalysisResult: ...


class MistralAnalysisProvider:
    provider_name = "mistral"

    def __init__(self, analyzer: MistralAnalyzer) -> None:
        self.analyzer = analyzer
        self.model_name = analyzer.model

    def analyze(self, question: str, packet: EvidencePacket) -> AnalysisResult:
        payload = self.analyzer.analyze(question, packet)
        rejected = tuple(
            dict(item) for item in payload.get("rejected_records", []) if isinstance(item, dict)
        )
        return AnalysisResult(
            status="complete",
            analysis=payload,
            provider=self.provider_name,
            model=self.model_name,
            packet_policy=packet.policy_version,
            prompt_contract=PROMPT_CONTRACT_VERSION,
            schema_version=SCHEMA_VERSION,
            validator_version=VALIDATOR_VERSION,
            usage=dict(payload.get("usage") or {}),
            rejected_records=rejected,
            evidence_packet=_packet_record(packet),
        )


def analyze_evidence(
    question: str,
    evidence: list[dict[str, Any]],
    adequacy: dict[str, Any],
    provider: AnalysisProvider,
    *,
    limits: EvidenceSelectionLimits | None = None,
) -> dict[str, Any]:
    """Select evidence before the provider call and preserve a safe fallback."""

    packet = select_model_evidence(evidence, adequacy, limits)
    if not packet.selected_records:
        return fallback_analysis(
            packet,
            "no evidence passages were available for model analysis",
            provider=provider.provider_name,
            model=provider.model_name,
        ).as_dict()
    try:
        return provider.analyze(question, packet).as_dict()
    except Exception as exc:
        return fallback_analysis(
            packet,
            f"validated model analysis failed: {type(exc).__name__}: {str(exc)[:300]}",
            provider=provider.provider_name,
            model=provider.model_name,
        ).as_dict()


def fallback_analysis(
    packet: EvidencePacket,
    reason: str,
    *,
    provider: str | None,
    model: str | None,
) -> AnalysisResult:
    payload = unavailable_analysis(reason)
    return AnalysisResult(
        status="unavailable",
        analysis=payload,
        provider=provider,
        model=model,
        packet_policy=packet.policy_version,
        prompt_contract=PROMPT_CONTRACT_VERSION,
        schema_version=SCHEMA_VERSION,
        validator_version=VALIDATOR_VERSION,
        fallback_reason=reason,
        evidence_packet=_packet_record(packet),
    )


def _packet_record(packet: EvidencePacket) -> dict[str, Any]:
    return {
        "policy_version": packet.policy_version,
        "selected_ids": list(packet.selected_ids),
        "excluded": [
            {"evidence_id": item.evidence_id, "reason": item.reason} for item in packet.exclusions
        ],
        "selection_reasons": {key: list(value) for key, value in packet.selection_reasons.items()},
        "estimated_tokens": packet.estimated_tokens,
        "max_records": packet.max_records,
        "max_tokens": packet.max_tokens,
        "publication_count": packet.publication_count,
        "evidence_type_count": packet.evidence_type_count,
        "coverage_complete": packet.coverage_complete,
        "missing_requirements": list(packet.missing_requirements),
    }
