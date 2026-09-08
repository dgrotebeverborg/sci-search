from __future__ import annotations

import hashlib
import multiprocessing
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from sqlalchemy import func, select

from sci_search.application.blobs import BlobRef
from sci_search.application.quotas import JobQuotaLimits
from sci_search.infrastructure.database import Database
from sci_search.infrastructure.jobs import SqlJobRepository
from sci_search.infrastructure.repositories import SqlResearchRepository
from sci_search.infrastructure.tables import (
    DocumentRow,
    EvidenceRow,
    JobCheckpointRow,
    JobRow,
    StageAttemptRow,
)
from sci_search.worker import StageInvocation, StageWork, Worker
from tests.integration.test_migrations import DATABASE_URL, _configuration
from tests.integration.test_research_storage import _project

NOW = datetime(2026, 8, 27, 18, 0, tzinfo=UTC)
BODY = b"Exact source passage: the measured value was 70 percent."
DIGEST = hashlib.sha256(BODY).hexdigest()


@pytest.fixture
def database() -> Database:
    configuration = _configuration(DATABASE_URL)
    command.downgrade(configuration, "base")
    command.upgrade(configuration, "head")
    database = Database(DATABASE_URL)
    try:
        yield database
    finally:
        database.dispose()


class RecordingQueue:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def enqueue(self, job_id: str, stage_name: str) -> None:
        self.messages.append((job_id, stage_name))


def _grant_document(database: Database, project_id: str) -> str:
    with database.transaction() as session:
        return SqlResearchRepository(session).grant_document(
            project_id,
            canonical_publication_key="doi:10.1234/restart",
            title="Restart-safe study",
            blob=BlobRef(DIGEST, len(BODY), "text/plain", f"objects/{DIGEST}"),
        )


def _crashing_process(
    database_url: str,
    job_id: str,
    project_id: str,
    marker_path: str,
    entered: multiprocessing.synchronize.Event,
) -> None:
    database = Database(database_url)
    marker = Path(marker_path)

    def acquisition(_invocation: StageInvocation) -> StageWork:
        document_id = _grant_document(database, project_id)
        marker.write_text("document committed", encoding="utf-8")
        entered.set()
        time.sleep(60)
        return StageWork({"document_id": document_id}, "analysis", "input-v1", "acquisition-v1")

    Worker(
        database,
        RecordingQueue(),
        {"acquisition": acquisition},
        worker_id="worker-before-termination",
        clock=lambda: NOW,
        lease_for=timedelta(seconds=1),
        quota_limits=JobQuotaLimits.permissive(),
    ).execute(job_id, "acquisition")


def test_worker_termination_reclaims_stage_without_duplicate_publication(
    database: Database, tmp_path: Path
) -> None:
    project_id, user_id = _project(database, "restart-owner")
    with database.transaction() as session:
        job_id = (
            SqlJobRepository(session)
            .create(
                project_id,
                created_by_user_id=user_id,
                idempotency_key="restart-run",
                first_stage="acquisition",
                input_payload={"question": "What value was measured?"},
                created_at=NOW,
            )
            .id
        )

    context = multiprocessing.get_context("fork")
    entered = context.Event()
    marker = tmp_path / "first-attempt.txt"
    process = context.Process(
        target=_crashing_process,
        args=(DATABASE_URL, job_id, project_id, str(marker), entered),
    )
    process.start()
    assert entered.wait(timeout=10), "worker did not enter the acquisition stage"
    process.terminate()
    process.join(timeout=10)
    assert not process.is_alive()

    queue = RecordingQueue()

    def acquisition(_invocation: StageInvocation) -> StageWork:
        document_id = _grant_document(database, project_id)
        return StageWork({"document_id": document_id}, "analysis", "input-v1", "acquisition-v1")

    def analysis(_invocation: StageInvocation) -> StageWork:
        with database.transaction() as session:
            document_id = str(session.scalar(select(DocumentRow.id)))
            evidence_id = SqlResearchRepository(session).add_evidence(
                project_id,
                document_id=document_id,
                statement="The measured value was 70 percent.",
                source_passage="Exact source passage: the measured value was 70 percent.",
                section="Results",
                page=1,
                extraction_method="restart-test",
                created_at=NOW,
            )
        return StageWork(
            {"evidence_id": evidence_id},
            next_stage="complete",
            input_fingerprint="analysis-input-v1",
            implementation_version="analysis-v1",
            complete=True,
        )

    worker = Worker(
        database,
        queue,
        {"acquisition": acquisition, "analysis": analysis},
        worker_id="worker-after-restart",
        clock=lambda: NOW + timedelta(seconds=2),
        lease_for=timedelta(minutes=1),
        quota_limits=JobQuotaLimits.permissive(),
    )
    assert worker.execute(job_id, "acquisition") == "checkpointed"
    assert worker.execute(job_id, "analysis") == "completed"
    assert worker.execute(job_id, "analysis") == "terminal"

    with database.transaction() as session:
        job = session.get(JobRow, UUID(job_id))
        assert job is not None and job.status == "completed"
        assert session.scalar(select(func.count()).select_from(DocumentRow)) == 1
        assert session.scalar(select(func.count()).select_from(EvidenceRow)) == 1
        assert session.scalar(select(func.count()).select_from(JobCheckpointRow)) == 2
        checkpoints = session.scalars(select(JobCheckpointRow)).all()
        assert len({(item.stage_name, item.input_fingerprint) for item in checkpoints}) == 2
        attempts = session.scalars(select(StageAttemptRow)).all()
        assert sum(item.outcome == "lease_expired" for item in attempts) == 1
