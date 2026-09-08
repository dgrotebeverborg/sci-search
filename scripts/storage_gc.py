#!/usr/bin/env python3
"""Plan or explicitly apply reference-aware blob garbage collection."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import boto3
from botocore.config import Config

from sci_search.application.blobs import BlobStore
from sci_search.application.retention import RetentionService
from sci_search.infrastructure.database import Database
from sci_search.infrastructure.filesystem_blobs import FilesystemBlobStore
from sci_search.infrastructure.s3_blobs import S3BlobStore


def _secret_env(name: str) -> str | None:
    direct = os.environ.get(name)
    filename = os.environ.get(f"{name}_FILE")
    if direct is not None and filename is not None:
        raise ValueError(f"configure either {name} or {name}_FILE, not both")
    if filename is None:
        return direct
    path = Path(filename)
    if not path.is_file() or path.stat().st_size > 65_536:
        raise ValueError(f"{name}_FILE is not a small regular file")
    return path.read_text(encoding="utf-8").strip()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan reference-aware blob collection; deletion requires a recorded plan."
    )
    parser.add_argument("--database-url", default=_secret_env("SCI_SEARCH_DATABASE_URL"))
    parser.add_argument("--blob-root", type=Path)
    parser.add_argument("--s3-endpoint", default=os.environ.get("SCI_SEARCH_S3_ENDPOINT"))
    parser.add_argument("--s3-bucket", default=os.environ.get("SCI_SEARCH_S3_BUCKET"))
    parser.add_argument("--s3-access-key", default=_secret_env("SCI_SEARCH_S3_ACCESS_KEY"))
    parser.add_argument("--s3-secret-key", default=_secret_env("SCI_SEARCH_S3_SECRET_KEY"))
    parser.add_argument("--grace-days", type=int, default=30)
    parser.add_argument("--apply-plan")
    parser.add_argument("--confirm")
    return parser


def _blob_store(arguments: Any) -> BlobStore:
    s3_values = (
        arguments.s3_endpoint,
        arguments.s3_bucket,
        arguments.s3_access_key,
        arguments.s3_secret_key,
    )
    if arguments.blob_root is not None:
        if any(s3_values):
            raise ValueError("configure blob-root or S3, not both")
        return FilesystemBlobStore(arguments.blob_root)
    if not all(s3_values):
        raise ValueError("blob-root or complete S3 configuration is required")
    client = boto3.client(
        "s3",
        endpoint_url=arguments.s3_endpoint,
        aws_access_key_id=arguments.s3_access_key,
        aws_secret_access_key=arguments.s3_secret_key,
        config=Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 2}),
    )
    return S3BlobStore(client, arguments.s3_bucket)


def _validate_apply_arguments(arguments: Any) -> None:
    if arguments.apply_plan == "" or arguments.confirm == "":
        raise ValueError("--apply-plan and --confirm require a non-empty UUID")
    if arguments.apply_plan is not None and arguments.confirm != arguments.apply_plan:
        raise ValueError("--apply-plan requires a matching --confirm value")
    if arguments.confirm is not None and arguments.apply_plan is None:
        raise ValueError("--confirm requires --apply-plan")
    if arguments.apply_plan is not None:
        try:
            UUID(arguments.apply_plan)
        except ValueError:
            raise ValueError("--apply-plan and --confirm require a valid UUID") from None


def main() -> int:
    parser = _parser()
    arguments = parser.parse_args()
    if not arguments.database_url:
        parser.error("--database-url or SCI_SEARCH_DATABASE_URL is required")
    if arguments.grace_days < 0:
        parser.error("--grace-days must not be negative")
    try:
        _validate_apply_arguments(arguments)
        blobs = _blob_store(arguments)
    except ValueError as error:
        parser.error(str(error))
    database = Database(arguments.database_url)
    try:
        service = RetentionService(database, blobs)
        if arguments.apply_plan is not None:
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
