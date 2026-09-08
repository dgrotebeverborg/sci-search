from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import boto3
import psycopg
import pytest
from alembic import command
from botocore.config import Config

from sci_search.application.identity import ExternalIdentity, IdentityProfile, provision_user
from sci_search.application.projects import Membership, Project, ProjectRole
from sci_search.infrastructure.database import Database
from sci_search.infrastructure.repositories import AuditEvent, SqlUnitOfWork
from sci_search.infrastructure.s3_blobs import S3BlobStore
from scripts.backup import BackupConfig, create_backup
from scripts.restore import RestoreConfig, restore_backup
from scripts.verify_restore import VerificationResult, verify_restore
from tests.integration.test_migrations import DATABASE_URL, _configuration


class FakeS3:
    def __init__(self, buckets: dict[str, dict[str, bytes]]) -> None:
        self.buckets = buckets

    def get_paginator(self, operation: str):
        assert operation == "list_objects_v2"
        return self

    def paginate(self, *, Bucket: str):
        yield {"Contents": [{"Key": key} for key in sorted(self.buckets[Bucket])]}

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        Path(filename).write_bytes(self.buckets[bucket][key])

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        self.buckets.setdefault(bucket, {})[key] = Path(filename).read_bytes()

    def head_bucket(self, *, Bucket: str) -> None:
        if Bucket not in self.buckets:
            raise KeyError(Bucket)

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, int]:
        return {"ContentLength": len(self.buckets[Bucket][Key])}

    def get_object(self, *, Bucket: str, Key: str):
        from io import BytesIO

        return {"Body": BytesIO(self.buckets[Bucket][Key])}


def _runner(command: list[str]) -> None:
    if command[0] == "fake-pg-dump":
        output = Path(command[command.index("--file") + 1])
        output.write_bytes(b"database-with-two-projects-and-one-shared-document")
    elif command[0] in {"fake-encrypt", "fake-decrypt"}:
        shutil.copyfile(command[-2], command[-1])
    elif command[0] == "fake-pg-restore":
        assert "--no-owner" in command and "--no-privileges" in command
    else:  # pragma: no cover - catches accidental shell/tool expansion
        raise AssertionError(command)


def test_backup_restore_round_trip_has_versioned_manifest_and_atomic_marker(
    tmp_path: Path,
) -> None:
    paper = b"shared scientific full text"
    report = b"representative literature review"
    source = {
        "objects/aa/bb/" + "a" * 64: paper,
        "artifacts/review.pdf": report,
    }
    s3 = FakeS3({"source": source, "restored": {}})
    output = tmp_path / "backup-20260827"
    database_state = {
        "schema_version": "0005_gold_labels",
        "row_counts": {"projects": 2, "documents": 1, "project_document_grants": 2},
        "grant_count": 2,
        "audit_endpoints": {"count": 4, "first": "audit-1", "last": "audit-4"},
    }
    commands: list[list[str]] = []

    def recorded_runner(command: list[str]) -> None:
        commands.append(command)
        _runner(command)

    manifest = create_backup(
        BackupConfig(
            database_url="postgresql+psycopg://user:secret@postgres/source_db",
            bucket="source",
            destination=output,
            pg_dump_command=("fake-pg-dump",),
            encryption_command=("fake-encrypt", "{input}", "{output}"),
        ),
        s3_client=s3,
        run=recorded_runner,
        inspect_database=lambda _url: database_state,
    )

    assert (output / "COMPLETE").read_text(encoding="utf-8").strip() == manifest["backup_id"]
    assert not any(tmp_path.glob("*.partial-*"))
    persisted = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert persisted["format_version"] == 1
    assert persisted["database"]["row_counts"]["projects"] == 2
    assert persisted["database"]["grant_count"] == 2
    assert persisted["objects"][0]["sha256"]
    assert persisted["encryption"]["enabled"] is True
    assert "secret" not in json.dumps(persisted)
    assert "secret" not in json.dumps(commands)

    restored = restore_backup(
        RestoreConfig(
            source=output,
            database_url="postgresql+psycopg://user:new-secret@postgres/restored_db",
            bucket="restored",
            pg_restore_command=("fake-pg-restore",),
            decryption_command=("fake-decrypt", "{input}", "{output}"),
        ),
        s3_client=s3,
        run=_runner,
        assert_empty_database=lambda _url: None,
    )
    assert restored["restored_objects"] == 2
    assert s3.buckets["restored"] == source

    result = verify_restore(
        output,
        database_url="postgresql+psycopg://user:new-secret@postgres/restored_db",
        bucket="restored",
        s3_client=s3,
        inspect_database=lambda _url: database_state,
    )
    assert result == VerificationResult(ok=True, checked_objects=2, errors=())

    persisted["database"]["row_counts"]["projects"] = 999
    (output / "manifest.json").write_text(json.dumps(persisted), encoding="utf-8")
    s3.buckets["tampered-target"] = {}
    with pytest.raises(ValueError, match="encrypted inventory"):
        restore_backup(
            RestoreConfig(
                source=output,
                database_url="postgresql://user:new-secret@postgres/tampered_db",
                bucket="tampered-target",
                pg_restore_command=("fake-pg-restore",),
                decryption_command=("fake-decrypt", "{input}", "{output}"),
            ),
            s3_client=s3,
            run=_runner,
            assert_empty_database=lambda _url: None,
        )


