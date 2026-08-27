#!/usr/bin/env python3
"""Evaluate persisted live runs against the five-question silver reference set."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sci_search.reference_evaluation import evaluate_reference_set


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference-set", type=Path, default=ROOT / "benchmarks" / "researcher_five_silver_v1.json"
    )
    parser.add_argument("--runs-root", type=Path, default=ROOT / "data" / "benchmark_runs")
    parser.add_argument(
        "--benchmark-result",
        type=Path,
        action="append",
        help="Use case/run mappings from one or more live benchmark results; later files override earlier ones",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--replay-analysis",
        action="store_true",
        help="Re-run evidence selection with current code over the persisted corpus",
    )
    args = parser.parse_args()
    run_ids = None
    if args.benchmark_result:
        run_ids = {}
        for result_path in args.benchmark_result:
            benchmark = json.loads(result_path.read_text(encoding="utf-8"))
            run_ids.update(
                {
                    str(item.get("case_id")): str(item.get("run_id"))
                    for item in benchmark.get("results", [])
                    if item.get("case_id") and item.get("run_id")
                }
            )
    report = evaluate_reference_set(
        args.reference_set,
        args.runs_root,
        run_ids,
        replay_analysis=args.replay_analysis,
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
