#!/usr/bin/env python3
"""Plan or explicitly apply reference-aware blob garbage collection."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sci_search.application.retention import RetentionService
from sci_search.infrastructure.database import Database
from sci_search.infrastructure.filesystem_blobs import FilesystemBlobStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run by default; apply only a recorded plan.")
    parser.add_argument("--database-url", default=os.environ.get("SCI_SEARCH_DATABASE_URL"))
    parser.add_argument("--blob-root", required=True, type=Path)
    parser.add_argument("--grace-days", type=int, default=30)
    parser.add_argument("--apply-plan")
    parser.add_argument("--confirm")
    arguments = parser.parse_args()
    if not arguments.database_url:
        parser.error("--database-url or SCI_SEARCH_DATABASE_URL is required")
    if arguments.grace_days < 0:
        parser.error("--grace-days must not be negative")
    database = Database(arguments.database_url)
    try:
        service = RetentionService(database, FilesystemBlobStore(arguments.blob_root))
        if arguments.apply_plan:
            result = service.apply_gc(arguments.apply_plan, arguments.confirm or "")
            payload = {"mode": "apply", "result": asdict(result)}
            status = 0 if not result.stale else 1
        else:
            plan = service.plan_gc(datetime.now(UTC), timedelta(days=arguments.grace_days))
            payload = {"mode": "dry_run", "plan": asdict(plan)}
            status = 0
    finally:
        database.dispose()
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
