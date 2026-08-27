#!/usr/bin/env python3
"""Write a deterministic, read-only inventory of retained legacy data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sci_search.compatibility.legacy_import import inventory_legacy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("legacy_root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--maximum-records", type=int, default=100_000)
    arguments = parser.parse_args()
    payload = (
        json.dumps(
            inventory_legacy(arguments.legacy_root, maximum_records=arguments.maximum_records),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if arguments.output is None:
        print(payload, end="")
    else:
        arguments.output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
