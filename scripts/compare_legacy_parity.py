#!/usr/bin/env python3
"""Compare a legacy source tree with a completed production import."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sci_search.compatibility.legacy_import import (
    LegacyImportTarget,
    compare_parity,
    scan_legacy,
)
from sci_search.infrastructure.database import Database


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail on unexplained legacy import loss.")
    parser.add_argument("legacy_root", type=Path)
    parser.add_argument("--database-url", default=os.environ.get("SCI_SEARCH_DATABASE_URL"))
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--actor-user-id", required=True)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if not arguments.database_url:
        parser.error("--database-url or SCI_SEARCH_DATABASE_URL is required")
    database = Database(arguments.database_url)
    try:
        report = compare_parity(
            scan_legacy(arguments.legacy_root),
            LegacyImportTarget(database, arguments.project_id, arguments.actor_user_id),
        )
    finally:
        database.dispose()
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if arguments.output:
        arguments.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
