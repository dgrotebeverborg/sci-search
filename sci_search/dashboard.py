"""Pure, versioned presentation contract for fresh and saved scientific results."""

import logging
from copy import deepcopy
from typing import Any

from sci_search.result_quality import result_quality
from sci_search.result_summary import summarize

logger = logging.getLogger(__name__)


def build_dashboard(investigation: dict[str, Any], *, run_id: str, revision: int) -> dict[str, Any]:
    """Map retained results without inference, model calls, or mutation of evidence."""
    source = deepcopy(investigation)
    review = source.get("literature_review_report") or {}
    if not review and (source.get("literature_review") or {}).get("executive_summary"):
        review = source["literature_review"]
    ai = source.get("ai_analysis") or {}
    retained_model = (review.get("methodology") or {}).get("model") or {}
    analysis = ai or retained_model
    reviewed_findings = (
        analysis.get("status") in {"complete", "coverage_limited"}
        or analysis.get("answer_withheld") is True
        or isinstance(analysis.get("semantic_review"), dict)
    )
    run = source.get("research_run") or {}
    synthesis = source.get("synthesis") or {}
    matrix = source.get("study_matrix") or {}
    studies = {str(s.get("publication_id")): s for s in matrix.get("studies", [])}
    screening = {str(s.get("publication_id")): s for s in run.get("full_text_screening", [])}
    acquired_ids = {
        str(item.get("publication_id"))
        for item in run.get("acquisitions", [])
        if item.get("status") == "acquired"
    }
    acquired_ids.update(str(item.get("publication_id")) for item in source.get("evidence", []))
    for paper in run.get("candidates", []):
        publication_id = str(paper.get("id") or paper.get("publication_id") or "")
        if publication_id and publication_id not in studies:
            studies[publication_id] = {
                **paper,
                "publication_id": publication_id,
                "screening": screening.get(publication_id, {}),
                "full_text_available": publication_id in acquired_ids,
            }
    landscape = source.get("research_landscape") or review.get("research_landscape") or {}
    if landscape:
        landscape["papers"] = list(studies.values())
    evidence = source.get("evidence") or []
    blocks: list[dict[str, Any]] = []

    def add(identifier: str, data: Any, *, present: bool = True) -> None:
        meaningful = any(bool(v) for v in data.values()) if isinstance(data, dict) else bool(data)
        status = "unavailable" if not present else "ready" if meaningful else "empty"
        blocks.append(
            {
                "id": identifier,
                "status": status,
                "data": data,
                "explanation": ""
                if status == "ready"
                else f"No {identifier.replace('_', ' ')} was retained for this revision.",
            }
        )

    add(
        "scope",
        {
            "question_brief": source.get("question_brief") or review.get("question_interpretation"),
            "research_scope": source.get("research_scope"),
            "plan": source.get("plan") or review.get("scope"),
        },
    )
    add(
        "answer",
        {
            "data_analysis": source.get("data_analysis"),
            "investigation_review": source.get("investigation_review"),
            "answer_adequacy": source.get("answer_adequacy") or review.get("answer_adequacy"),
            "synthesis": synthesis,
            "answer_contest": review.get("answer_contest"),
            "executive_summary": {
                "text": analysis.get("answer_withheld_reason")
                or "The overall answer did not pass the support review.",
                "evidence_ids": [],
            }
            if analysis.get("answer_withheld") is True
            else review.get("executive_summary")
            or (
                {
                    "text": source["answer_summary"],
                    "evidence_ids": source.get("summary_evidence_ids") or [],
                }
                if source.get("answer_summary")
                else None
            ),
        },
    )
    add("literature_review", review, present=bool(review))
    add(
        "findings",
        {
            # An empty reviewed result is a decision, not permission to restore
            # findings from the extraction performed before semantic review.
            "claims": review.get("findings", ai.get("claims", []))
            if reviewed_findings
            else synthesis.get("claims") or source.get("findings") or review.get("findings"),
            "thematic_findings": review.get("thematic_findings"),
            "measurements": review.get("measurements"),
        },
    )
    add(
        "comparisons",
        {
            "contradiction_groups": review.get("contradiction_groups"),
            "comparison_groups": source.get("comparisons") or synthesis.get("convergence_clusters"),
            "comparability": synthesis.get("comparability"),
            "measurements": review.get("measurements"),
        },
    )
    add("landscape", landscape, present=bool(landscape))
    add("studies", {**matrix, "studies": list(studies.values())})
    add(
        "gaps",
        {
            "limitations": (review.get("quality") or {}).get("limitations")
            or source.get("limitations"),
            "quality_flags": synthesis.get("quality_flags"),
            "follow_up_questions": source.get("follow_up_questions")
            or review.get("research_implications"),
        },
    )
    add(
        "methods",
        {
            "methodology": review.get("methodology"),
            "selection_flow": review.get("selection_flow"),
            "research_run": run,
        },
    )
    add("evidence", evidence)
    add(
        "validation",
        {
            "summary": source.get("validation") or synthesis.get("validation"),
            "records": [
                {
                    "evidence_id": e.get("id"),
                    "validation": e.get("validation"),
                    "validation_status": e.get("validation_status"),
                    "validation_checks": e.get("validation_checks"),
                    "validator_version": e.get("validator_version"),
                    "review_state": e.get("review_state"),
                }
                for e in evidence
            ],
        },
    )
    add("references", review.get("references") or [])
    add("downloads", source.get("artifacts") or [])
    snapshot = {
        "result_quality": result_quality(source),
        "analysis": {
            "selection": source.get("analysis_selection"),
            "provider": ai.get("provider") or retained_model.get("provider"),
            "model": ai.get("model") or retained_model.get("name"),
            "status": ai.get("status") or retained_model.get("status"),
            "method": ai.get("method") or retained_model.get("method"),
            "fallback_reason": ai.get("fallback_reason") or ai.get("reason"),
        },
        "schema_version": "research_dashboard_v1",
        "layout_version": 1,
        "run_id": run_id,
        "revision": revision,
        "question": source.get("question", ""),
        "blocks": blocks,
    }
    try:
        snapshot["summary"] = summarize(snapshot)
    except Exception:  # the read route recomputes it; a summary must never block a revision
        logger.exception("Result summary failed for run %s", run_id)
        snapshot["summary"] = None
    return snapshot
