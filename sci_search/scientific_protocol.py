"""Locked, budgeted and sanitized scheduled scientific regression contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sci_search.researcher_benchmark import validate_researcher_benchmark


@dataclass(frozen=True, slots=True)
class ScheduledScientificProtocol:
    version: int
    question_sha256: str
    case_ids: tuple[str, ...]
    per_query: int
    max_full_texts: int
    max_acquisition_attempts: int
    max_model_calls_per_case: int
    scientific_status: str
    artifact_retention_days: int


def load_protocol(path: Path, question_benchmark: Path) -> ScheduledScientificProtocol:
    payload = json.loads(path.read_text(encoding="utf-8"))
    contract = validate_researcher_benchmark(question_benchmark)
    if contract["failed"] or payload.get("question_sha256") != contract["question_sha256"]:
        raise ValueError("scheduled protocol question version does not match the locked benchmark")
    benchmark = json.loads(question_benchmark.read_text(encoding="utf-8"))
    known_cases = {str(item.get("id")) for item in benchmark.get("cases", [])}
    case_ids = tuple(str(item) for item in payload.get("case_ids", []))
    if not case_ids or len(case_ids) != len(set(case_ids)) or not set(case_ids) <= known_cases:
        raise ValueError("scheduled protocol case IDs must be unique locked benchmark cases")
    budgets = payload.get("budgets") if isinstance(payload.get("budgets"), dict) else {}
    protocol = ScheduledScientificProtocol(
        version=int(payload.get("version") or 0),
        question_sha256=str(payload.get("question_sha256") or ""),
        case_ids=case_ids,
        per_query=int(budgets.get("per_query") or 0),
        max_full_texts=int(budgets.get("max_full_texts") or 0),
        max_acquisition_attempts=int(budgets.get("max_acquisition_attempts") or 0),
        max_model_calls_per_case=int(budgets.get("max_model_calls_per_case") or 0),
        scientific_status=str(payload.get("scientific_status") or ""),
        artifact_retention_days=int(payload.get("artifact_retention_days") or 0),
    )
    if protocol.version != 1:
        raise ValueError("unsupported scheduled scientific protocol version")
    if not (1 <= protocol.per_query <= 10):
        raise ValueError("scheduled discovery budget exceeds its safety bound")
    if not (1 <= protocol.max_full_texts <= 5):
        raise ValueError("scheduled full-text budget exceeds its safety bound")
    if not (1 <= protocol.max_acquisition_attempts <= 10):
        raise ValueError("scheduled acquisition budget exceeds its safety bound")
    if protocol.max_model_calls_per_case != 1:
        raise ValueError("scheduled model calls must be limited to one per case")
    if protocol.scientific_status != "informational_pending_researcher_review":
        raise ValueError("live provider outcomes must remain informational")
    if not (7 <= protocol.artifact_retention_days <= 30):
        raise ValueError("scheduled artifact retention must be between 7 and 30 days")
    return protocol


_RESULT_FIELDS = {
    "case_id",
    "tier",
    "question",
    "run_id",
    "run_status",
    "answer_policy",
    "answer_adequacy",
    "answer_withheld",
    "full_texts_analyzed",
    "contributing_publications",
    "selected_passages",
    "citation_ids_valid",
    "model_status",
    "pipeline_warnings",
    "must_distinguish",
    "manual_scientific_appraisal",
}


def sanitize_live_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Allowlist diagnostics; omit passages, provider payloads, URLs and credentials."""

    raw_rows = payload.get("results")
    rows = cast(list[Any], raw_rows) if isinstance(raw_rows, list) else []
    return {
        "schema_version": "sci_search_scheduled_scientific_result_v1",
        "question_sha256": str(payload.get("question_sha256") or ""),
        "scientific_validation_status": "informational_pending_researcher_review",
        "completed_cases": len(rows),
        "results": [
            {key: item[key] for key in sorted(_RESULT_FIELDS) if key in item}
            for item in rows
            if isinstance(item, dict)
        ],
    }
