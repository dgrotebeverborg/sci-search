"""Audit historical Sci-Search runs against the current scientific-scope gates."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sci_search.corpus import load_corpus
from sci_search.coverage import decompose_question, evidence_context
from sci_search.generic_research import GenericResearchEngine
from sci_search.literature_review import build_literature_review
from sci_search.question_planning import plan_question


@dataclass(frozen=True, slots=True)
class RunAudit:
    run_id: str
    question: str
    artifact_status: str
    stored_evidence: int
    current_evidence: int
    stored_adequacy: str
    current_adequacy: str
    stored_answer_claimed: bool
    current_answer_supported: bool
    stored_exact_provenance: int
    stored_scope_complete: int
    stored_promoted_evidence: int
    stored_promoted_scope_complete: int
    unavailable_high_relevance_records: int
    unsafe_historical_answer: bool
    issues: tuple[str, ...]


def audit_research_runs(root: Path) -> dict[str, Any]:
    results: list[RunAudit] = []
    skipped: list[dict[str, str]] = []
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        run_path = directory / "run.json"
        investigation_path = directory / "investigation.json"
        if not run_path.is_file() or not investigation_path.is_file():
            skipped.append(
                {"run_id": directory.name, "reason": "missing run or investigation artifact"}
            )
            continue
        try:
            state = json.loads(run_path.read_text(encoding="utf-8"))
            stored = json.loads(investigation_path.read_text(encoding="utf-8"))
            results.append(_audit_run(directory, state, stored))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            skipped.append({"run_id": directory.name, "reason": f"{type(exc).__name__}: {exc}"})
    unsafe = sum(item.unsafe_historical_answer for item in results)
    exact = sum(item.stored_exact_provenance for item in results)
    evidence = sum(item.stored_evidence for item in results)
    scope_complete = sum(item.stored_scope_complete for item in results)
    promoted = sum(item.stored_promoted_evidence for item in results)
    promoted_complete = sum(item.stored_promoted_scope_complete for item in results)
    current_supported = sum(item.current_answer_supported for item in results)
    return {
        "schema_version": "sci_search_historical_reliability_audit_v1",
        "runs_directory": str(root.resolve()),
        "audited_runs": len(results),
        "skipped_runs": skipped,
        "summary": {
            "unsafe_historical_answers": unsafe,
            "currently_supported_answers": current_supported,
            "stored_evidence_records": evidence,
            "stored_exact_provenance_records": exact,
            "stored_scope_complete_records": scope_complete,
            "stored_promoted_evidence_records": promoted,
            "stored_promoted_scope_complete_records": promoted_complete,
            "exact_provenance_rate": round(exact / evidence, 4) if evidence else 1.0,
            "complete_scope_rate": round(scope_complete / evidence, 4) if evidence else 1.0,
            "promoted_complete_scope_rate": round(promoted_complete / promoted, 4)
            if promoted
            else 1.0,
        },
        "runs": [asdict(item) for item in results],
    }


def _audit_run(directory: Path, state: dict[str, Any], stored: dict[str, Any]) -> RunAudit:
    question = str(state.get("question") or stored.get("question") or "").strip()
    documents = load_corpus(directory / "corpus")
    current = GenericResearchEngine(documents).investigate(question).to_dict()
    plan = plan_question(question)
    scope = decompose_question(question, plan)
    stored_evidence = [item for item in stored.get("evidence", []) if isinstance(item, dict)]
    source_text = {item.publication.source_document: item.text for item in documents}
    exact_count = sum(_exact_record(item, source_text) for item in stored_evidence)
    complete_count = sum(_scope_complete(item, scope) for item in stored_evidence)
    promoted_ids = _promoted_evidence_ids(stored)
    promoted_records = [
        item for item in stored_evidence if str(item.get("id") or "") in promoted_ids
    ]
    promoted_complete = sum(_scope_complete(item, scope) for item in promoted_records)
    stored_adequacy = (
        stored.get("answer_adequacy") if isinstance(stored.get("answer_adequacy"), dict) else {}
    )
    current_adequacy = (
        current.get("answer_adequacy") if isinstance(current.get("answer_adequacy"), dict) else {}
    )
    stored_claimed = _answer_claimed(stored)
    current_supported = bool(current_adequacy.get("can_answer_overall_question"))
    candidates = (
        (stored.get("research_run") or {}).get("candidates") or state.get("candidates") or []
    )
    unavailable = sum(
        isinstance(item, dict)
        and item.get("screening_status") == "unavailable"
        and float(item.get("concept_coverage") or 0) >= 0.99
        for item in candidates
    )
    issues: list[str] = []
    if exact_count < len(stored_evidence):
        issues.append(
            f"{len(stored_evidence) - exact_count} stored evidence records fail exact provenance reconstruction"
        )
    if promoted_complete < len(promoted_records):
        issues.append(
            f"{len(promoted_records) - promoted_complete} answer-promoted evidence records do not cover every required question dimension"
        )
    unsafe = stored_claimed and not current_supported
    if unsafe:
        issues.append(
            "historical artifact presented an answer that the current adequacy gate withholds"
        )
    if unavailable:
        issues.append(f"{unavailable} high-relevance metadata records lacked trusted full text")
    review = build_literature_review(current)
    if not current_supported and review.get("findings"):
        issues.append("coverage-limited current review still promotes findings")
    return RunAudit(
        run_id=directory.name,
        question=question,
        artifact_status=str(state.get("status") or "unknown"),
        stored_evidence=len(stored_evidence),
        current_evidence=len(current.get("evidence") or []),
        stored_adequacy=str(stored_adequacy.get("status") or "legacy_unassessed"),
        current_adequacy=str(current_adequacy.get("status") or "unknown"),
        stored_answer_claimed=stored_claimed,
        current_answer_supported=current_supported,
        stored_exact_provenance=exact_count,
        stored_scope_complete=complete_count,
        stored_promoted_evidence=len(promoted_records),
        stored_promoted_scope_complete=promoted_complete,
        unavailable_high_relevance_records=unavailable,
        unsafe_historical_answer=unsafe,
        issues=tuple(issues),
    )


def _exact_record(item: dict[str, Any], sources: dict[str, str]) -> bool:
    text = sources.get(str(item.get("source_document") or ""))
    start, end = item.get("passage_start"), item.get("passage_end")
    passage, statement = str(item.get("passage") or ""), str(item.get("statement") or "")
    return bool(
        text is not None
        and isinstance(start, int)
        and isinstance(end, int)
        and 0 <= start <= end <= len(text)
        and text[start:end] == passage
        and statement in passage
    )


def _scope_complete(item: dict[str, Any], scope: dict[str, Any]) -> bool:
    context = evidence_context(f"{item.get('statement') or ''} {item.get('passage') or ''}", scope)
    matched = set(context.get("scope_dimension_ids") or [])
    required = {
        str(dimension.get("id"))
        for dimension in scope.get("dimensions", [])
        if dimension.get("required") and dimension.get("kind") != "task"
    }
    return required <= matched


def _answer_claimed(investigation: dict[str, Any]) -> bool:
    adequacy = (
        investigation.get("answer_adequacy")
        if isinstance(investigation.get("answer_adequacy"), dict)
        else {}
    )
    if adequacy:
        return bool(adequacy.get("can_answer_overall_question"))
    ai = (
        investigation.get("ai_analysis")
        if isinstance(investigation.get("ai_analysis"), dict)
        else {}
    )
    if isinstance(ai.get("answer"), dict):
        return True
    if investigation.get("summary_evidence_ids"):
        return True
    summary = str(investigation.get("answer_summary") or "").casefold()
    return bool(summary and "withheld" not in summary and "not contain enough" not in summary)


def _promoted_evidence_ids(investigation: dict[str, Any]) -> set[str]:
    result = {str(item) for item in investigation.get("summary_evidence_ids", []) if str(item)}
    ai = (
        investigation.get("ai_analysis")
        if isinstance(investigation.get("ai_analysis"), dict)
        else {}
    )
    values: list[Any] = [ai.get("answer")]
    for category in (
        "claims",
        "agreements",
        "contradictions",
        "method_differences",
        "limitations",
        "uncertainties",
        "assumptions",
        "knowledge_gaps",
    ):
        category_values = ai.get(category)
        if isinstance(category_values, list):
            values.extend(category_values)
    for value in values:
        if isinstance(value, dict):
            result.update(str(item) for item in value.get("evidence_ids", []) if str(item))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path, nargs="?", default=Path("data/research_runs"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = audit_research_runs(args.runs)
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 1 if result["summary"]["unsafe_historical_answers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
