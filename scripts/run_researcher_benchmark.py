#!/usr/bin/env python3
"""Run selected locked researcher questions through the complete live pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sci_search.configuration import load_env_file, load_legacy_mistral_key
from sci_search.research_runs import ResearchLimits, ResearchRunManager
from sci_search.researcher_benchmark import validate_researcher_benchmark
from sci_search.scientific_memory import ScientificMemory

DEFAULT_BENCHMARK = ROOT / "benchmarks" / "researcher_questions_v1.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--case", action="append", dest="case_ids")
    selection.add_argument("--tier", choices=("core", "hard", "boundary"))
    selection.add_argument("--all", action="store_true")
    parser.add_argument("--max-full-texts", type=int, default=25)
    parser.add_argument("--per-query", type=int, default=100)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    load_env_file(ROOT / ".env.local")
    load_legacy_mistral_key(ROOT)
    contract = validate_researcher_benchmark(args.benchmark)
    if contract["failed"]:
        raise SystemExit(f"benchmark contract is invalid: {contract['failures']}")
    specification = json.loads(args.benchmark.read_text(encoding="utf-8"))
    cases = specification["cases"]
    if args.case_ids:
        requested = set(args.case_ids)
        cases = [case for case in cases if case["id"] in requested]
        missing = requested - {case["id"] for case in cases}
        if missing:
            raise SystemExit(f"unknown benchmark case(s): {', '.join(sorted(missing))}")
    elif args.tier:
        cases = [case for case in cases if case["tier"] == args.tier]

    memory = ScientificMemory(ROOT / "data" / "scientific_memory")
    memory.bootstrap_runs(ROOT / "data" / "research_runs")
    manager = ResearchRunManager(ROOT / "data" / "benchmark_runs", memory=memory)
    limits = ResearchLimits(
        per_query=args.per_query,
        max_selected=100,
        max_full_texts=args.max_full_texts,
        max_acquisition_attempts=min(200, max(50, args.max_full_texts * 2)),
        citation_depth=1,
    )
    results = []
    if args.output and args.output.is_file():
        checkpoint = json.loads(args.output.read_text(encoding="utf-8"))
        if checkpoint.get("question_sha256") != contract["question_sha256"]:
            raise SystemExit("output checkpoint belongs to a different locked question set")
        results = [
            item
            for item in checkpoint.get("results", [])
            if isinstance(item, dict) and item.get("run_status") == "complete"
        ]
    completed_ids = {item["case_id"] for item in results}
    for case in cases:
        if case["id"] in completed_ids:
            continue
        state = manager.run_sync(case["question"], limits=limits)
        results.append(_result_record(case, state))
        _write_output(args.output, specification, contract, results)
    rendered = _write_output(args.output, specification, contract, results)
    if not args.output:
        print(rendered, end="")
    return 0 if all(item["run_status"] == "complete" for item in results) else 1


def _result_record(case: dict, state: dict) -> dict:
    result = state.get("result") or {}
    evidence = [item for item in result.get("evidence", []) if isinstance(item, dict)]
    evidence_ids = {str(item.get("id")) for item in evidence}
    diagnostics = result.get("pipeline_diagnostics") or {}
    adequacy = result.get("answer_adequacy") or {}
    return {
        "case_id": case["id"],
        "tier": case["tier"],
        "question": case["question"],
        "run_id": state.get("run_id"),
        "run_status": state.get("status"),
        "answer_policy": case["answer_policy"],
        "answer_adequacy": adequacy.get("status"),
        "answer_withheld": not adequacy.get("can_answer_overall_question", False),
        "full_texts_analyzed": (result.get("coverage") or {}).get("full_texts_analyzed", 0),
        "contributing_publications": (diagnostics.get("analysis") or {}).get(
            "contributing_publications", 0
        ),
        "selected_passages": len(evidence),
        "citation_ids_valid": set(result.get("summary_evidence_ids") or []) <= evidence_ids,
        "model_status": (result.get("ai_analysis") or {}).get("status"),
        "pipeline_warnings": diagnostics.get("warnings") or [],
        "must_distinguish": case["must_distinguish"],
        "manual_scientific_appraisal": "pending",
        "artifact_directory": f"data/benchmark_runs/{state.get('run_id')}",
    }


def _write_output(
    output: Path | None, specification: dict, contract: dict, results: list[dict]
) -> str:
    payload = {
        "schema_version": "sci_search_researcher_benchmark_result_v1",
        "created_at": datetime.now(UTC).isoformat(),
        "benchmark": specification.get("name"),
        "lock_version": specification.get("lock_version"),
        "question_sha256": contract["question_sha256"],
        "scientific_validation_status": "silver_pending_researcher_validation",
        "completed_cases": len(results),
        "results": results,
    }
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    return rendered


if __name__ == "__main__":
    raise SystemExit(main())
