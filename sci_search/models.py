"""Generic, dependency-free scientific evidence contracts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any


class EvidenceType(StrEnum):
    LABORATORY_EXPERIMENT = "laboratory_experiment"
    FIELD_EXPERIMENT = "field_experiment"
    OBSERVATIONAL_STUDY = "observational_study"
    PILOT_DEMONSTRATION = "pilot_demonstration"
    COMMERCIAL_SYSTEM = "commercial_system"
    SIMULATION = "simulation"
    TECHNO_ECONOMIC_MODEL = "techno_economic_model"
    SYSTEM_MODEL = "system_model"
    REVIEW = "review"
    EXPERT_ASSUMPTION = "expert_assumption"
    MANUFACTURER_CLAIM = "manufacturer_claim"
    OTHER = "other"


class ResultNature(StrEnum):
    MEASURED = "measured"
    MODELED = "modeled"
    ASSUMED = "assumed"
    REPORTED = "reported"


class StatementKind(StrEnum):
    RESEARCH_QUESTION = "research_question"
    CLAIM = "claim"
    LIMITATION = "limitation"
    ASSUMPTION = "assumption"
    KNOWLEDGE_GAP = "knowledge_gap"
    RESEARCH_IMPLICATION = "research_implication"


class EntityKind(StrEnum):
    TOPIC = "topic"
    METHOD = "method"
    DATASET = "dataset"
    STUDY_OBJECT = "study_object"
    VARIABLE = "variable"
    LOCATION = "location"


@dataclass(frozen=True, slots=True)
class ExtractionMethod:
    name: str
    version: str
    provider: str | None = None
    model: str | None = None
    schema_version: str = "scientific_evidence_v1"

    def __post_init__(self) -> None:
        _require_text("extraction method name", self.name)
        _require_text("extraction method version", self.version)


@dataclass(frozen=True, slots=True)
class Provenance:
    publication_id: str
    source_document: str
    section: str
    passage: str
    extraction_method: ExtractionMethod
    page: int | None = None
    passage_start: int | None = None
    passage_end: int | None = None

    def __post_init__(self) -> None:
        _require_text("publication_id", self.publication_id)
        _require_text("source_document", self.source_document)
        _require_text("section", self.section)
        _require_text("passage", self.passage)
        if self.page is not None and self.page < 1:
            raise ValueError("page must be positive")
        if (self.passage_start is None) != (self.passage_end is None):
            raise ValueError("passage offsets must be provided together")
        if self.passage_start is not None:
            if self.passage_start < 0 or self.passage_end <= self.passage_start:
                raise ValueError("invalid passage offsets")


@dataclass(frozen=True, slots=True)
class Publication:
    id: str
    title: str
    source_document: str
    doi: str | None = None
    year: int | None = None
    fixture_status: str | None = None
    authors: tuple[str, ...] = ()
    document_type: str = "article"
    source_url: str | None = None
    access_url: str | None = None
    license: str | None = None
    access_status: str | None = None

    def __post_init__(self) -> None:
        _require_text("publication id", self.id)
        _require_text("publication title", self.title)
        _require_text("source_document", self.source_document)


@dataclass(frozen=True, slots=True)
class Quantity:
    value: Decimal
    unit: str
    original_text: str
    uncertainty: Decimal | None = None
    lower_bound: Decimal | None = None
    upper_bound: Decimal | None = None

    def __post_init__(self) -> None:
        _require_text("quantity unit", self.unit)
        _require_text("quantity original_text", self.original_text)
        if not self.value.is_finite():
            raise ValueError("quantity value must be finite")
        if self.uncertainty is not None and self.uncertainty < 0:
            raise ValueError("uncertainty cannot be negative")
        if (self.lower_bound is None) != (self.upper_bound is None):
            raise ValueError("quantity bounds must be provided together")
        if self.lower_bound is not None and not (
            self.lower_bound <= self.value <= self.upper_bound
        ):
            raise ValueError("quantity value must fall within its bounds")


@dataclass(frozen=True, slots=True)
class Condition:
    name: str
    value: str | Decimal
    unit: str | None = None
    qualifier: str | None = None

    def __post_init__(self) -> None:
        _require_text("condition name", self.name)
        if isinstance(self.value, str):
            _require_text("condition value", self.value)
        elif not self.value.is_finite():
            raise ValueError("condition value must be finite")


@dataclass(frozen=True, slots=True)
class MeasurementContext:
    technology: str
    evidence_type: EvidenceType
    result_nature: ResultNature
    configuration: str | None = None
    chemistry: str | None = None
    system_scale: str | None = None
    calculation_boundary: str | None = None
    conditions: tuple[Condition, ...] = ()
    assumptions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text("context technology", self.technology)
        names = [item.name for item in self.conditions]
        if len(names) != len(set(names)):
            raise ValueError("condition names must be unique within a result")

    def condition(self, name: str) -> Condition | None:
        return next((item for item in self.conditions if item.name == name), None)


@dataclass(frozen=True, slots=True)
class MeasurementResult:
    id: str
    metric: str
    quantity: Quantity
    context: MeasurementContext
    provenance: Provenance
    confidence: float | None = None

    def __post_init__(self) -> None:
        _require_text("result id", self.id)
        _require_text("result metric", self.metric)
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between zero and one")


@dataclass(frozen=True, slots=True)
class ScientificStatement:
    id: str
    kind: StatementKind
    text: str
    provenance: Provenance
    evidence_type: EvidenceType
    scope: tuple[Condition, ...] = ()
    supports_result_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text("statement id", self.id)
        _require_text("statement text", self.text)


@dataclass(frozen=True, slots=True)
class ScientificEntity:
    id: str
    kind: EntityKind
    label: str
    provenance: Provenance
    normalized_label: str | None = None

    def __post_init__(self) -> None:
        _require_text("entity id", self.id)
        _require_text("entity label", self.label)


@dataclass(frozen=True, slots=True)
class Evidence:
    id: str
    evidence_type: EvidenceType
    description: str
    provenance: Provenance
    method_ids: tuple[str, ...] = ()
    result_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text("evidence id", self.id)
        _require_text("evidence description", self.description)


@dataclass(frozen=True, slots=True)
class ExtractionBundle:
    publication: Publication
    entities: tuple[ScientificEntity, ...] = ()
    results: tuple[MeasurementResult, ...] = ()
    statements: tuple[ScientificStatement, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    warnings: tuple[str, ...] = ()


def dataclass_to_dict(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {
            name: dataclass_to_dict(getattr(value, name)) for name in value.__dataclass_fields__
        }
    if isinstance(value, tuple):
        return [dataclass_to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: dataclass_to_dict(item) for key, item in value.items()}
    return value


def _require_text(label: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} is required")
