"""Conservative evidence adequacy for presentation, separate from run lifecycle."""

from typing import Any


def result_quality(investigation: dict[str, Any]) -> dict[str, Any]:
    data = investigation.get("data_analysis") or {}
    if data and (
        data.get("strategy", {}).get("route") == "both"
        or data.get("literature_status") == "complete"
    ):
        literature = result_quality(
            {k: v for k, v in investigation.items() if k != "data_analysis"}
        )
        has_evidence = bool(literature["qualifying_passages"] or data.get("analyses"))
        return {
            **literature,
            "status": "partial" if has_evidence else "insufficient",
            "label": "Partial combined evidence"
            if has_evidence
            else "Insufficient combined evidence",
            "explanation": literature["explanation"]
            + (
                " No supported numerical answer was obtained from the data sources."
                if not data.get("analyses")
                else " The numerical analysis has separate coverage limitations; inspect those alongside the literature."
            ),
        }
    if data.get("kind") == "discovered":
        blocked = not data.get("analyses")
        return {
            "status": "insufficient" if blocked else "partial",
            "label": "Numerical answer unavailable" if blocked else "Data coverage requires review",
            "explanation": "The data branch could not produce a supported numerical answer; inspect source decisions."
            if blocked
            else "Calculated observations are available. Inspect source definitions, selected entities and missing coverage before drawing conclusions.",
            "expert_validation": False,
            "qualifying_passages": 0,
            "validation_note": "Model-assisted source assessment is not expert validation. Literature, when requested, is assessed separately.",
        }
    if investigation.get("data_analysis"):
        return {
            "status": "partial",
            "label": "Data coverage limited",
            "explanation": "Numerical results describe the listed reporting panel; geographical, temporal and measurement limitations remain.",
            "qualifying_passages": 0,
            "expert_validation": False,
            "validation_note": "Reproducible calculations do not establish complete coverage or consistent reporting practices.",
        }
    review = (
        investigation.get("literature_review_report")
        or investigation.get("literature_review")
        or {}
    )
    adequacy = investigation.get("answer_adequacy") or review.get("answer_adequacy") or {}
    analysis = (
        investigation.get("ai_analysis") or (review.get("methodology") or {}).get("model") or {}
    )
    answer_withheld = analysis.get("answer_withheld") is True
    evidence = (
        investigation.get("evidence")
        or (review.get("appendices") or {}).get("evidence_records")
        or []
    )
    retained = {
        str(item["id"])
        for item in evidence
        if isinstance(item, dict)
        and item.get("id")
        and item.get("review_state") != "rejected"
        and item.get("validation_status") not in {"failed", "invalid", "rejected"}
    }
    qualifying = retained.intersection(
        str(item) for item in adequacy.get("qualifying_evidence_ids", [])
    )
    status = (
        "not_assessed"
        if not adequacy
        else "adequate"
        if adequacy.get("can_answer_overall_question") is True
        and qualifying
        and not answer_withheld
        else "partial"
        if qualifying
        else "insufficient"
    )
    label, explanation = {
        "adequate": (
            "Evidence covers the question",
            "The retained evidence passes the recorded coverage checks for this question.",
        ),
        "partial": (
            "Partial evidence",
            "Some qualifying evidence was found, but it does not support an overall answer to the complete question.",
        ),
        "insufficient": (
            "Insufficient evidence",
            "The retained evidence does not support an overall answer to the complete question.",
        ),
        "not_assessed": (
            "Evidence adequacy not recorded",
            "Evidence adequacy was not recorded for this saved result.",
        ),
    }[status]
    if answer_withheld:
        reason = str(
            analysis.get("answer_withheld_reason")
            or "The overall answer did not pass the support review."
        )
        explanation += f" Overall answer withheld: {reason}"
    return {
        "status": status,
        "label": label,
        "explanation": explanation,
        "qualifying_passages": len(qualifying),
        "expert_validation": False,
        "validation_note": "Source traceability and automated checks do not constitute expert scientific validation.",
    }
