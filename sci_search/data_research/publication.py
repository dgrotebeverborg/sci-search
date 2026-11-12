"""One publication boundary for executed analyses and assessment transitions."""

import json
from pathlib import Path


def publish_analysis(
    analysis,
    folder,
    *,
    result,
    assessment,
    reason,
    overlap_policy,
    execute,
    check_cancelled,
    preserve_initial=False,
):
    """Execute before checking overlap, retaining existing observations unchanged.

    Initial/fallback extraction allows overlap; reassessment rejects a repeated
    source/measurement/entity combination, even when the proposed years differ.
    The executor is injected so workflow and review callers keep their test seams.
    """
    if overlap_policy not in {"allow", "reject_source_series"}:
        raise ValueError("Unknown publication overlap policy")
    analysis = execute(analysis, folder, check_cancelled=check_cancelled)
    if overlap_policy == "reject_source_series":
        existing = {
            (a["source"]["sha256"], s["label"], s["entity"])
            for a in result["analyses"]
            for s in a.get("series", [])
        }
        keys = {(analysis["source"]["sha256"], s["label"], s["entity"]) for s in analysis["series"]}
        if keys & existing:
            raise ValueError(
                "Reassessment overlaps already retained series; existing results preserved"
            )
    (Path(folder) / "analysis.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result["analyses"].append(analysis)
    failure_fields = (
        "failure_stage",
        "failure_category",
        "error_class",
        "diagnostic",
        "python_error",
        "recovery_failure",
    )
    if preserve_initial or any(key in assessment for key in failure_fields):
        assessment.setdefault(
            "initial_assessment",
            {k: assessment.get(k) for k in ("decision", "reason", "availability", *failure_fields)},
        )
    assessment.update(decision="analysed", reason=reason, source=analysis["source"])
    assessment.pop("availability", None)
    for key in failure_fields:
        assessment.pop(key, None)
    return analysis
