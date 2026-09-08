#!/usr/bin/env python3
"""Restore a complete Sci-Search backup into new database and bucket targets."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tarfile
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from sqlalchemy import create_engine, inspect

from scripts.backup import (
    RunCommand,
    _command,
    _database_name,
    _expand,
    _postgres_cli_url,
    _run_database_command,
    _safe_object_path,
    _secret_env,
    _sha256,
    _write_pgpass,
)


@dataclass(frozen=True, slots=True)
class RestoreConfig:
    source: Path
    database_url: str
    bucket: str
    pg_restore_command: tuple[str, ...] = ("pg_restore",)
    decryption_command: tuple[str, ...] = ()


def restore_backup(
    config: RestoreConfig,
    *,
    s3_client: Any,
    run: RunCommand | None = None,
    assert_empty_database: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    if not config.decryption_command:
        raise ValueError("a decryption command is required")
    manifest = _validated_manifest(config.source)
    if _database_name(config.database_url) == manifest["database"]["name"]:
        raise ValueError("restore database must differ from the source database")
    if config.bucket == manifest["object_store"]["bucket"]:
        raise ValueError("restore bucket must differ from the source bucket")
    (assert_empty_database or _assert_empty_database)(config.database_url)
    _assert_empty_bucket(s3_client, config.bucket)
    execute = run or _run

    with tempfile.TemporaryDirectory(prefix="sci-search-restore-") as temporary_name:
        temporary = Path(temporary_name)
        archive = temporary / "payload.tar"
        encrypted = config.source / manifest["encryption"]["payload"]
        execute(_expand(config.decryption_command, encrypted, archive))
        if not archive.is_file():
            raise RuntimeError("decryption command did not produce a payload archive")
        extracted = temporary / "extracted"
        extracted.mkdir()
        _safe_extract(archive, extracted)
        payload = extracted / "payload"
        inventory = json.loads((payload / "inventory.json").read_text(encoding="utf-8"))
        for key in ("database", "object_store", "objects"):
            if inventory.get(key) != manifest.get(key):
                raise ValueError("encrypted inventory does not match the backup manifest")
        dump = payload / "database.dump"
        if _sha256(dump) != manifest["database"]["dump_sha256"]:
            raise ValueError("database dump checksum mismatch")
        pgpass = temporary / ".pgpass"
        _write_pgpass(config.database_url, pgpass)
        _run_database_command(
            run,
            [
                *config.pg_restore_command,
                "--dbname",
                _postgres_cli_url(config.database_url),
                "--no-owner",
                "--no-privileges",
                "--exit-on-error",
                str(dump),
            ],
            pgpass,
        )
        pgpass.unlink()
        restored = 0
        for item in manifest["objects"]:
            source = payload / "objects" / _safe_object_path(item["key"])
            if source.stat().st_size != item["size"] or _sha256(source) != item["sha256"]:
                raise ValueError(f"object checksum mismatch: {item['key']}")
            s3_client.upload_file(str(source), config.bucket, item["key"])
            restored += 1
    return {"backup_id": manifest["backup_id"], "restored_objects": restored}


def _validated_manifest(source: Path) -> dict[str, Any]:
    marker = source / "COMPLETE"
    manifest_path = source / "manifest.json"
    if not marker.is_file() or not manifest_path.is_file():
        raise ValueError("backup is not complete")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {"format_version", "backup_id", "database", "object_store", "objects", "encryption"}
    if manifest.get("format_version") != 1 or not required <= manifest.keys():
        raise ValueError("backup manifest is invalid or unsupported")
    if marker.read_text(encoding="utf-8").strip() != manifest["backup_id"]:
        raise ValueError("backup completion marker does not match the manifest")
    encrypted = source / manifest["encryption"].get("payload", "")
    if not encrypted.is_file() or _sha256(encrypted) != manifest["encryption"].get("sha256"):
        raise ValueError("encrypted backup payload checksum mismatch")
    return manifest


def _assert_empty_database(database_url: str) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        existing = set(inspect(engine).get_table_names()) - {"alembic_version"}
        if existing:
            raise ValueError("restore database must be empty")
    finally:
        engine.dispose()


def _assert_empty_bucket(client: Any, bucket: str) -> None:
    client.head_bucket(Bucket=bucket)
    pages = client.get_paginator("list_objects_v2").paginate(Bucket=bucket)
    if any(page.get("Contents") for page in pages):
        raise ValueError("restore bucket must be empty")


def _safe_extract(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r") as bundle:
        for member in bundle.getmembers():
            target = (destination / member.name).resolve()
            if destination.resolve() not in target.parents and target != destination.resolve():
                raise ValueError("backup archive contains an unsafe path")
            if member.issym() or member.islnk():
                raise ValueError("backup archive contains a link")
        bundle.extractall(destination, filter="data")


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--database-url", default=_secret_env("SCI_SEARCH_DATABASE_URL"))
    parser.add_argument("--s3-endpoint", default=os.environ.get("SCI_SEARCH_S3_ENDPOINT"))
    parser.add_argument("--s3-bucket", default=os.environ.get("SCI_SEARCH_S3_BUCKET"))
    parser.add_argument("--s3-access-key", default=_secret_env("SCI_SEARCH_S3_ACCESS_KEY"))
    parser.add_argument("--s3-secret-key", default=_secret_env("SCI_SEARCH_S3_SECRET_KEY"))
    parser.add_argument("--pg-restore-command", type=_command, default=("pg_restore",))
    parser.add_argument("--decryption-command", type=_command, required=True)
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
    restore_backup(
        RestoreConfig(
            arguments.source,
            arguments.database_url,
            arguments.s3_bucket,
            arguments.pg_restore_command,
            arguments.decryption_command,
        ),
        s3_client=client,
    )


if __name__ == "__main__":
    main()
