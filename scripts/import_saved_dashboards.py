#!/usr/bin/env python3
"""Recover local research files into an explicitly selected persistent project."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_search.infrastructure.dashboard_import import import_local_run
from sci_search.infrastructure.local_research import LocalResearchService
from sci_search.infrastructure.local_workspace import LocalProjectRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Directory containing run.json")
    parser.add_argument(
        "--local-root", required=True, type=Path, help="Existing durable workspace root"
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--user-id", default="development-researcher")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not (args.local_root / "workspace.sqlite3").is_file():
        parser.error("local-root must contain an existing workspace.sqlite3 catalog")
    projects = LocalProjectRepository(args.local_root)
    service = LocalResearchService(
        projects,
        root=args.local_root,
        clock=lambda: datetime.now(UTC),
        id_source=lambda: str(uuid4()),
    )
    try:
        print(
            json.dumps(
                import_local_run(
                    service, args.user_id, args.project_id, args.source, dry_run=args.dry_run
                ),
                indent=2,
            )
        )
    finally:
        service.close()


if __name__ == "__main__":
    main()
