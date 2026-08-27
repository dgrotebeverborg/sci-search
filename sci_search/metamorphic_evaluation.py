"""Counterfactual and paraphrase-invariance tests for scientific retrieval."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sci_search.corpus import load_corpus
from sci_search.generic_research import GenericResearchEngine


def evaluate_metamorphic_cases(path: Path) -> dict[str, Any]:
    specification = json.loads(path.read_text(encoding="utf-8"))
    engines: dict[Path, GenericResearchEngine] = {}
    results: list[dict[str, Any]] = []

    def engine_for(value: str) -> GenericResearchEngine:
        corpus = (path.parent / value).resolve()
        if corpus not in engines:
            engines[corpus] = GenericResearchEngine(load_corpus(corpus))
        return engines[corpus]

    for case in specification.get("cases", []):
        engine = engine_for(str(case["corpus"]))
        kind = str(case["kind"])
        failures: list[str] = []
        if kind == "negative_control":
            report = engine.investigate(str(case["question"]))
            publications = {item.publication_id for item in report.evidence}
            maximum = case.get("maximum_evidence_publications")
            if maximum is not None and len(publications) > int(maximum):
                failures.append(
                    f"counterfactual retained {len(publications)} evidence publications; maximum is {maximum}"
                )
            if report.answer_adequacy.get("can_answer_overall_question"):
                failures.append("counterfactual was incorrectly judged answerable")
            if report.summary_evidence_ids:
                failures.append(
                    "counterfactual promoted candidate passages into the answer summary"
                )
            detail = {
                "question": case["question"],
                "evidence_publications": len(publications),
                "adequacy": report.answer_adequacy.get("status"),
                "concepts": list(report.plan.concepts),
            }
        elif kind == "paraphrase_invariance":
            left = engine.investigate(str(case["question_a"]))
            right = engine.investigate(str(case["question_b"]))
            left_ids = {item.publication_id for item in left.evidence}
            right_ids = {item.publication_id for item in right.evidence}
            union = left_ids | right_ids
            jaccard = len(left_ids & right_ids) / len(union) if union else 1.0
            minimum = float(case.get("minimum_publication_jaccard", 0.5))
            if jaccard < minimum:
                failures.append(f"publication Jaccard {jaccard:.3f} is below {minimum:.3f}")
            if left.plan.profile_id != right.plan.profile_id:
                failures.append(
                    f"profile changed from {left.plan.profile_id} to {right.plan.profile_id}"
                )
            if case.get("require_same_intent", True) and left.plan.intent != right.plan.intent:
                failures.append(f"intent changed from {left.plan.intent} to {right.plan.intent}")
            detail = {
                "question_a": case["question_a"],
                "question_b": case["question_b"],
                "publication_jaccard": round(jaccard, 4),
                "evidence_publications_a": len(left_ids),
                "evidence_publications_b": len(right_ids),
                "adequacy_a": left.answer_adequacy.get("status"),
                "adequacy_b": right.answer_adequacy.get("status"),
            }
        else:
            raise ValueError(f"unknown metamorphic case kind: {kind}")
        results.append(
            {
                "id": str(case["id"]),
                "kind": kind,
                "passed": not failures,
                "failures": failures,
                **detail,
            }
        )
    passed = sum(item["passed"] for item in results)
    return {
        "schema_version": "sci_search_metamorphic_evaluation_v1",
        "case_count": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": round(passed / len(results), 4) if results else 1.0,
        "cases": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = evaluate_metamorphic_cases(args.benchmark)
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
