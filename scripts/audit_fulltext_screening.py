#!/usr/bin/env python3
"""Audit post-acquisition full-text decisions against the five-question silver set."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sci_search.fulltext_screening import screen_acquired_documents
from sci_search.question_planning import plan_question
from sci_search.research_runs import _candidate_from_dict, _outcome_from_dict


def main() -> int:
    suite = json.loads(
        (ROOT / "benchmarks" / "researcher_five_silver_v1.json").read_text(encoding="utf-8")
    )
    rows = []
    for case in suite["cases"]:
        directory = ROOT / "data" / "benchmark_runs" / case["baseline_run_id"]
        discovery = json.loads((directory / "discovery.json").read_text(encoding="utf-8"))
        candidates = {item["id"]: _candidate_from_dict(item) for item in discovery["candidates"]}
        outcomes = [
            _outcome_from_dict(item)
            for item in discovery["acquisitions"]
            if item.get("status") == "acquired" and item.get("publication_id") in candidates
        ]
        _, decisions = screen_acquired_documents(
            case["question"],
            plan_question(case["question"]),
            directory / "corpus",
            [(candidates[outcome.publication_id], outcome) for outcome in outcomes],
        )
        by_doi = {
            str(candidates[item["publication_id"]].doi): item["decision"]
            for item in decisions
            if candidates[item["publication_id"]].doi
        }
        references = [
            {
                "doi": item["doi"],
                "expected": item["relevance"],
                "decision": by_doi.get(item["doi"], "not_acquired"),
            }
            for item in case["publications"]
        ]
        rows.append(
            {
                "case_id": case["id"],
                "run_id": case["baseline_run_id"],
                "decision_counts": dict(Counter(item["decision"] for item in decisions)),
                "reference_decisions": references,
            }
        )
    print(json.dumps({"schema_version": "fulltext_screening_audit_v1", "cases": rows}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
