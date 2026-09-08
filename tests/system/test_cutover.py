from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from alembic import command
from sqlalchemy import func, select

from sci_search.application.identity import ExternalIdentity, IdentityProfile, provision_user
from sci_search.application.jobs import JobStatus
from sci_search.application.projects import Membership, Project, ProjectRole
from sci_search.compatibility.legacy_import import apply_import, compare_parity, scan_legacy
from sci_search.infrastructure.database import Database
from sci_search.infrastructure.filesystem_blobs import FilesystemBlobStore
from sci_search.infrastructure.jobs import SqlJobRepository
from sci_search.infrastructure.repositories import SqlUnitOfWork
from sci_search.infrastructure.tables import AuditEventRow, EvidenceRow, ResearchRunRow
from scripts.deploy import DeployConfig, deploy
from tests.integration.test_legacy_import import _legacy_fixture, _target
from tests.integration.test_migrations import DATABASE_URL, _configuration

NOW = datetime(2026, 8, 27, 16, 0, tzinfo=UTC)


class CutoverRecorder:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run(self, command: list[str], *, timeout: float | None = None) -> None:
        del timeout
        self.commands.append(tuple(command))

    def ready(self, url: str, *, timeout: float) -> bool:
        del url, timeout
        return True


def test_cutover_incremental_import_two_identities_jobs_and_rollback_preserve_data(
    tmp_path: Path,
) -> None:
    configuration = _configuration(DATABASE_URL)
    command.downgrade(configuration, "base")
    command.upgrade(configuration, "head")
    database = Database(DATABASE_URL)
    try:
        source = tmp_path / "protected-source"
        _legacy_fixture(source)
        blobs = FilesystemBlobStore(tmp_path / "target-blobs")
        target = _target(database)
        first = scan_legacy(source)
        assert apply_import(first, target, blobs, apply=True).completed is True
        assert compare_parity(first, target)["passed"] is True

        with database.transaction() as session:
            repositories = SqlUnitOfWork(session)
            second_user = provision_user(
                ExternalIdentity("https://connect.surfconext.nl", "cutover-researcher-2"),
                IdentityProfile(email="researcher-2@mit.example"),
                repositories.provisioning,
                clock=lambda: NOW,
            )
            private_project = Project(
                str(uuid4()),
                second_user.workspace.id,
                "Second researcher private project",
                second_user.user.id,
                True,
                NOW,
            )
            repositories.projects.add_project(private_project)
            repositories.projects.add_membership(
                Membership(
                    str(uuid4()),
                    second_user.user.id,
                    ProjectRole.EDITOR,
                    True,
                    NOW,
                    project_id=target.project_id,
                )
            )

        def create_job(project_id: str, user_id: str, key: str) -> str:
            with database.transaction() as session:
                return (
                    SqlJobRepository(session)
                    .create(
                        project_id,
                        created_by_user_id=user_id,
                        idempotency_key=key,
                        first_stage="discovery",
                        input_payload={"question": key},
                        created_at=NOW,
                    )
                    .id
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            jobs = list(
                executor.map(
                    lambda args: create_job(*args),
                    [
                        (target.project_id, target.actor_user_id, "shared-project-job"),
                        (private_project.id, second_user.user.id, "private-project-job"),
                    ],
                )
            )
        assert len(set(jobs)) == 2

        extra = source / "research_runs" / "legacy-run-2"
        extra.mkdir(parents=True)
        (extra / "run.json").write_text(
            json.dumps(
                {
                    "run_id": "legacy-run-2",
                    "question": "Which result remains uncertain?",
                    "status": "complete",
                    "created_at": NOW.isoformat(),
                    "active_publication_ids": ["legacy-pub-1"],
                }
            ),
            encoding="utf-8",
        )
        final_manifest = scan_legacy(source)
        assert final_manifest.source_fingerprint != first.source_fingerprint
        assert apply_import(final_manifest, target, blobs, apply=True).completed is True
        assert compare_parity(final_manifest, target)["passed"] is True

        recorder = CutoverRecorder()
        result = deploy(
            DeployConfig(
                environment="production",
                hostname="search.uu.nl",
                confirmation="DEPLOY search.uu.nl",
                compose_command=("docker", "compose"),
                backup_command=("verified-backup",),
                readiness_url="https://search.uu.nl/health/ready",
                drain_timeout_seconds=300,
                readiness_timeout_seconds=5,
                readiness_attempts=3,
                state_file=tmp_path / "cutover-state.json",
                previous_image="registry.example/sci-search@sha256:" + "a" * 64,
                migration_rollback_revision="0007_storage_gc",
                readiness_interval_seconds=0,
            ),
            executor=recorder,
        )
        assert result.rollback_eligible is True
        before_rollback = _durable_counts(database)

        # Application rollback changes services/images, never the newly authoritative data store.
        recorder.run(["docker", "compose", "stop", "worker"])
        recorder.run(["docker", "compose", "up", "--detach", "web", "worker"])
        assert _durable_counts(database) == before_rollback
        assert before_rollback["runs"] == 2
        assert before_rollback["evidence"] == 1
        assert before_rollback["queued_jobs"] == 2
        assert before_rollback["audits"] >= 4
    finally:
        database.dispose()


def _durable_counts(database: Database) -> dict[str, int]:
    from sci_search.infrastructure.tables import JobRow

    with database.transaction() as session:
        return {
            "runs": int(session.scalar(select(func.count()).select_from(ResearchRunRow)) or 0),
            "evidence": int(session.scalar(select(func.count()).select_from(EvidenceRow)) or 0),
            "queued_jobs": int(
                session.scalar(
                    select(func.count())
                    .select_from(JobRow)
                    .where(JobRow.status == JobStatus.QUEUED.value)
                )
                or 0
            ),
            "audits": int(session.scalar(select(func.count()).select_from(AuditEventRow)) or 0),
        }
