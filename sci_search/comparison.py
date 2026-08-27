"""Context-aware comparison of scientific measurements."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from sci_search.energy import METRICS
from sci_search.models import Condition, MeasurementResult, dataclass_to_dict


class ComparabilityStatus(StrEnum):
    COMPARABLE = "comparable"
    DIFFERENT_CONTEXT = "different_context"
    INSUFFICIENT_CONTEXT = "insufficient_context"


@dataclass(frozen=True, slots=True)
class ContextDifference:
    field: str
    left: str | None
    right: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class PairComparison:
    left_result_id: str
    right_result_id: str
    status: ComparabilityStatus
    differences: tuple[ContextDifference, ...] = ()
    missing_context: tuple[str, ...] = ()


def compare_pair(left: MeasurementResult, right: MeasurementResult) -> PairComparison:
    if left.metric != right.metric:
        raise ValueError("results must measure the same metric")
    definition = METRICS[left.metric]
    differences: list[ContextDifference] = []
    missing: list[str] = []
    for field_name in definition.required_context:
        left_value = _context_value(left, field_name)
        right_value = _context_value(right, field_name)
        if left_value is None or right_value is None:
            missing.append(field_name)
            continue
        tolerance = definition.tolerance(field_name)
        if not _equivalent(left_value, right_value, tolerance):
            differences.append(
                ContextDifference(
                    field_name, _display(left_value), _display(right_value), "context values differ"
                )
            )
    if differences:
        status = ComparabilityStatus.DIFFERENT_CONTEXT
    elif missing:
        status = ComparabilityStatus.INSUFFICIENT_CONTEXT
    else:
        status = ComparabilityStatus.COMPARABLE
    return PairComparison(
        left.id, right.id, status, tuple(differences), tuple(sorted(set(missing)))
    )


def comparison_report(results: tuple[MeasurementResult, ...]) -> dict[str, object]:
    if not results:
        return {
            "metric": None,
            "results": [],
            "pairwise_comparisons": [],
            "warnings": ["no_results"],
        }
    metrics = {result.metric for result in results}
    if len(metrics) != 1:
        raise ValueError("comparison report accepts one metric at a time")
    pairs = [
        compare_pair(results[left], results[right])
        for left in range(len(results))
        for right in range(left + 1, len(results))
    ]
    fixture_statuses = {result.provenance.publication_id for result in results}
    return {
        "metric": results[0].metric,
        "results": [dataclass_to_dict(result) for result in results],
        "pairwise_comparisons": [dataclass_to_dict(pair) for pair in pairs],
        "summary": {
            status.value: sum(pair.status == status for pair in pairs)
            for status in ComparabilityStatus
        },
        "publication_count": len(fixture_statuses),
    }


def _context_value(result: MeasurementResult, field_name: str) -> object | None:
    if field_name in {
        "technology",
        "evidence_type",
        "result_nature",
        "configuration",
        "chemistry",
        "system_scale",
        "calculation_boundary",
    }:
        return getattr(result.context, field_name)
    return result.context.condition(field_name)


def _equivalent(left: object, right: object, tolerance: Decimal | None) -> bool:
    if isinstance(left, Condition) and isinstance(right, Condition):
        if left.unit != right.unit:
            return False
        if isinstance(left.value, Decimal) and isinstance(right.value, Decimal):
            return abs(left.value - right.value) <= (tolerance or Decimal(0))
        return _text(left.value) == _text(right.value)
    return _text(left) == _text(right)


def _display(value: object) -> str:
    if isinstance(value, Condition):
        return f"{value.value} {value.unit or ''}".strip()
    return str(getattr(value, "value", value))


def _text(value: object) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()
