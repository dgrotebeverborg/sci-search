"""Validated, provenance-preserving structure over generic extracted evidence."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any


def build_structured_synthesis(investigation: dict[str, Any]) -> dict[str, Any]:
    """Build a conservative cross-paper view without generating new scientific claims."""
    evidence = [item for item in investigation.get("evidence", []) if isinstance(item, dict)]
    findings = [item for item in investigation.get("findings", []) if isinstance(item, dict)]
    by_id = {str(item.get("id")): item for item in evidence}
    claims: list[dict[str, Any]] = []
    for finding in findings:
        ids = [str(value) for value in finding.get("evidence_ids", []) if str(value) in by_id]
        statement = str(finding.get("statement") or "").strip()
        if not statement or not ids:
            continue
        # Validation is intentionally strict: promoted statements must occur in
        # every linked source passage. No detached paraphrase enters synthesis.
        if not all(statement in str(by_id[item_id].get("passage") or "") for item_id in ids):
            continue
        claims.append(
            {
                "id": str(finding.get("id") or f"claim:{len(claims) + 1}"),
                "statement": statement,
                "status": str(finding.get("status") or "source_reported"),
                "evidence_ids": ids,
                "publication_ids": sorted(
                    {str(by_id[item_id].get("publication_id")) for item_id in ids}
                ),
            }
        )

    evidence_types = Counter(str(item.get("evidence_type") or "unknown") for item in evidence)
    study_designs = Counter(str(item.get("study_design") or "unknown") for item in evidence)
    publications = {str(item.get("publication_id")) for item in evidence}
    numerical = [item for item in evidence if item.get("numerical_mentions")]
    clusters = _claim_clusters(claims)
    quality_flags: list[str] = []
    if len(publications) < 3:
        quality_flags.append("fewer_than_three_contributing_publications")
    if len(claims) < 2:
        quality_flags.append("insufficient_claims_for_cross_paper_convergence")
    if numerical:
        quality_flags.append("numerical_results_require_manual_context_comparability_review")
    if evidence and all(str(item.get("evidence_type")) == "review" for item in evidence):
        quality_flags.append("secondary_evidence_only")

    result = {
        "schema_version": "1.0",
        "method": "validated_extractive_synthesis_v1",
        "claims": claims,
        "convergence_clusters": clusters,
        "evidence_distribution": {
            "publications": len(publications),
            "passages": len(evidence),
            "evidence_types": dict(sorted(evidence_types.items())),
            "study_designs": dict(sorted(study_designs.items())),
        },
        "comparability": {
            "numerical_passages": len(numerical),
            "status": "manual_context_review_required"
            if numerical
            else "no_numerical_comparison_attempted",
            "evidence_ids": [str(item.get("id")) for item in numerical],
        },
        "quality_flags": quality_flags,
        "validation": {
            "all_claims_have_evidence": all(claim["evidence_ids"] for claim in claims),
            "all_claims_are_exact_source_text": True,
            "arbitrary_universal_score_used": False,
        },
    }
    validate_structured_synthesis(result, by_id)
    return result


def validate_structured_synthesis(
    synthesis: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]
) -> None:
    for claim in synthesis.get("claims", []):
        statement = str(claim.get("statement") or "")
        ids = claim.get("evidence_ids") or []
        if not statement or not ids:
            raise ValueError("synthesis claims require a statement and evidence")
        for evidence_id in ids:
            evidence = evidence_by_id.get(str(evidence_id))
            if evidence is None or statement not in str(evidence.get("passage") or ""):
                raise ValueError("synthesis claim is detached from its source passage")


def _claim_clusters(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for claim in claims:
        tokens = _tokens(claim["statement"])
        target = next((item for item in clusters if _jaccard(tokens, item["_tokens"]) >= 0.6), None)
        if target is None:
            target = {
                "id": f"cluster:{len(clusters) + 1}",
                "claim_ids": [],
                "evidence_ids": [],
                "publication_ids": [],
                "_tokens": tokens,
            }
            clusters.append(target)
        target["claim_ids"].append(claim["id"])
        target["evidence_ids"] = sorted(set(target["evidence_ids"]) | set(claim["evidence_ids"]))
        target["publication_ids"] = sorted(
            set(target["publication_ids"]) | set(claim["publication_ids"])
        )
    for cluster in clusters:
        cluster.pop("_tokens", None)
        cluster["independent_publication_count"] = len(cluster["publication_ids"])
        cluster["status"] = (
            "multi_publication_pattern"
            if len(cluster["publication_ids"]) > 1
            else "single_publication_signal"
        )
    return clusters


def _tokens(text: str) -> set[str]:
    stop = {
        "a",
        "an",
        "and",
        "at",
        "by",
        "for",
        "in",
        "is",
        "of",
        "on",
        "the",
        "to",
        "was",
        "were",
        "with",
    }
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if token not in stop}


def _jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left or right else 0.0
