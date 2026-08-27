#!/usr/bin/env python3
"""Export the current ten-question researcher-validation scorecard."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sci_search.validation_workspace import ValidationWorkspace


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    args = parser.parse_args()
    root = ROOT
    workspace = ValidationWorkspace(
        root / "benchmarks" / "researcher_validation_v1.json",
        root / "data" / "validation_annotations",
        (
            root / "data" / "validation_replays" / "v1",
            root / "data" / "benchmark_runs",
            root / "data" / "research_runs",
        ),
    )
    payload = workspace.overview()
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
