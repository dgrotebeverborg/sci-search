#!/usr/bin/env python3
"""Compare deterministic ranking on explicit relevance labels without training."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sci_search.feedback_ranking import SCORING_VERSION, score_feedback
from sci_search.question_planning import plan_question


def metrics(candidates: list[dict]) -> dict[str, float | int]:
    def dcg(rows):
        return sum(
            (2 ** item["relevance"] - 1) / math.log2(index + 2)
            for index, item in enumerate(rows[:10])
        )

    ideal = dcg(sorted(candidates, key=lambda item: -item["relevance"]))
    relevant = sum(item["relevance"] > 0 for item in candidates)
    return {
        "ndcg_at_10": dcg(candidates) / ideal if ideal else 1.0,
        "recall_at_20": sum(item["relevance"] > 0 for item in candidates[:20]) / relevant
        if relevant
        else 1.0,
        "irrelevant_selections": sum(item["relevance"] == 0 for item in candidates[:10]),
        "repeated_corrections": sum(
            item["relevance"] == 0 and item.get("prior_excluded", False) for item in candidates[:10]
        ),
        "source_reuse": sum(bool(item.get("cached")) for item in candidates[:10]),
    }


def evaluate(benchmark: dict) -> dict:
    results = []
    for question in benchmark["questions"]:
        baseline = sorted(
            question["candidates"], key=lambda item: (-item["base_score"], item["id"])
        )
        scores = score_feedback(plan_question(question["question"]), benchmark["feedback"])
        ranked = sorted(
            baseline,
            key=lambda item: (
                -(item["base_score"] + scores.get(item["id"], {}).get("adjustment", 0)),
                item["id"],
            ),
        )
        off, on = metrics(baseline), metrics(ranked)
        results.append(
            {
                "question_id": question["id"],
                "related": question["related"],
                "ranking_off": off,
                "ranking_on": on,
                "ndcg_delta": on["ndcg_at_10"] - off["ndcg_at_10"],
                "explanations": scores,
            }
        )
    return {
        "dataset_status": benchmark["dataset_status"],
        "scoring_version": SCORING_VERSION,
        "release_gate": "pending_researcher_confirmed_held_out_labels",
        "default_ranking_enabled": False,
        "questions": results,
        "mean_ndcg_delta": sum(row["ndcg_delta"] for row in results) / max(1, len(results)),
        "unrelated_degradation": any(
            row["ndcg_delta"] < 0 for row in results if not row["related"]
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = evaluate(json.loads(args.benchmark.read_text()))
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "release_gate": result["release_gate"]}))


if __name__ == "__main__":
    main()
