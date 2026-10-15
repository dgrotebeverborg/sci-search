"""Deterministic identity and severity for model-proposed contradiction groups."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum

SEVERITY_RULES_VERSION = "contradiction_severity_v1"
GROUP_STATUS = "model_proposed_source_verified"
PRIMARY_EMPIRICAL_NATURES = frozenset({"laboratory experiment", "field or observational study"})


class ContradictionCause(StrEnum):
    DIFFERENT_CONDITIONS = "different_conditions"
    DIFFERENT_POPULATION = "different_population"
    DIFFERENT_METHOD = "different_method"
    DIFFERENT_OUTCOME_MEASURE = "different_outcome_measure"
    UNEXPLAINED = "unexplained"


class Severity(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


_ORDER = (Severity.LOW, Severity.MODERATE, Severity.HIGH)
_CONTEXT = "Apparent contradiction explained by differing context"
_BASE = {
    ContradictionCause.DIFFERENT_CONDITIONS: (Severity.LOW, _CONTEXT),
    ContradictionCause.DIFFERENT_POPULATION: (Severity.LOW, _CONTEXT),
    ContradictionCause.DIFFERENT_OUTCOME_MEASURE: (Severity.LOW, _CONTEXT),
    ContradictionCause.DIFFERENT_METHOD: (
        Severity.MODERATE,
        "Differing methods; which method is appropriate is unresolved",
    ),
    ContradictionCause.UNEXPLAINED: (
        Severity.HIGH,
        "No grounded explanation for the disagreement",
    ),
}


def contradiction_group_id(topic: str, positions: Sequence[Iterable[str]]) -> str:
    normalized = " ".join(topic.casefold().split())
    members = sorted(",".join(sorted(set(ids))) for ids in positions)
    digest = hashlib.sha256(f"{normalized}\x1f{'|'.join(members)}".encode()).hexdigest()
    return f"contradiction:{digest[:20]}"


def assess_severity(
    cause: str | ContradictionCause,
    position_publication_ids: Sequence[Sequence[str]],
    *,
    touches_answer: bool,
    evidence_nature_by_publication: Mapping[str, str],
) -> tuple[Severity, tuple[str, ...]]:
    base, reason = _BASE[ContradictionCause(cause)]
    level = _ORDER.index(base)
    basis = [reason]
    if touches_answer:
        level += 1
        basis.append("Raised: the contested evidence supports the answer or a main finding")
    if _imbalanced(position_publication_ids, evidence_nature_by_publication):
        level -= 1
        basis.append(
            "Lowered: one side rests on a single non-empirical study while another side "
            "has at least two primary empirical studies"
        )
    return _ORDER[max(0, min(level, len(_ORDER) - 1))], tuple(basis)


def _imbalanced(positions: Sequence[Sequence[str]], natures: Mapping[str, str]) -> bool:
    def primary(publication_id: str) -> bool:
        return natures.get(publication_id, "unclassified") in PRIMARY_EMPIRICAL_NATURES

    weak = any(len(ids) == 1 and not primary(ids[0]) for ids in positions)
    strong = any(sum(primary(item) for item in ids) >= 2 for ids in positions)
    return weak and strong
