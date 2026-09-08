#!/usr/bin/env python3
"""Dry-run or apply a fingerprinted legacy Sci-Search import."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from sci_search.compatibility.legacy_import import (
    LegacyImportTarget,
    apply_import,
    scan_legacy,
)
from sci_search.infrastructure.database import Database
from sci_search.infrastructure.filesystem_blobs import FilesystemBlobStore


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a legacy tree and copy it only when --apply is explicit."
    )
    parser.add_argument("legacy_root", type=Path)
    parser.add_argument("--database-url", default=os.environ.get("SCI_SEARCH_DATABASE_URL"))
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--actor-user-id", required=True)
    parser.add_argument("--blob-root", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--maximum-batches", type=int)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    if not arguments.database_url:
        parser.error("--database-url or SCI_SEARCH_DATABASE_URL is required")

    manifest = scan_legacy(arguments.legacy_root)
    database = Database(arguments.database_url)
    try:
        result = apply_import(
            manifest,
            LegacyImportTarget(database, arguments.project_id, arguments.actor_user_id),
            FilesystemBlobStore(arguments.blob_root),
            apply=arguments.apply,
            batch_size=arguments.batch_size,
            maximum_batches=arguments.maximum_batches,
        )
    finally:
        database.dispose()
    payload = {
        "manifest": {
            "source_fingerprint": manifest.source_fingerprint,
            "publications": manifest.publication_count,
            "runs": manifest.run_count,
            "evidence": manifest.evidence_count,
            "blobs": manifest.blob_count,
        },
        "result": asdict(result),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
