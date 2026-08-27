"""Stage-level evaluation against a small researcher-reviewable reference set.

The reference set is intentionally called silver until a domain researcher has
validated both inclusions and exclusions. Metrics therefore describe recall of
*known* references, not recall of the complete scientific literature.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sci_search.corpus import load_corpus
from sci_search.generic_research import GenericResearchEngine


@dataclass(frozen=True, slots=True)
class StageEvaluation:
    case_id: str
    run_id: str
    known_direct_references: int
    discovered_direct_references: int
    selected_direct_references: int
    acquired_direct_references: int
    evidence_direct_references: int
    known_reference_discovery_recall: float
    known_reference_selection_recall: float
    known_reference_acquisition_recall: float
    known_reference_evidence_recall: float
    known_distractors: int
    distractors_excluded_at_screening: int
    distractors_used_as_evidence: int
    evidence_records: int
    provenance_complete_records: int
    provenance_completeness: float
    answer_adequacy: str
    missing_direct_dois: tuple[str, ...]
    acquired_without_evidence_dois: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_reference_set(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "sci_search_silver_reference_set_v1":
        raise ValueError("unsupported reference-set schema")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("reference set must contain cases")
    identifiers: set[str] = set()
    for case in cases:
        identifier = str(case.get("id") or "")
        if not identifier or identifier in identifiers:
            raise ValueError("reference case ids must be present and unique")
        identifiers.add(identifier)
        publications = case.get("publications")
        if not isinstance(publications, list) or not publications:
            raise ValueError(f"reference case {identifier} has no publications")
        for publication in publications:
            if publication.get("relevance") not in {"direct", "contextual", "distractor"}:
                raise ValueError(f"reference case {identifier} has an invalid relevance label")
            if not _doi(publication.get("doi")):
                raise ValueError(f"reference case {identifier} contains a publication without DOI")
    return payload


def evaluate_reference_case(
    run_directory: Path,
    reference_case: dict[str, Any],
    *,
    replay_analysis: bool = False,
) -> StageEvaluation:
    discovery = json.loads((run_directory / "discovery.json").read_text(encoding="utf-8"))
    investigation = (
        GenericResearchEngine(load_corpus(run_directory / "corpus"))
        .investigate(str(reference_case.get("question") or ""))
        .to_dict()
        if replay_analysis
        else json.loads((run_directory / "investigation.json").read_text(encoding="utf-8"))
    )
    run = json.loads((run_directory / "run.json").read_text(encoding="utf-8"))
    candidates = [item for item in discovery.get("candidates", []) if isinstance(item, dict)]
    candidate_by_doi = {_doi(item.get("doi")): item for item in candidates if _doi(item.get("doi"))}
    acquired_ids = {
        str(item.get("publication_id"))
        for item in discovery.get("acquisitions", [])
        if isinstance(item, dict) and item.get("status") == "acquired"
    }
    evidence = [item for item in investigation.get("evidence", []) if isinstance(item, dict)]
    evidence_publication_ids = {str(item.get("publication_id")) for item in evidence}
    direct = [
        item for item in reference_case.get("publications", []) if item.get("relevance") == "direct"
    ]
    distractors = [
        item
        for item in reference_case.get("publications", [])
        if item.get("relevance") == "distractor"
    ]
    located_direct = [(item, _reference_candidates(item, candidate_by_doi)) for item in direct]
    located_distractors = [
        (item, _reference_candidates(item, candidate_by_doi)) for item in distractors
    ]
    discovered = [item for item, candidates in located_direct if candidates]
    selected = [
        item
        for item, candidates in located_direct
        if any(candidate.get("screening_status") == "selected" for candidate in candidates)
    ]
    acquired = [
        item
        for item, candidates in located_direct
        if any(str(candidate.get("id")) in acquired_ids for candidate in candidates)
    ]
    used = [
        item
        for item, candidates in located_direct
        if any(str(candidate.get("id")) in evidence_publication_ids for candidate in candidates)
    ]
    excluded_distractors = [
        item
        for item, candidates in located_distractors
        if candidates
        and all(
            candidate.get("screening_status") in {"excluded", "not_selected"}
            for candidate in candidates
        )
    ]
    used_distractors = [
        item
        for item, candidates in located_distractors
        if any(str(candidate.get("id")) in evidence_publication_ids for candidate in candidates)
    ]
    complete = sum(_provenance_complete(item) for item in evidence)
    warnings: list[str] = []
    if _ratio(len(discovered), len(direct)) < 0.8:
        warnings.append("known-reference discovery recall is below 0.80")
    if _ratio(len(acquired), len(direct)) < 0.8:
        warnings.append("known-reference full-text acquisition recall is below 0.80")
    acquired_canonical = {_doi(item.get("doi")) for item in acquired}
    used_canonical = {_doi(item.get("doi")) for item in used}
    if acquired_canonical - used_canonical:
        warnings.append("one or more acquired direct references contributed no selected evidence")
    if used_distractors:
        warnings.append("a known distractor contributed selected evidence")
    if evidence and complete != len(evidence):
        warnings.append("one or more evidence records have incomplete provenance")
    return StageEvaluation(
        case_id=str(reference_case["id"]),
        run_id=str(run.get("run_id") or run_directory.name),
        known_direct_references=len(direct),
        discovered_direct_references=len(discovered),
        selected_direct_references=len(selected),
        acquired_direct_references=len(acquired),
        evidence_direct_references=len(used),
        known_reference_discovery_recall=_ratio(len(discovered), len(direct)),
        known_reference_selection_recall=_ratio(len(selected), len(direct)),
        known_reference_acquisition_recall=_ratio(len(acquired), len(direct)),
        known_reference_evidence_recall=_ratio(len(used), len(direct)),
        known_distractors=len(distractors),
        distractors_excluded_at_screening=len(excluded_distractors),
        distractors_used_as_evidence=len(used_distractors),
        evidence_records=len(evidence),
        provenance_complete_records=complete,
        provenance_completeness=_ratio(complete, len(evidence)),
        answer_adequacy=str(
            (investigation.get("answer_adequacy") or {}).get("status") or "unknown"
        ),
        missing_direct_dois=tuple(
            sorted(_doi(item.get("doi")) for item, candidates in located_direct if not candidates)
        ),
        acquired_without_evidence_dois=tuple(sorted(acquired_canonical - used_canonical)),
        warnings=tuple(warnings),
    )


def evaluate_reference_set(
    reference_path: Path,
    runs_root: Path,
    run_ids: dict[str, str] | None = None,
    *,
    replay_analysis: bool = False,
) -> dict[str, Any]:
    specification = load_reference_set(reference_path)
    configured = run_ids or {
        str(case["id"]): str(case.get("baseline_run_id") or "") for case in specification["cases"]
    }
    results = []
    for case in specification["cases"]:
        identifier = str(case["id"])
        run_id = configured.get(identifier, "")
        if not run_id:
            raise ValueError(f"no run id configured for {identifier}")
        results.append(
            evaluate_reference_case(
                runs_root / run_id,
                case,
                replay_analysis=replay_analysis,
            ).to_dict()
        )
    return {
        "schema_version": "sci_search_reference_evaluation_v1",
        "reference_set": specification.get("name"),
        "validation_status": specification.get("validation_status"),
        "metric_scope": "recall_of_known_silver_references_not_complete_literature_recall",
        "analysis_mode": "current_code_replay" if replay_analysis else "persisted_run_baseline",
        "case_count": len(results),
        "results": results,
    }


def _provenance_complete(evidence: dict[str, Any]) -> bool:
    required = (
        "id",
        "publication_id",
        "source_document",
        "statement",
        "passage",
        "extraction_method",
    )
    if not all(evidence.get(field) not in {None, ""} for field in required):
        return False
    passage = " ".join(str(evidence.get("passage") or "").split())
    statement = " ".join(str(evidence.get("statement") or "").split())
    return bool(
        statement
        and statement in passage
        and evidence.get("passage_start") is not None
        and evidence.get("passage_end") is not None
    )


def _reference_candidates(
    reference: dict[str, Any], candidates: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], ...]:
    dois = (
        _doi(reference.get("doi")),
        *(_doi(item) for item in reference.get("equivalent_dois", [])),
    )
    return tuple(candidates[doi] for doi in dois if doi in candidates)


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 1.0


def _doi(value: Any) -> str:
    return str(value or "").strip().casefold().removeprefix("https://doi.org/").removeprefix("doi:")
