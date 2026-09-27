#!/usr/bin/env python3
"""Validate and explicitly import one owner-attested legacy local memory.

This offline command never guesses who owns a legacy memory. Place a
.memory-owner.json attestation containing project_id and user_id in the source
only after verifying ownership. Imports into a populated destination are refused;
use revision replay to merge existing projects.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sci_search.application.memory import MemoryContext
from sci_search.infrastructure.local_memory import LocalScientificMemory


def import_memory(source: Path, destination: Path, project_id: str, *, dry_run: bool) -> dict:
    source = source.resolve()
    database = source / "memory.sqlite3"
    if not database.is_file():
        raise ValueError("source has no scientific memory database")
    owner_path = source / ".memory-owner.json"
    if not owner_path.is_file():
        return {
            "status": "blocked_unknown_ownership",
            "imported": 0,
            "unknown_provenance": True,
            "dry_run": dry_run,
        }
    owner = json.loads(owner_path.read_text())
    if owner.get("project_id") != project_id or not owner.get("user_id"):
        raise ValueError("source ownership does not match requested project")
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("source database integrity failed")
        rows = connection.execute(
            "SELECT cache_path, download_cache_path, content_sha256 FROM publications"
        ).fetchall()
        files: set[Path] = set()
        for cache, download, digest in rows:
            for relative, expected in (
                (cache, digest),
                (download, Path(download).stem if download else None),
            ):
                if not relative:
                    continue
                path = (source / relative).resolve()
                path.relative_to(source)
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    raise ValueError("source document hash mismatch")
                files.add(path)
        publications = connection.execute("SELECT COUNT(*) FROM publications").fetchone()[0]
    report = {
        "status": "validated",
        "publications": publications,
        "documents": len(files),
        "imported": 0,
        "dry_run": dry_run,
        "legacy_actor_provenance": "unknown; historical decisions are not inferred votes",
    }
    if dry_run:
        return report
    memory = LocalScientificMemory(destination, MemoryContext(owner["user_id"], project_id))
    if memory.root == source:
        raise ValueError("source and destination must differ")
    digest = hashlib.sha256(database.read_bytes()).hexdigest()
    receipt = memory.root / "legacy-import.json"
    if receipt.is_file() and json.loads(receipt.read_text()).get("source_sha256") == digest:
        return {**report, "status": "already_imported"}
    if any(memory.stats().values()):
        raise ValueError("destination has research; merge via authorized revision replay")
    with (
        sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as old,
        sqlite3.connect(memory.database) as new,
    ):
        old.backup(new)
    for path in files:
        target = memory.root / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    LocalScientificMemory(destination, MemoryContext(owner["user_id"], project_id))
    receipt.write_text(
        json.dumps({"source_sha256": digest, "project_id": project_id, "user_id": owner["user_id"]})
    )
    return {**report, "status": "imported", "imported": publications}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--destination", type=Path, default=Path("data/project-memory"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            import_memory(args.source, args.destination, args.project_id, dry_run=args.dry_run),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
