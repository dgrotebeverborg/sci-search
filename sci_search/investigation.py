"""Question-first scientific investigation over validated evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sci_search.comparison import ComparabilityStatus, PairComparison, compare_pair
from sci_search.energy import canonical_metric
from sci_search.models import MeasurementResult, Publication
from sci_search.store import EvidenceStore


class FindingStatus(StrEnum):
    CONSISTENT = "consistent"
    CONTEXT_DEPENDENT = "context_dependent"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True, slots=True)
class CorpusCoverage:
    publications_discovered: int
    full_texts_available: int
    full_texts_analyzed: int
    results_found: int
    synthetic_documents: int


@dataclass(frozen=True, slots=True)
class InvestigationFinding:
    id: str
    status: FindingStatus
    statement: str
    evidence_ids: tuple[str, ...]
    qualification: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    id: str
    result_id: str
    publication_id: str
    publication_title: str
    source_document: str
    section: str
    page: int | None
    passage: str
    extraction_method: str
    source_url: str | None = None
    doi: str | None = None


@dataclass(frozen=True, slots=True)
class FollowUpPrompt:
    id: str
    label: str
    action: str


@dataclass(frozen=True, slots=True)
class ResearchInvestigation:
    question: str
    interpreted_metric: str
    answer_summary: str
    coverage: CorpusCoverage
    findings: tuple[InvestigationFinding, ...]
    results: tuple[MeasurementResult, ...]
    comparisons: tuple[PairComparison, ...]
    evidence: tuple[EvidenceReference, ...]
    publications: tuple[Publication, ...]
    limitations: tuple[str, ...]
    follow_up_questions: tuple[FollowUpPrompt, ...]


def investigate(question: str, store: EvidenceStore) -> ResearchInvestigation:
    metric = interpret_question(question)
    results = store.query_results(metric)
    publications = tuple(sorted(store.publications.values(), key=lambda item: item.id))
    comparisons = tuple(
        compare_pair(results[left], results[right])
        for left in range(len(results))
        for right in range(left + 1, len(results))
    )
    evidence = tuple(
        _evidence_reference(result, store.publications[result.provenance.publication_id])
        for result in results
    )
    findings = _findings(results, comparisons, evidence)
    coverage = CorpusCoverage(
        publications_discovered=len(publications),
        full_texts_available=sum(bool(item.source_document) for item in publications),
        full_texts_analyzed=len(publications),
        results_found=len(results),
        synthetic_documents=sum(item.fixture_status == "synthetic" for item in publications),
    )
    limitations = _limitations(coverage, results, comparisons)
    return ResearchInvestigation(
        question=question.strip(),
        interpreted_metric=metric,
        answer_summary=_summary(coverage, results, comparisons),
        coverage=coverage,
        findings=findings,
        results=results,
        comparisons=comparisons,
        evidence=evidence,
        publications=publications,
        limitations=limitations,
        follow_up_questions=_follow_up_questions(),
    )


def interpret_question(question: str) -> str:
    normalized = " ".join(question.lower().replace("-", " ").split())
    if "round trip efficien" in normalized or "rte" in normalized.split():
        return canonical_metric("round_trip_efficiency")
    raise ValueError(
        "The current vertical slice supports questions about round-trip efficiency. "
        "The question was preserved but no supported metric could be identified."
    )


def _summary(
    coverage: CorpusCoverage,
    results: tuple[MeasurementResult, ...],
    comparisons: tuple[PairComparison, ...],
) -> str:
    if not results:
        return "No round-trip-efficiency results were found in the analyzed full texts."
    lower_values = [result.quantity.lower_bound or result.quantity.value for result in results]
    upper_values = [result.quantity.upper_bound or result.quantity.value for result in results]
    comparable_pairs = sum(item.status == ComparabilityStatus.COMPARABLE for item in comparisons)
    different_pairs = sum(
        item.status == ComparabilityStatus.DIFFERENT_CONTEXT for item in comparisons
    )
    measured = [result for result in results if result.context.result_nature.value == "measured"]
    assumed = [result for result in results if result.context.result_nature.value == "assumed"]
    parts = [
        f"Sci-Search analyzed {coverage.full_texts_analyzed} full texts and found {len(results)} reviewed contextual round-trip-efficiency results spanning {_number(min(lower_values))}% to {_number(max(upper_values))}%.",
    ]
    if measured:
        measured_lower = [
            result.quantity.lower_bound or result.quantity.value for result in measured
        ]
        measured_upper = [
            result.quantity.upper_bound or result.quantity.value for result in measured
        ]
        parts.append(
            f"The measured laboratory results span {_number(min(measured_lower))}% to {_number(max(measured_upper))}%."
        )
    if assumed:
        assumed_values = ", ".join(_quantity_text(item) for item in assumed)
        parts.append(
            f"The corpus also contains assumed rather than measured performance ({assumed_values})."
        )
    parts.append(
        f"There {_verb(comparable_pairs)} {comparable_pairs} comparable result {_noun(comparable_pairs, 'pair')} "
        f"and {different_pairs} {_noun(different_pairs, 'pair')} with materially different evidence context."
    )
    parts.append(
        "The available evidence therefore does not justify treating every reported value as one universal technology performance figure."
    )
    return " ".join(parts)


def _findings(
    results: tuple[MeasurementResult, ...],
    comparisons: tuple[PairComparison, ...],
    evidence: tuple[EvidenceReference, ...],
) -> tuple[InvestigationFinding, ...]:
    evidence_by_result = {item.result_id: item.id for item in evidence}
    findings: list[InvestigationFinding] = []
    comparable = [item for item in comparisons if item.status == ComparabilityStatus.COMPARABLE]
    if comparable:
        ids = tuple(
            dict.fromkeys(
                result_id
                for pair in comparable
                for result_id in (pair.left_result_id, pair.right_result_id)
            )
        )
        selected = [result for result in results if result.id in ids]
        values = [result.quantity.value for result in selected]
        findings.append(
            InvestigationFinding(
                id="finding:comparable-measurements",
                status=FindingStatus.CONSISTENT,
                statement=f"Comparable laboratory evidence reports round-trip efficiency between {_number(min(values))}% and {_number(max(values))}% under the recorded conditions.",
                evidence_ids=tuple(evidence_by_result[item.id] for item in selected),
                qualification="Consistency here means similar values under the profile's required comparison dimensions; it is not a universal performance estimate.",
            )
        )
    different = [
        item for item in comparisons if item.status == ComparabilityStatus.DIFFERENT_CONTEXT
    ]
    if different:
        differing_fields = sorted(
            {difference.field for pair in different for difference in pair.differences}
        )
        affected_ids = tuple(
            dict.fromkeys(
                result_id
                for pair in different
                for result_id in (pair.left_result_id, pair.right_result_id)
            )
        )
        findings.append(
            InvestigationFinding(
                id="finding:context-differences",
                status=FindingStatus.CONTEXT_DEPENDENT,
                statement="Some reported values are not directly comparable because their scientific contexts differ.",
                evidence_ids=tuple(evidence_by_result[result_id] for result_id in affected_ids),
                qualification="Differing dimensions: " + ", ".join(differing_fields) + ".",
            )
        )
    if not findings:
        findings.append(
            InvestigationFinding(
                id="finding:insufficient-evidence",
                status=FindingStatus.INSUFFICIENT_EVIDENCE,
                statement="The current corpus does not contain enough mutually comparable results to form a cross-paper finding.",
                evidence_ids=tuple(item.id for item in evidence),
            )
        )
    return tuple(findings)


def _evidence_reference(result: MeasurementResult, publication: Publication) -> EvidenceReference:
    return EvidenceReference(
        id=f"evidence:{result.id.removeprefix('result:')}",
        result_id=result.id,
        publication_id=publication.id,
        publication_title=publication.title,
        source_document=publication.source_document,
        section=result.provenance.section,
        page=result.provenance.page,
        passage=result.provenance.passage,
        extraction_method=f"{result.provenance.extraction_method.name} {result.provenance.extraction_method.version}",
        source_url=publication.source_url or publication.access_url,
        doi=publication.doi,
    )


def _limitations(
    coverage: CorpusCoverage,
    results: tuple[MeasurementResult, ...],
    comparisons: tuple[PairComparison, ...],
) -> tuple[str, ...]:
    limitations: list[str] = []
    if coverage.synthetic_documents:
        limitations.append(
            "The bundled corpus is synthetic and demonstrates software behavior, not scientific evidence."
        )
    if coverage.publications_discovered < 10:
        limitations.append(
            "The corpus is smaller than the planned 10–20 paper manually reviewed evaluation set."
        )
    missing = sorted({field for comparison in comparisons for field in comparison.missing_context})
    if missing:
        limitations.append("Some comparisons lack required context: " + ", ".join(missing) + ".")
    if not results:
        limitations.append("No results were extracted for the interpreted metric.")
    return tuple(limitations)


def _follow_up_questions() -> tuple[FollowUpPrompt, ...]:
    return (
        FollowUpPrompt(
            "measured-evidence",
            "Show only measured laboratory evidence and its operating conditions.",
            "filter_measured",
        ),
        FollowUpPrompt(
            "model-comparison",
            "Why is the modeled system value not comparable with the cell measurements?",
            "show_comparison",
        ),
        FollowUpPrompt(
            "assumption-passages",
            "Which source passages describe the efficiency assumptions?",
            "show_assumptions",
        ),
        FollowUpPrompt(
            "missing-context",
            "Which missing conditions prevent stronger comparison?",
            "show_missing_context",
        ),
        FollowUpPrompt(
            "lcos-impact",
            "How could round-trip-efficiency assumptions affect a future LCOS analysis?",
            "new_question",
        ),
    )


def _number(value: object) -> str:
    text = str(value)
    return text.rstrip("0").rstrip(".") if "." in text else text


def _verb(count: int) -> str:
    return "is" if count == 1 else "are"


def _noun(count: int, singular: str) -> str:
    return singular if count == 1 else singular + "s"


def _quantity_text(result: MeasurementResult) -> str:
    quantity = result.quantity
    if quantity.lower_bound is not None:
        return f"{_number(quantity.lower_bound)}–{_number(quantity.upper_bound)}{quantity.unit}"
    return f"{_number(quantity.value)}{quantity.unit}"
