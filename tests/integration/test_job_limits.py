from __future__ import annotations

from datetime import UTC, datetime

import pytest
from alembic import command
from sqlalchemy import func, select

from sci_search.application.quotas import JobQuotaLimits, QuotaExceeded
from sci_search.infrastructure.database import Database
from sci_search.infrastructure.jobs import SqlJobRepository
from sci_search.infrastructure.tables import JobCheckpointRow, JobRow
from sci_search.worker import StageInvocation, StageWork, Worker
from tests.integration.test_migrations import DATABASE_URL, _configuration
from tests.integration.test_research_storage import _project

NOW = datetime(2026, 8, 27, 17, 0, tzinfo=UTC)


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


def _create(
    database: Database,
    project_id: str,
    user_id: str,
    key: str,
    limits: JobQuotaLimits,
) -> str:
    with database.transaction() as session:
        return (
            SqlJobRepository(session)
            .create(
                project_id,
                created_by_user_id=user_id,
                idempotency_key=key,
                first_stage="acquisition",
                input_payload={"question": "Q"},
                created_at=NOW,
                quota_limits=limits,
            )
            .id
        )


@pytest.mark.parametrize("scope", ["global_queued", "workspace_queued", "user_queued"])
def test_queue_saturation_at_each_scope(database: Database, scope: str) -> None:
    project_id, user_id = _project(database, "quota-owner")
    limits = JobQuotaLimits(
        global_active=2,
        global_queued=1 if scope == "global_queued" else 5,
        workspace_active=2,
        workspace_queued=1 if scope == "workspace_queued" else 5,
        user_active=1,
        user_queued=1 if scope == "user_queued" else 5,
    )
    first = _create(database, project_id, user_id, "first", limits)
    with pytest.raises(QuotaExceeded, match=scope):
        _create(database, project_id, user_id, "second", limits)
    assert _create(database, project_id, user_id, "first", limits) == first


def test_active_quota_releases_after_completion(database: Database) -> None:
    project_id, user_id = _project(database, "active-owner")
    limits = JobQuotaLimits(
        global_active=1,
        global_queued=5,
        workspace_active=1,
        workspace_queued=5,
        user_active=1,
        user_queued=5,
    )
    first = _create(database, project_id, user_id, "first", limits)
    second = _create(database, project_id, user_id, "second", limits)
    with database.transaction() as session:
        jobs = SqlJobRepository(session)
        jobs.claim(first, "worker-a", now=NOW, quota_limits=limits)
        with pytest.raises(QuotaExceeded, match="global_active"):
            jobs.claim(second, "worker-b", now=NOW, quota_limits=limits)
    with database.transaction() as session:
        SqlJobRepository(session).complete(first, "worker-a", now=NOW)
    with database.transaction() as session:
        claimed = SqlJobRepository(session).claim(second, "worker-b", now=NOW, quota_limits=limits)
        assert claimed.lease_owner == "worker-b"


def test_cancellation_inside_acquisition_retains_prior_checkpoint_and_publishes_no_more(
    database: Database,
) -> None:
    project_id, user_id = _project(database, "cancel-owner")
    limits = JobQuotaLimits.permissive()
    job_id = _create(database, project_id, user_id, "cancel", limits)
    with database.transaction() as session:
        jobs = SqlJobRepository(session)
        jobs.claim(job_id, "setup-worker", now=NOW, quota_limits=limits)
        jobs.checkpoint(
            job_id,
            "setup-worker",
            stage_name="acquisition",
            input_fingerprint="batch-0",
            implementation_version="acquisition-v1",
            output={"documents": ["already-published"]},
            next_stage="gap_search",
            now=NOW,
        )

    processed: list[int] = []

    def gap_search(invocation: StageInvocation) -> StageWork:
        for item in range(5):
            invocation.cancellation.raise_if_requested()
            processed.append(item)
            if item == 0:
                with database.transaction() as session:
                    SqlJobRepository(session).request_cancel(project_id, job_id, now=NOW)
        return StageWork({"new": "must-not-publish"}, "analysis", "batch-1", "gap-v1")

    queue = RecordingQueue()
    worker = Worker(
        database,
        queue,
        {"gap_search": gap_search},
        worker_id="cancel-worker",
        clock=lambda: NOW,
        quota_limits=limits,
    )
    assert worker.execute(job_id, "gap_search") == "cancelled"
    assert processed == [0]
    assert queue.messages == []

    with database.transaction() as session:
        row = session.get(JobRow, _uuid(job_id))
        assert row is not None
        assert row.status == "cancelled"
        assert row.current_stage == "gap_search"
        assert session.scalar(select(func.count()).select_from(JobCheckpointRow)) == 1


def _uuid(value: str):
    from uuid import UUID

    return UUID(value)