def test_backup_requires_encryption_and_restore_requires_new_targets(tmp_path: Path) -> None:
    s3 = FakeS3({"source": {}})
    with pytest.raises(ValueError, match="encryption command"):
        create_backup(
            BackupConfig(
                database_url="postgresql://user:secret@postgres/source_db",
                bucket="source",
                destination=tmp_path / "backup",
                pg_dump_command=("fake-pg-dump",),
                encryption_command=(),
            ),
            s3_client=s3,
            run=_runner,
            inspect_database=lambda _url: {},
        )


def test_restore_rejects_incomplete_or_tampered_backup(tmp_path: Path) -> None:
    source = tmp_path / "backup"
    source.mkdir()
    (source / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="complete"):
        restore_backup(
            RestoreConfig(
                source=source,
                database_url="postgresql://user:secret@postgres/restored_db",
                bucket="restored",
                pg_restore_command=("fake-pg-restore",),
                decryption_command=("fake-decrypt", "{input}", "{output}"),
            ),
            s3_client=FakeS3({"restored": {}}),
            run=_runner,
            assert_empty_database=lambda _url: None,
        )


@pytest.mark.skipif(
    os.environ.get("SCI_SEARCH_BACKUP_SYSTEM_TESTS") != "1",
    reason="set SCI_SEARCH_BACKUP_SYSTEM_TESTS=1 for the destructive isolated restore drill",
)
def test_real_postgres_and_minio_restore_drill(tmp_path: Path) -> None:
    """Prove two project grants to one blob and a report survive a real restore."""

    image = os.environ.get("SCI_SEARCH_TEST_IMAGE", "sci-search:program7-test")
    source_bucket = "sci-search-backup-source"
    restored_bucket = "sci-search-backup-restored"
    restored_database = "sci_search_restore_test"
    restored_url = DATABASE_URL.rsplit("/", 1)[0] + "/" + restored_database
    s3 = boto3.client(
        "s3",
        endpoint_url="http://127.0.0.1:59000",
        aws_access_key_id="sci_search",
        aws_secret_access_key="sci_search_test_password",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    _reset_bucket(s3, source_bucket)
    _reset_bucket(s3, restored_bucket)
    _reset_restore_database(restored_database)
    command.downgrade(_configuration(DATABASE_URL), "base")
    command.upgrade(_configuration(DATABASE_URL), "head")
    now = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    database = Database(DATABASE_URL)
    try:
        users = []
        for subject in ("backup-alice", "backup-bob"):
            with database.transaction() as session:
                users.append(
                    provision_user(
                        ExternalIdentity("https://connect.surfconext.nl", subject),
                        IdentityProfile(email=f"{subject}@example.test"),
                        SqlUnitOfWork(session).provisioning,
                        clock=lambda: now,
                    )
                )
        projects: list[Project] = []
        for index, provisioned in enumerate(users, start=1):
            project = Project(
                str(uuid4()),
                provisioned.workspace.id,
                f"Backup project {index}",
                provisioned.user.id,
                True,
                now,
            )
            with database.transaction() as session:
                repositories = SqlUnitOfWork(session)
                repositories.projects.add_project(project)
                repositories.projects.add_membership(
                    Membership(
                        str(uuid4()),
                        provisioned.user.id,
                        ProjectRole.OWNER,
                        True,
                        now,
                        project_id=project.id,
                    )
                )
            projects.append(project)

        store = S3BlobStore(s3, source_bucket)
        paper = store.put(BytesIO(b"one shared full-text paper"), 1024)
        report = store.put(BytesIO(b"representative generated review PDF"), 1024)
        with database.transaction() as session:
            repositories = SqlUnitOfWork(session)
            for project, user in zip(projects, users, strict=True):
                repositories.research.grant_document(
                    project.id,
                    canonical_publication_key="doi:10.0000/shared",
                    title="Shared source paper",
                    blob=paper,
                )
                repositories.audit.add(
                    AuditEvent(
                        str(uuid4()),
                        now,
                        "backup.seeded",
                        "project",
                        project.id,
                        {},
                        actor_user_id=user.user.id,
                        project_id=project.id,
                    )
                )
            repositories.research.add_artifact(
                projects[0].id,
                run_id=None,
                kind="literature-review.pdf",
                blob_key=report.key,
                input_fingerprint="backup-drill",
                generator_version="test",
                created_at=now,
            )
    finally:
        database.dispose()

    tmp_path.chmod(0o777)
    mount = f"type=bind,source={tmp_path},target=/backup"
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--mount",
            mount,
            "--entrypoint",
            "age-keygen",
            image,
            "--output",
            "/backup/key.txt",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    recipient = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--mount",
            mount,
            "--entrypoint",
            "age-keygen",
            image,
            "--y",
            "/backup/key.txt",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    common = [
        "docker",
        "run",
        "--rm",
        "--network",
        "host",
        "--mount",
        mount,
        "--env",
        f"SCI_SEARCH_DATABASE_URL={DATABASE_URL}",
        "--env",
        "SCI_SEARCH_S3_ENDPOINT=http://127.0.0.1:59000",
        "--env",
        "SCI_SEARCH_S3_BUCKET=" + source_bucket,
        "--env",
        "SCI_SEARCH_S3_ACCESS_KEY=sci_search",
        "--env",
        "SCI_SEARCH_S3_SECRET_KEY=sci_search_test_password",
        image,
    ]
    subprocess.run(
        [
            *common,
            "backup",
            "--destination",
            "/backup/snapshot",
            "--encryption-command",
            json.dumps(["age", "--recipient", recipient, "--output", "{output}", "{input}"]),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    target_common = [
        item.replace(
            f"SCI_SEARCH_DATABASE_URL={DATABASE_URL}", f"SCI_SEARCH_DATABASE_URL={restored_url}"
        )
        for item in common
    ]
    target_common = [
        item.replace(
            "SCI_SEARCH_S3_BUCKET=" + source_bucket, "SCI_SEARCH_S3_BUCKET=" + restored_bucket
        )
        for item in target_common
    ]
    subprocess.run(
        [
            *target_common,
            "restore",
            "--source",
            "/backup/snapshot",
            "--decryption-command",
            json.dumps(
                [
                    "age",
                    "--decrypt",
                    "--identity",
                    "/backup/key.txt",
                    "--output",
                    "{output}",
                    "{input}",
                ]
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    verified = subprocess.run(
        [*target_common, "verify-restore", "--source", "/backup/snapshot"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(verified.stdout)["ok"] is True


def _reset_bucket(client, bucket: str) -> None:
    try:
        client.create_bucket(Bucket=bucket)
    except client.exceptions.BucketAlreadyOwnedByYou:
        pass
    for item in client.list_objects_v2(Bucket=bucket).get("Contents", []):
        client.delete_object(Bucket=bucket, Key=item["Key"])


def _reset_restore_database(name: str) -> None:
    with psycopg.connect(
        "postgresql://sci_search:sci_search_test@127.0.0.1:55432/postgres",
        autocommit=True,
    ) as connection:
        connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
            (name,),
        )
        connection.execute(f'DROP DATABASE IF EXISTS "{name}"')
        connection.execute(f'CREATE DATABASE "{name}" OWNER sci_search')
