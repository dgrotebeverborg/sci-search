#!/usr/bin/env python3
"""Create an encrypted, versioned PostgreSQL and S3-compatible backup."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tarfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4

import boto3
from botocore.config import Config
from sqlalchemy import MetaData, Table, create_engine, func, inspect, select, text

RunCommand = Callable[[list[str]], None]


@dataclass(frozen=True, slots=True)
class BackupConfig:
    database_url: str
    bucket: str
    destination: Path
    pg_dump_command: tuple[str, ...] = ("pg_dump",)
    encryption_command: tuple[str, ...] = ()


def create_backup(
    config: BackupConfig,
    *,
    s3_client: Any,
    run: RunCommand | None = None,
    inspect_database: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a complete backup directory or leave no completed destination."""

    if not config.encryption_command:
        raise ValueError("an encryption command is required")
    if not config.pg_dump_command:
        raise ValueError("pg_dump command is required")
    if config.destination.exists():
        raise FileExistsError(config.destination)
    if not config.bucket.strip():
        raise ValueError("source bucket is required")
    execute = run or _run
    database_inspector = inspect_database or inspect_database_state
    backup_id = str(uuid4())
    staging = config.destination.with_name(f".{config.destination.name}.partial-{backup_id}")
    staging.mkdir(parents=True)
    try:
        payload = staging / "payload"
        payload.mkdir()
        database_dump = payload / "database.dump"
        pgpass = staging / ".pgpass"
        _write_pgpass(config.database_url, pgpass)
        _run_database_command(
            run,
            [
                *config.pg_dump_command,
                "--dbname",
                _postgres_cli_url(config.database_url),
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--file",
                str(database_dump),
            ],
            pgpass,
        )
        pgpass.unlink()
        if not database_dump.is_file():
            raise RuntimeError("pg_dump did not produce a database dump")

        object_records: list[dict[str, Any]] = []
        for key in _object_keys(s3_client, config.bucket):
            relative = _safe_object_path(key)
            target = payload / "objects" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            s3_client.download_file(config.bucket, key, str(target))
            object_records.append(
                {"key": key, "size": target.stat().st_size, "sha256": _sha256(target)}
            )

        database_state = database_inspector(config.database_url)
        inventory: dict[str, Any] = {
            "database": {
                "name": _database_name(config.database_url),
                "dump_sha256": _sha256(database_dump),
                **database_state,
            },
            "object_store": {"bucket": config.bucket},
            "objects": object_records,
        }
        (payload / "inventory.json").write_text(
            json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        archive = staging / "payload.tar"
        with tarfile.open(archive, "w") as bundle:
            bundle.add(payload, arcname="payload", recursive=True)
        encrypted = staging / "payload.enc"
        execute(_expand(config.encryption_command, archive, encrypted))
        if not encrypted.is_file():
            raise RuntimeError("encryption command did not produce an encrypted payload")

        manifest: dict[str, Any] = {
            "format_version": 1,
            "backup_id": backup_id,
            "created_at": datetime.now(UTC).isoformat(),
            **inventory,
            "encryption": {
                "enabled": True,
                "payload": encrypted.name,
                "sha256": _sha256(encrypted),
            },
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        shutil.rmtree(payload)
        archive.unlink()
        (staging / "COMPLETE").write_text(backup_id + "\n", encoding="utf-8")
        staging.rename(config.destination)
        return manifest
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def inspect_database_state(database_url: str) -> dict[str, Any]:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        table_names = sorted(inspect(engine).get_table_names())
        metadata = MetaData()
        counts: dict[str, int] = {}
        with engine.connect() as connection:
            for name in table_names:
                table = Table(name, metadata, autoload_with=engine)
                counts[name] = int(connection.scalar(select(func.count()).select_from(table)) or 0)
            schema_version = (
                connection.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
                if "alembic_version" in table_names
                else None
            )
            grant_count = counts.get("project_document_grants", 0)
            audit_endpoints: dict[str, Any] = {"count": counts.get("audit_events", 0)}
            if audit_endpoints["count"]:
                endpoints = connection.execute(
                    text(
                        "SELECT CAST(id AS TEXT), occurred_at FROM audit_events "
                        "ORDER BY occurred_at, id"
                    )
                ).all()
                audit_endpoints.update(
                    {
                        "first": endpoints[0][0],
                        "first_at": endpoints[0][1].isoformat(),
                        "last": endpoints[-1][0],
                        "last_at": endpoints[-1][1].isoformat(),
                    }
                )
        return {
            "schema_version": schema_version,
            "row_counts": counts,
            "grant_count": grant_count,
            "audit_endpoints": audit_endpoints,
        }
    finally:
        engine.dispose()


def _object_keys(client: Any, bucket: str) -> list[str]:
    keys: list[str] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        keys.extend(str(item["Key"]) for item in page.get("Contents", []))
    return sorted(keys)


def _safe_object_path(key: str) -> Path:
    path = PurePosixPath(key)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("object key cannot be represented safely in a backup")
    return Path(*path.parts)


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _expand(command: tuple[str, ...], source: Path, destination: Path) -> list[str]:
    expanded = [
        item.replace("{input}", str(source)).replace("{output}", str(destination))
        for item in command
    ]
    if not any("{input}" in item for item in command) or not any(
        "{output}" in item for item in command
    ):
        raise ValueError("encryption command must contain {input} and {output} placeholders")
    return expanded


def _database_name(url: str) -> str:
    name = urlsplit(url).path.lstrip("/")
    if not name:
        raise ValueError("database URL must name a database")
    return name


def _postgres_cli_url(url: str) -> str:
    parsed = urlsplit(url)
    scheme = parsed.scheme.split("+", 1)[0]
    if not parsed.hostname or not parsed.username:
        raise ValueError("database URL must include a host and username")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    netloc = f"{quote(parsed.username, safe='')}@{host}"
    if parsed.port is not None:
        netloc += f":{parsed.port}"
    return urlunsplit((scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _write_pgpass(url: str, path: Path) -> None:
    parsed = urlsplit(url)
    if not parsed.hostname or not parsed.username or parsed.password is None:
        raise ValueError("database URL must include host, username, and password")
    values = (
        parsed.hostname,
        str(parsed.port or 5432),
        _database_name(url),
        parsed.username,
        parsed.password,
    )
    escaped = [value.replace("\\", "\\\\").replace(":", "\\:") for value in values]
    path.write_text(":".join(escaped) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _run_database_command(run: RunCommand | None, command: list[str], pgpass: Path) -> None:
    if run is not None:
        run(command)
        return
    environment = {**os.environ, "PGPASSFILE": str(pgpass)}
    subprocess.run(command, check=True, env=environment)


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def _command(value: str) -> tuple[str, ...]:
    parsed = json.loads(value)
    if (
        not isinstance(parsed, list)
        or not parsed
        or not all(isinstance(item, str) for item in parsed)
    ):
        raise argparse.ArgumentTypeError("command must be a JSON array of strings")
    return tuple(parsed)


def _secret_env(name: str) -> str | None:
    direct = os.environ.get(name)
    filename = os.environ.get(f"{name}_FILE")
    if direct is not None and filename is not None:
        raise ValueError(f"configure either {name} or {name}_FILE")
    if filename is not None:
        return Path(filename).read_text(encoding="utf-8").strip()
    return direct


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=_secret_env("SCI_SEARCH_DATABASE_URL"))
    parser.add_argument("--s3-endpoint", default=os.environ.get("SCI_SEARCH_S3_ENDPOINT"))
    parser.add_argument("--s3-bucket", default=os.environ.get("SCI_SEARCH_S3_BUCKET"))
    parser.add_argument("--s3-access-key", default=_secret_env("SCI_SEARCH_S3_ACCESS_KEY"))
    parser.add_argument("--s3-secret-key", default=_secret_env("SCI_SEARCH_S3_SECRET_KEY"))
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--pg-dump-command", type=_command, default=("pg_dump",))
    parser.add_argument("--encryption-command", type=_command, required=True)
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
    create_backup(
        BackupConfig(
            arguments.database_url,
            arguments.s3_bucket,
            arguments.destination,
            arguments.pg_dump_command,
            arguments.encryption_command,
        ),
        s3_client=client,
    )


if __name__ == "__main__":
    main()
