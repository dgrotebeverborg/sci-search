from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from sqlalchemy import func, select

from sci_search.application.jobs import JobStatus, JobTransitionError, transition
from sci_search.infrastructure.database import Database
from sci_search.infrastructure.jobs import LeaseRejected, SqlJobRepository
from sci_search.infrastructure.tables import JobCheckpointRow, JobRow, StageAttemptRow
from tests.integration.test_migrations import DATABASE_URL, _configuration
from tests.integration.test_research_storage import _project

NOW = datetime(2026, 8, 27, 15, 0, tzinfo=UTC)


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


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (JobStatus.QUEUED, JobStatus.RUNNING),
        (JobStatus.QUEUED, JobStatus.CANCEL_REQUESTED),
        (JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED),
        (JobStatus.RUNNING, JobStatus.FAILED),
        (JobStatus.RUNNING, JobStatus.COMPLETED),
        (JobStatus.CANCEL_REQUESTED, JobStatus.CANCELLED),
        (JobStatus.FAILED, JobStatus.QUEUED),
    ],
)
def test_valid_job_transitions(current: JobStatus, target: JobStatus) -> None:
    assert transition(current, target) is target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (JobStatus.QUEUED, JobStatus.COMPLETED),
        (JobStatus.RUNNING, JobStatus.QUEUED),
        (JobStatus.CANCEL_REQUESTED, JobStatus.COMPLETED),
        (JobStatus.CANCELLED, JobStatus.QUEUED),
        (JobStatus.COMPLETED, JobStatus.RUNNING),
        (JobStatus.FAILED, JobStatus.COMPLETED),
    ],
)
def test_invalid_job_transitions_are_literal_errors(current: JobStatus, target: JobStatus) -> None:
    with pytest.raises(JobTransitionError, match=f"{current.value} -> {target.value}"):
        transition(current, target)


def test_repeated_idempotency_key_returns_one_job(database: Database) -> None:
    project_id, user_id = _project(database, "job-owner")
    with database.transaction() as session:
        jobs = SqlJobRepository(session)
        first = jobs.create(
            project_id,
            created_by_user_id=user_id,
            idempotency_key="start-request-1",
            first_stage="planning",
            input_payload={"question": "What is known?"},
            created_at=NOW,
        )
        second = jobs.create(
            project_id,
            created_by_user_id=user_id,
            idempotency_key="start-request-1",
            first_stage="planning",
            input_payload={"question": "What is known?"},
            created_at=NOW,
        )
        assert first.id == second.id
    with database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(JobRow)) == 1


def test_one_lease_heartbeat_expiry_reclaim_and_stale_owner_rejection(
    database: Database,
) -> None:
    project_id, user_id = _project(database, "lease-owner")
    with database.transaction() as session:
        job = SqlJobRepository(session).create(
            project_id,
            created_by_user_id=user_id,
            idempotency_key="lease-test",
            first_stage="planning",
            input_payload={"question": "Q"},
            created_at=NOW,
        )

    with database.transaction() as session:
        jobs = SqlJobRepository(session)
        claimed = jobs.claim(job.id, "worker-a", now=NOW, lease_for=timedelta(seconds=30))
        assert claimed.lease_owner == "worker-a"
        assert claimed.lease_expires_at == NOW + timedelta(seconds=30)
        with pytest.raises(LeaseRejected):
            jobs.claim(job.id, "worker-b", now=NOW, lease_for=timedelta(seconds=30))

    with database.transaction() as session:
        extended = SqlJobRepository(session).heartbeat(
            job.id,
            "worker-a",
            now=NOW + timedelta(seconds=10),
            lease_for=timedelta(seconds=40),
        )
        assert extended.lease_expires_at == NOW + timedelta(seconds=50)

    reclaimed_at = NOW + timedelta(seconds=51)
    with database.transaction() as session:
        reclaimed = SqlJobRepository(session).claim(
            job.id, "worker-b", now=reclaimed_at, lease_for=timedelta(seconds=30)
        )
        assert reclaimed.lease_owner == "worker-b"

    with database.transaction() as session:
        jobs = SqlJobRepository(session)
        with pytest.raises(LeaseRejected):
            jobs.checkpoint(
                job.id,
                "worker-a",
                stage_name="planning",
                input_fingerprint="input-v1",
                implementation_version="planning-v1",
                output={"plan": "stale"},
                next_stage="discovery",
                now=reclaimed_at + timedelta(seconds=1),
            )
        jobs.checkpoint(
            job.id,
            "worker-b",
            stage_name="planning",
            input_fingerprint="input-v1",
            implementation_version="planning-v1",
            output={"plan": "accepted"},
            next_stage="discovery",
            now=reclaimed_at + timedelta(seconds=1),
        )

    with database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(JobCheckpointRow)) == 1
        attempts = session.scalars(
            select(StageAttemptRow).order_by(StageAttemptRow.started_at)
        ).all()
        assert [attempt.worker_id for attempt in attempts] == ["worker-a", "worker-b"]
        assert attempts[0].outcome == "lease_expired"
        job_row = session.get(JobRow, _uuid(job.id))
        assert job_row is not None
        assert job_row.current_stage == "discovery"


def _uuid(value: str):
    from uuid import UUID

    return UUID(value)
