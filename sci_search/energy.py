"""Energy-domain vocabulary and comparability rules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from sci_search.models import Condition, Quantity


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    name: str
    aliases: tuple[str, ...]
    canonical_unit: str
    required_context: tuple[str, ...]
    condition_tolerances: tuple[tuple[str, Decimal], ...] = ()

    def tolerance(self, condition_name: str) -> Decimal | None:
        return dict(self.condition_tolerances).get(condition_name)


ROUND_TRIP_EFFICIENCY = MetricDefinition(
    name="round_trip_efficiency",
    aliases=("round-trip efficiency", "round trip efficiency", "rte"),
    canonical_unit="%",
    required_context=(
        "technology",
        "evidence_type",
        "result_nature",
        "configuration",
        "system_scale",
        "calculation_boundary",
        "temperature",
        "current_density",
    ),
    condition_tolerances=(
        ("temperature", Decimal(2)),
        ("current_density", Decimal(1)),
    ),
)


METRICS = {ROUND_TRIP_EFFICIENCY.name: ROUND_TRIP_EFFICIENCY}


def canonical_metric(value: str) -> str:
    key = _key(value)
    for metric in METRICS.values():
        if key == _key(metric.name) or any(key == _key(alias) for alias in metric.aliases):
            return metric.name
    raise ValueError(f"unknown energy metric: {value}")


def normalize_quantity(metric: str, value: str, unit: str, original_text: str) -> Quantity:
    definition = METRICS[canonical_metric(metric)]
    number = Decimal(value)
    normalized_unit = unit.strip().lower()
    if definition.name == "round_trip_efficiency":
        if normalized_unit in {"%", "percent", "percentage"}:
            normalized = number
        elif normalized_unit in {"fraction", "ratio", "1"}:
            normalized = number * Decimal(100)
        else:
            raise ValueError(f"unsupported round-trip efficiency unit: {unit}")
        if not Decimal(0) <= normalized <= Decimal(100):
            raise ValueError("round-trip efficiency must be between 0 and 100 percent")
        return Quantity(
            value=normalized, unit=definition.canonical_unit, original_text=original_text
        )
    raise ValueError(f"no unit normalizer for metric: {metric}")


def normalize_condition(name: str, value: str, unit: str) -> Condition:
    key = _key(name)
    number = Decimal(value)
    normalized_unit = unit.strip().lower().replace(" ", "")
    if key == "temperature":
        if normalized_unit in {"°c", "ºc", "c", "degc"}:
            return Condition("temperature", number, "degC")
        if normalized_unit in {"k", "kelvin"}:
            return Condition("temperature", number - Decimal("273.15"), "degC")
    if key == "current_density":
        normalized_unit = (
            normalized_unit.replace("−", "-").replace("–", "-").replace("²", "2").replace("^", "")
        )
        if normalized_unit in {"ma/cm2", "macm-2", "ma·cm-2"}:
            return Condition("current_density", number, "mA/cm^2")
        if normalized_unit in {"a/cm2", "acm-2", "a·cm-2"}:
            return Condition("current_density", number * Decimal(1000), "mA/cm^2")
    if key == "storage_duration":
        if normalized_unit in {"h", "hr", "hour", "hours"}:
            return Condition("storage_duration", number, "h")
        if normalized_unit in {"d", "day", "days"}:
            return Condition("storage_duration", number * Decimal(24), "h")
    raise ValueError(f"unsupported condition unit for {name}: {unit}")


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
