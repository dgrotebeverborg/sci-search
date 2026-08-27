#!/usr/bin/env python3
"""Validate a locked protocol and write an allowlisted live-result artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sci_search.scientific_protocol import load_protocol, sanitize_live_result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    protocol = load_protocol(args.protocol, args.questions)
    raw = json.loads(args.input.read_text(encoding="utf-8"))
    if raw.get("question_sha256") != protocol.question_sha256:
        raise SystemExit("live result does not belong to the locked question version")
    sanitized = sanitize_live_result(raw)
    args.output.write_text(json.dumps(sanitized, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
