"""Deterministic diversity-aware evidence packets for bounded model analysis."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

POLICY_VERSION = "diverse_model_evidence_v1"
_COUNTEREVIDENCE = re.compile(
    r"\b(?:contrary|contradict|disagree|conflict|decreas|negative|no (?:significant )?effect|"
    r"did not|failed to|lower than|worse)\b",
    re.IGNORECASE,
)
_LIMITATION = re.compile(
    r"\b(?:limitation|bias|uncertain|constraint|drawback|excluded|cannot|underestimat|"
    r"overestimat|however|caution)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class EvidenceSelectionLimits:
    max_records: int = 12
    max_tokens: int = 6000
    max_passage_chars: int = 2500

    def __post_init__(self) -> None:
        if self.max_records < 1 or self.max_tokens < 1 or self.max_passage_chars < 80:
            raise ValueError("evidence packet limits must be positive and passages need 80 characters")


@dataclass(frozen=True, slots=True)
class EvidenceExclusion:
    evidence_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class EvidencePacket:
    policy_version: str
    selected_records: tuple[dict[str, Any], ...]
    exclusions: tuple[EvidenceExclusion, ...]
    selection_reasons: dict[str, tuple[str, ...]]
    estimated_tokens: int
    max_records: int
    max_tokens: int
    publication_count: int
    evidence_type_count: int
    coverage_complete: bool
    missing_requirements: tuple[str, ...]

    @property
    def selected_ids(self) -> tuple[str, ...]:
        return tuple(str(record["id"]) for record in self.selected_records)

    @property
    def excluded_ids(self) -> tuple[str, ...]:
        return tuple(item.evidence_id for item in self.exclusions)


@dataclass(frozen=True, slots=True)
class _Candidate:
    evidence_id: str
    publication_id: str
    evidence_type: str
    record: dict[str, Any]
    score: float
    counterevidence: bool
    limitation: bool
    truncated: bool
    tokens: int


def select_model_evidence(
    evidence: list[dict[str, Any]],
    adequacy: dict[str, Any],
    limits: EvidenceSelectionLimits | None = None,
) -> EvidencePacket:
    """Build a stable, inspectable packet before any model provider is called."""

    selected_limits = limits or EvidenceSelectionLimits()
    candidates, invalid = _candidates(evidence, selected_limits)
    selected: list[_Candidate] = []
    selected_ids: set[str] = set()
    reasons: dict[str, list[str]] = defaultdict(list)
    token_total = 0
    budget_rejected: set[str] = set()

    def consider(candidate: _Candidate, reason: str) -> None:
        nonlocal token_total
        if candidate.evidence_id in selected_ids or len(selected) >= selected_limits.max_records:
            return
        if token_total + candidate.tokens > selected_limits.max_tokens:
            budget_rejected.add(candidate.evidence_id)
            return
        selected.append(candidate)
        selected_ids.add(candidate.evidence_id)
        token_total += candidate.tokens
        reasons[candidate.evidence_id].append(reason)
        if candidate.truncated:
            reasons[candidate.evidence_id].append("passage_truncated")

    ranked = sorted(candidates, key=lambda item: (-item.score, item.evidence_id))
    counter = [item for item in ranked if item.counterevidence]
    limitations = [item for item in ranked if item.limitation]
    if counter:
        consider(counter[0], "qualifying_counterevidence")
    if limitations:
        consider(limitations[0], "reported_limitation_or_uncertainty")

    # First pass: one record per publication prevents a dense leading paper from
    # consuming the packet before independent or conflicting studies are seen.
    publication_best: dict[str, _Candidate] = {}
    for candidate in ranked:
        publication_best.setdefault(candidate.publication_id, candidate)
    for candidate in sorted(
        publication_best.values(), key=lambda item: (-item.score, item.evidence_id)
    ):
        consider(candidate, "publication_diversity")

    # Second pass: preserve different evidence natures/study designs even when
    # their retrieval score is below a homogeneous cluster.
    type_best: dict[str, _Candidate] = {}
    for candidate in ranked:
        type_best.setdefault(candidate.evidence_type, candidate)
    for candidate in sorted(type_best.values(), key=lambda item: (-item.score, item.evidence_id)):
        consider(candidate, "evidence_type_diversity")

    # Fill remaining slots by round-robin publication depth, with stable scoring
    # and evidence ID tie-breaking inside every publication.
    by_publication: dict[str, list[_Candidate]] = defaultdict(list)
    for candidate in ranked:
        by_publication[candidate.publication_id].append(candidate)
    publication_order = sorted(
        by_publication,
        key=lambda publication_id: (
            -by_publication[publication_id][0].score,
            publication_id,
        ),
    )
    maximum_depth = max((len(records) for records in by_publication.values()), default=0)
    for depth in range(maximum_depth):
        if len(selected) >= selected_limits.max_records:
            break
        for publication_id in publication_order:
            records = by_publication[publication_id]
            if depth < len(records):
                consider(records[depth], "ranked_round_robin")

    exclusions = list(invalid)
    for candidate in sorted(candidates, key=lambda item: item.evidence_id):
        if candidate.evidence_id in selected_ids:
            continue
        reason = (
            "token_budget"
            if candidate.evidence_id in budget_rejected
            or token_total + candidate.tokens > selected_limits.max_tokens
            else "record_budget"
        )
        exclusions.append(EvidenceExclusion(candidate.evidence_id, reason))

    selected_records = tuple(candidate.record for candidate in selected)
    missing = tuple(str(item) for item in adequacy.get("missing_requirements", ()) if str(item))
    return EvidencePacket(
        policy_version=POLICY_VERSION,
        selected_records=selected_records,
        exclusions=tuple(exclusions),
        selection_reasons={key: tuple(value) for key, value in sorted(reasons.items())},
        estimated_tokens=token_total,
        max_records=selected_limits.max_records,
        max_tokens=selected_limits.max_tokens,
        publication_count=len({item.publication_id for item in selected}),
        evidence_type_count=len({item.evidence_type for item in selected}),
        coverage_complete=bool(evidence) and adequacy.get("can_answer_overall_question") is True,
        missing_requirements=missing,
    )


def _candidates(
    evidence: list[dict[str, Any]], limits: EvidenceSelectionLimits
) -> tuple[list[_Candidate], list[EvidenceExclusion]]:
    unique: dict[str, dict[str, Any]] = {}
    invalid: list[EvidenceExclusion] = []
    for index, raw in enumerate(evidence):
        if not isinstance(raw, dict):
            invalid.append(EvidenceExclusion(f"record:{index}", "invalid_record"))
            continue
        evidence_id = str(raw.get("id") or "").strip()
        if not evidence_id:
            invalid.append(EvidenceExclusion(f"record:{index}", "missing_evidence_id"))
            continue
        existing = unique.get(evidence_id)
        if existing is None or _canonical(raw) < _canonical(existing):
            unique[evidence_id] = raw

    candidates: list[_Candidate] = []
    for evidence_id, raw in sorted(unique.items()):
        statement = " ".join(str(raw.get("statement") or "").split())
        passage, truncated = _bounded_passage(
            str(raw.get("passage") or statement), statement, limits.max_passage_chars
        )
        record = dict(raw)
        record["id"] = evidence_id
        record["statement"] = statement
        record["passage"] = passage
        record, passage, truncated = _fit_single_record_budget(
            record,
            str(raw.get("passage") or statement),
            statement,
            limits,
            truncated,
        )
        publication_id = str(raw.get("publication_id") or "unknown-publication")
        evidence_type = str(
            raw.get("evidence_type") or raw.get("study_design") or "unknown"
        ).casefold()
        direction = str(raw.get("direction") or "").casefold()
        combined = f"{statement} {passage[:1000]}"
        counterevidence = direction in {"negative", "decrease", "decreasing", "none"} or bool(
            _COUNTEREVIDENCE.search(combined)
        )
        limitation = bool(_LIMITATION.search(combined))
        score = _numeric_score(raw.get("retrieval_score"))
        score += 100 if counterevidence else 0
        score += 80 if limitation else 0
        score += 10 if evidence_type not in {"", "unknown"} else 0
        tokens = _estimate_tokens(record)
        candidates.append(
            _Candidate(
                evidence_id,
                publication_id,
                evidence_type,
                record,
                score,
                counterevidence,
                limitation,
                truncated,
                tokens,
            )
        )
    return candidates, invalid


def _bounded_passage(passage: str, statement: str, maximum: int) -> tuple[str, bool]:
    cleaned = " ".join(passage.split())
    if len(cleaned) <= maximum:
        return cleaned, False
    statement_index = cleaned.find(statement) if statement else -1
    if statement_index < 0 or len(statement) >= maximum:
        return cleaned[:maximum], True
    spare = maximum - len(statement)
    start = max(0, statement_index - spare // 2)
    end = min(len(cleaned), start + maximum)
    start = max(0, end - maximum)
    return cleaned[start:end], True


def _estimate_tokens(record: dict[str, Any]) -> int:
    # Conservative deterministic approximation; the provider records actual usage later.
    return max(1, math.ceil(len(json.dumps(record, ensure_ascii=False, sort_keys=True)) / 4))


def _fit_single_record_budget(
    record: dict[str, Any],
    original_passage: str,
    statement: str,
    limits: EvidenceSelectionLimits,
    already_truncated: bool,
) -> tuple[dict[str, Any], str, bool]:
    """Let one otherwise-valid record fit when passage context can be reduced safely."""

    tokens = _estimate_tokens(record)
    if tokens <= limits.max_tokens:
        return record, str(record["passage"]), already_truncated

    minimum = max(80, len(statement))
    maximum = len(str(record["passage"]))
    if maximum <= minimum:
        return record, str(record["passage"]), already_truncated

    # Binary search keeps the largest context window that satisfies the packet's
    # hard token ceiling while retaining the selected source statement.
    best_record: dict[str, Any] | None = None
    best_passage = ""
    low, high = minimum, maximum - 1
    while low <= high:
        midpoint = (low + high) // 2
        candidate_passage, _ = _bounded_passage(original_passage, statement, midpoint)
        candidate_record = dict(record)
        candidate_record["passage"] = candidate_passage
        if _estimate_tokens(candidate_record) <= limits.max_tokens:
            best_record = candidate_record
            best_passage = candidate_passage
            low = midpoint + 1
        else:
            high = midpoint - 1
    if best_record is None:
        return record, str(record["passage"]), already_truncated
    return best_record, best_passage, True


def _numeric_score(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
