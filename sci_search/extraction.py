"""Model-independent extraction boundary and deterministic pilot extractor."""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal
from typing import Protocol

from sci_search.corpus import CorpusDocument, SourcePassage
from sci_search.energy import normalize_condition, normalize_quantity
from sci_search.models import (
    Evidence,
    EvidenceType,
    ExtractionBundle,
    ExtractionMethod,
    MeasurementContext,
    MeasurementResult,
    Provenance,
    Quantity,
    ResultNature,
    ScientificStatement,
    StatementKind,
)


class ScientificExtractor(Protocol):
    def extract(self, document: CorpusDocument) -> ExtractionBundle: ...


class RuleBasedEnergyExtractor:
    """A transparent smoke extractor, not a production NLP system."""

    method = ExtractionMethod(name="rule_based_energy", version="0.1.0")
    _efficiency = re.compile(
        r"(?:round[- ]trip(?: energy)? efficiency|\bRTE\b)[^.;]{0,80}?"
        r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>%|percent|fraction|ratio)",
        re.IGNORECASE,
    )
    _temperature = re.compile(
        r"(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>°C|ºC|degC|K)\b", re.IGNORECASE
    )
    _current_density = re.compile(
        r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mA\s*(?:/|·)?\s*cm(?:\^?[-−]?2|²)|A\s*(?:/|·)?\s*cm(?:\^?[-−]?2|²))",
        re.IGNORECASE,
    )
    _duration = re.compile(
        r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>hours?|hrs?|h|days?|d)\b", re.IGNORECASE
    )

    def extract(self, document: CorpusDocument) -> ExtractionBundle:
        if document.reviewed_results is not None:
            return self._extract_reviewed(document)
        results: list[MeasurementResult] = []
        statements: list[ScientificStatement] = []
        evidence: list[Evidence] = []
        warnings: list[str] = []
        for passage in document.passages():
            for match in self._efficiency.finditer(passage.text):
                try:
                    result = self._result(document, passage, match)
                    results.append(result)
                    statement_kind = (
                        StatementKind.ASSUMPTION
                        if result.context.result_nature == ResultNature.ASSUMED
                        else StatementKind.CLAIM
                    )
                    statement_id = _stable_id(result.id, statement_kind.value, passage.text)
                    statements.append(
                        ScientificStatement(
                            id=statement_id,
                            kind=statement_kind,
                            text=passage.text,
                            provenance=result.provenance,
                            evidence_type=result.context.evidence_type,
                            scope=result.context.conditions,
                            supports_result_ids=(result.id,),
                        )
                    )
                    evidence.append(
                        Evidence(
                            id=_stable_id(
                                result.id, "evidence", result.context.evidence_type.value
                            ),
                            evidence_type=result.context.evidence_type,
                            description=f"{result.context.evidence_type.value} reported in {passage.section}",
                            provenance=result.provenance,
                            result_ids=(result.id,),
                        )
                    )
                except ValueError as exc:
                    warnings.append(f"{document.publication.id}:{passage.page}:{exc}")
        if not results:
            warnings.append(f"{document.publication.id}:no_round_trip_efficiency_found")
        return ExtractionBundle(
            document.publication,
            results=tuple(results),
            statements=tuple(statements),
            evidence=tuple(evidence),
            warnings=tuple(warnings),
        )

    def _extract_reviewed(self, document: CorpusDocument) -> ExtractionBundle:
        results: list[MeasurementResult] = []
        statements: list[ScientificStatement] = []
        evidence: list[Evidence] = []
        warnings: list[str] = []
        method = ExtractionMethod(name="manual_context_review", version="0.1.0")
        for index, annotation in enumerate(document.reviewed_results or ()):
            anchor = str(annotation.get("anchor") or "").strip()
            passage = next(
                (item for item in document.passages() if anchor and anchor in item.text), None
            )
            if passage is None:
                warnings.append(
                    f"{document.publication.id}:reviewed_anchor_not_found:{anchor[:60]}"
                )
                continue
            lower = annotation.get("lower_bound")
            upper = annotation.get("upper_bound")
            conditions = tuple(
                normalize_condition(str(item["name"]), str(item["value"]), str(item["unit"]))
                for item in annotation.get("conditions", [])
            )
            provenance = Provenance(
                publication_id=document.publication.id,
                source_document=document.publication.source_document,
                section=passage.section,
                page=passage.page,
                passage=passage.text,
                passage_start=passage.start,
                passage_end=passage.end,
                extraction_method=method,
            )
            result_id = _stable_id(document.publication.id, "reviewed", str(index), anchor)
            result = MeasurementResult(
                id=result_id,
                metric="round_trip_efficiency",
                quantity=Quantity(
                    value=Decimal(str(annotation["value"])),
                    unit="%",
                    original_text=str(annotation.get("original_text") or anchor),
                    lower_bound=Decimal(str(lower)) if lower is not None else None,
                    upper_bound=Decimal(str(upper)) if upper is not None else None,
                ),
                context=MeasurementContext(
                    technology=document.technology,
                    evidence_type=EvidenceType(
                        str(annotation.get("evidence_type") or document.evidence_type.value)
                    ),
                    result_nature=ResultNature(
                        str(annotation.get("result_nature") or document.result_nature.value)
                    ),
                    configuration=str(
                        annotation.get("configuration") or document.configuration or ""
                    )
                    or None,
                    chemistry=str(annotation.get("chemistry") or document.chemistry or "") or None,
                    system_scale=str(annotation.get("system_scale") or document.system_scale or "")
                    or None,
                    calculation_boundary=str(
                        annotation.get("calculation_boundary")
                        or document.calculation_boundary
                        or ""
                    )
                    or None,
                    conditions=conditions,
                    assumptions=tuple(annotation.get("assumptions", document.assumptions)),
                ),
                provenance=provenance,
                confidence=1.0,
            )
            results.append(result)
            statement_id = _stable_id(result_id, "claim", passage.text)
            statements.append(
                ScientificStatement(
                    id=statement_id,
                    kind=StatementKind.CLAIM,
                    text=passage.text,
                    provenance=provenance,
                    evidence_type=result.context.evidence_type,
                    scope=conditions,
                    supports_result_ids=(result_id,),
                )
            )
            evidence.append(
                Evidence(
                    id=_stable_id(result_id, "evidence"),
                    evidence_type=result.context.evidence_type,
                    description="Manually reviewed contextual result",
                    provenance=provenance,
                    result_ids=(result_id,),
                )
            )
        return ExtractionBundle(
            document.publication,
            results=tuple(results),
            statements=tuple(statements),
            evidence=tuple(evidence),
            warnings=tuple(warnings),
        )

    def _result(
        self,
        document: CorpusDocument,
        passage: SourcePassage,
        match: re.Match[str],
    ) -> MeasurementResult:
        quantity = normalize_quantity(
            "round_trip_efficiency",
            match.group("value"),
            match.group("unit"),
            match.group(0),
        )
        conditions = []
        for name, pattern in (
            ("temperature", self._temperature),
            ("current_density", self._current_density),
            ("storage_duration", self._duration),
        ):
            condition_match = pattern.search(passage.text)
            if condition_match:
                conditions.append(
                    normalize_condition(
                        name, condition_match.group("value"), condition_match.group("unit")
                    )
                )
        provenance = Provenance(
            publication_id=document.publication.id,
            source_document=document.publication.source_document,
            section=passage.section,
            page=passage.page,
            passage=passage.text,
            passage_start=passage.start,
            passage_end=passage.end,
            extraction_method=self.method,
        )
        result_id = _stable_id(
            document.publication.id, "round_trip_efficiency", str(passage.start), match.group(0)
        )
        return MeasurementResult(
            id=result_id,
            metric="round_trip_efficiency",
            quantity=quantity,
            context=MeasurementContext(
                technology=document.technology,
                evidence_type=document.evidence_type,
                result_nature=document.result_nature,
                configuration=document.configuration,
                chemistry=document.chemistry,
                system_scale=document.system_scale,
                calculation_boundary=document.calculation_boundary,
                conditions=tuple(conditions),
                assumptions=document.assumptions,
            ),
            provenance=provenance,
            confidence=1.0,
        )


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"result:{digest}"
