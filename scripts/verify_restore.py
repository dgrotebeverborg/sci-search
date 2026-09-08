#!/usr/bin/env python3
"""Verify a restored Sci-Search database and object bucket against its manifest."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config

from scripts.backup import _secret_env, inspect_database_state
from scripts.restore import _validated_manifest


@dataclass(frozen=True, slots=True)
class VerificationResult:
    ok: bool
    checked_objects: int
    errors: tuple[str, ...]


def verify_restore(
    source: Path,
    *,
    database_url: str,
    bucket: str,
    s3_client: Any,
    inspect_database: Any = inspect_database_state,
) -> VerificationResult:
    manifest = _validated_manifest(source)
    errors: list[str] = []
    state = inspect_database(database_url)
    expected_database = manifest["database"]
    for key in ("schema_version", "row_counts", "grant_count", "audit_endpoints"):
        if state.get(key) != expected_database.get(key):
            errors.append(f"database {key} mismatch")
    checked = 0
    for item in manifest["objects"]:
        digest = sha256()
        size = 0
        try:
            body = s3_client.get_object(Bucket=bucket, Key=item["key"])["Body"]
            while chunk := body.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
        except Exception:
            errors.append(f"missing object: {item['key']}")
            continue
        checked += 1
        if size != item["size"] or digest.hexdigest() != item["sha256"]:
            errors.append(f"object checksum mismatch: {item['key']}")
    return VerificationResult(not errors, checked, tuple(errors))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--database-url", default=_secret_env("SCI_SEARCH_DATABASE_URL"))
    parser.add_argument("--s3-endpoint", default=os.environ.get("SCI_SEARCH_S3_ENDPOINT"))
    parser.add_argument("--s3-bucket", default=os.environ.get("SCI_SEARCH_S3_BUCKET"))
    parser.add_argument("--s3-access-key", default=_secret_env("SCI_SEARCH_S3_ACCESS_KEY"))
    parser.add_argument("--s3-secret-key", default=_secret_env("SCI_SEARCH_S3_SECRET_KEY"))
    arguments = parser.parse_args()
    required = {
        "database URL": arguments.database_url,
        "S3 endpoint": arguments.s3_endpoint,
        "S3 bucket": arguments.s3_bucket,
        "S3 access key": arguments.s3_access_key,
        "S3 secret key": arguments.s3_secret_key,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        parser.error(f"missing {', '.join(missing)}")
    client = boto3.client(
        "s3",
        endpoint_url=arguments.s3_endpoint,
        aws_access_key_id=arguments.s3_access_key,
        aws_secret_access_key=arguments.s3_secret_key,
        config=Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 2}),
    )
    result = verify_restore(
        arguments.source,
        database_url=arguments.database_url,
        bucket=arguments.s3_bucket,
        s3_client=client,
    )
    print(
        json.dumps(
            {"ok": result.ok, "checked_objects": result.checked_objects, "errors": result.errors}
        )
    )
    if not result.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
