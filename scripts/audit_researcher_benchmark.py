#!/usr/bin/env python3
"""Replay completed benchmark corpora through the current evidence gates."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sci_search.corpus import load_corpus
from sci_search.generic_research import GenericResearchEngine


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    baseline = json.loads(args.result.read_text(encoding="utf-8"))
    rows = []
    for item in baseline.get("results", []):
        corpus = ROOT / str(item["artifact_directory"]) / "corpus"
        report = GenericResearchEngine(load_corpus(corpus)).investigate(str(item["question"]))
        policy = str(item.get("answer_policy") or "")
        current_withheld = not report.answer_adequacy.get("can_answer_overall_question", False)
        boundary_policy = policy.startswith("withhold_") or policy.startswith("reject_")
        rows.append(
            {
                "case_id": item["case_id"],
                "tier": item["tier"],
                "baseline_adequacy": item.get("answer_adequacy"),
                "current_adequacy": report.answer_adequacy.get("status"),
                "current_answer_withheld": current_withheld,
                "current_contributing_publications": report.coverage.publications_with_relevant_evidence,
                "current_selected_passages": len(report.evidence),
                "current_missing_requirements": report.answer_adequacy.get(
                    "missing_requirements", []
                ),
                "boundary_policy_checked": boundary_policy,
                "boundary_policy_passed": current_withheld if boundary_policy else None,
                "summary_citation_ids_valid": set(report.summary_evidence_ids)
                <= {record.id for record in report.evidence},
            }
        )
    adequacy = Counter(row["current_adequacy"] for row in rows)
    boundary = [row for row in rows if row["boundary_policy_checked"]]
    payload = {
        "schema_version": "sci_search_researcher_benchmark_audit_v1",
        "source_result": str(args.result),
        "case_count": len(rows),
        "current_adequacy": dict(sorted(adequacy.items())),
        "boundary_policies_passed": sum(row["boundary_policy_passed"] for row in boundary),
        "boundary_policies_total": len(boundary),
        "all_summary_citation_ids_valid": all(row["summary_citation_ids_valid"] for row in rows),
        "cases": rows,
    }
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if payload["boundary_policies_passed"] == payload["boundary_policies_total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
