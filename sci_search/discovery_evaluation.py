"""Evaluate discovery coverage against a researcher-curated bibliography."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class DiscoveryEvaluation:
    expected_publications: int
    discovered_publications: int
    selected_publications: int
    full_texts_acquired: int
    discovery_recall: float
    selection_recall: float
    acquisition_recall: float
    missed_dois: tuple[str, ...]
    excluded_expected: tuple[dict[str, str], ...]
    passed: bool


def evaluate_discovery(discovery_path: Path, gold_path: Path) -> DiscoveryEvaluation:
    discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    expected = {_doi(item) for item in gold.get("expected_dois", []) if _doi(item)}
    if not expected:
        raise ValueError("gold fixture must contain expected_dois")
    candidates = [item for item in discovery.get("candidates", []) if isinstance(item, dict)]
    by_doi = {_doi(item.get("doi")): item for item in candidates if _doi(item.get("doi"))}
    acquired_ids = {
        str(item.get("publication_id"))
        for item in discovery.get("acquisitions", [])
        if isinstance(item, dict) and item.get("status") == "acquired"
    }
    found = expected & set(by_doi)
    selected = {doi for doi in found if by_doi[doi].get("screening_status") == "selected"}
    acquired = {doi for doi in found if str(by_doi[doi].get("id")) in acquired_ids}
    excluded = tuple(
        {
            "doi": doi,
            "status": str(by_doi[doi].get("screening_status") or "unknown"),
            "reason": str(by_doi[doi].get("screening_reason") or ""),
        }
        for doi in sorted(found - selected)
    )
    threshold = float(gold.get("minimum_discovery_recall", 0.8))
    recall = len(found) / len(expected)
    return DiscoveryEvaluation(
        expected_publications=len(expected),
        discovered_publications=len(found),
        selected_publications=len(selected),
        full_texts_acquired=len(acquired),
        discovery_recall=round(recall, 4),
        selection_recall=round(len(selected) / len(expected), 4),
        acquisition_recall=round(len(acquired) / len(expected), 4),
        missed_dois=tuple(sorted(expected - found)),
        excluded_expected=excluded,
        passed=recall >= threshold,
    )


def _doi(value: Any) -> str:
    return str(value or "").strip().lower().removeprefix("https://doi.org/").removeprefix("doi:")
