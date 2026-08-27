"""PostgreSQL-authoritative durable job repository."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as OrmSession

from sci_search.application.authorization import ResourceNotFound
from sci_search.application.jobs import Job, JobStatus, transition
from sci_search.infrastructure.tables import (
    AuditEventRow,
    JobCheckpointRow,
    JobRow,
    ProjectRow,
    StageAttemptRow,
    UserRow,
)


class LeaseRejected(RuntimeError):
    def __init__(self) -> None:
        super().__init__("job lease is not owned or is no longer valid")


def _uuid(value: str) -> UUID:
    return UUID(value)


def _job(row: JobRow) -> Job:
    return Job(
        id=str(row.id),
        project_id=str(row.project_id),
        created_by_user_id=str(row.created_by_user_id),
        idempotency_key=row.idempotency_key,
        status=JobStatus(row.status),
        current_stage=row.current_stage,
        input_payload=row.input_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
        lease_owner=row.lease_owner,
        lease_expires_at=row.lease_expires_at,
        version=row.version,
        attempt_count=row.attempt_count,
    )


class SqlJobRepository:
    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def create(
        self,
        project_id: str,
        *,
        created_by_user_id: str,
        idempotency_key: str,
        first_stage: str,
        input_payload: dict[str, Any],
        created_at: datetime,
    ) -> Job:
        project_uuid = _uuid(project_id)
        user_uuid = _uuid(created_by_user_id)
        if (
            self._session.get(ProjectRow, project_uuid) is None
            or self._session.get(UserRow, user_uuid) is None
        ):
            raise ResourceNotFound
        if not idempotency_key.strip() or not first_stage.strip():
            raise ValueError("idempotency key and first stage are required")
        job_id = uuid4()
        created_id = self._session.scalar(
            insert(JobRow)
            .values(
                id=job_id,
                project_id=project_uuid,
                created_by_user_id=user_uuid,
                idempotency_key=idempotency_key,
                status=JobStatus.QUEUED.value,
                current_stage=first_stage,
                input_json=input_payload,
                created_at=created_at,
                updated_at=created_at,
                version=1,
                attempt_count=0,
            )
            .on_conflict_do_nothing(index_elements=["project_id", "idempotency_key"])
            .returning(JobRow.id)
        )
        if created_id is None:
            row = self._session.scalar(
                select(JobRow).where(
                    JobRow.project_id == project_uuid,
                    JobRow.idempotency_key == idempotency_key,
                )
            )
            if row is None:  # Defensive: a conflicting transaction cannot disappear after commit.
                raise RuntimeError("idempotent job creation could not resolve existing job")
            return _job(row)
        row = self._session.get(JobRow, created_id)
        if row is None:  # pragma: no cover - INSERT RETURNING guarantees this.
            raise RuntimeError("created job was not returned")
        self._audit(
            row,
            action="job.created",
            occurred_at=created_at,
            actor_user_id=created_by_user_id,
            payload={"first_stage": first_stage},
        )
        return _job(row)

    def get(self, project_id: str, job_id: str) -> Job:
        row = self._session.scalar(
            select(JobRow).where(JobRow.id == _uuid(job_id), JobRow.project_id == _uuid(project_id))
        )
        if row is None:
            raise ResourceNotFound
        return _job(row)

    def get_for_worker(self, job_id: str) -> Job:
        """Trusted worker lookup; browser/API callers must use project-scoped ``get``."""
        row = self._session.get(JobRow, _uuid(job_id))
        if row is None:
            raise ResourceNotFound
        return _job(row)

    def claim(
        self,
        job_id: str,
        worker_id: str,
        *,
        now: datetime,
        lease_for: timedelta,
    ) -> Job:
        if lease_for <= timedelta(0):
            raise ValueError("lease duration must be positive")
        job_uuid = _uuid(job_id)
        row = self._session.scalar(
            update(JobRow)
            .where(
                JobRow.id == job_uuid,
                or_(
                    JobRow.status == JobStatus.QUEUED.value,
                    and_(
                        JobRow.status == JobStatus.RUNNING.value,
                        or_(JobRow.lease_expires_at.is_(None), JobRow.lease_expires_at <= now),
                    ),
                ),
            )
            .values(
                status=JobStatus.RUNNING.value,
                lease_owner=worker_id,
                lease_expires_at=now + lease_for,
                updated_at=now,
                version=JobRow.version + 1,
                attempt_count=JobRow.attempt_count + 1,
            )
            .returning(JobRow)
        )
        if row is None:
            raise LeaseRejected
        self._session.execute(
            update(StageAttemptRow)
            .where(StageAttemptRow.job_id == job_uuid, StageAttemptRow.finished_at.is_(None))
            .values(finished_at=now, outcome="lease_expired")
        )
        attempt = StageAttemptRow(
            id=uuid4(),
            job_id=job_uuid,
            stage_name=row.current_stage,
            worker_id=worker_id,
            attempt_number=row.attempt_count,
            started_at=now,
        )
        self._session.add(attempt)
        self._session.flush([attempt])
        return _job(row)

    def heartbeat(
        self,
        job_id: str,
        worker_id: str,
        *,
        now: datetime,
        lease_for: timedelta,
    ) -> Job:
        row = self._session.scalar(
            update(JobRow)
            .where(*self._active_lease_conditions(job_id, worker_id, now))
            .values(
                lease_expires_at=now + lease_for,
                updated_at=now,
                version=JobRow.version + 1,
            )
            .returning(JobRow)
        )
        if row is None:
            raise LeaseRejected
        return _job(row)

    def checkpoint(
        self,
        job_id: str,
        worker_id: str,
        *,
        stage_name: str,
        input_fingerprint: str,
        implementation_version: str,
        output: dict[str, Any],
        next_stage: str,
        now: datetime,
    ) -> Job:
        job_uuid = _uuid(job_id)
        row = self._session.scalar(
            update(JobRow)
            .where(
                *self._active_lease_conditions(job_id, worker_id, now),
                JobRow.current_stage == stage_name,
            )
            .values(
                current_stage=next_stage,
                lease_owner=None,
                lease_expires_at=None,
                updated_at=now,
                version=JobRow.version + 1,
            )
            .returning(JobRow)
        )
        if row is None:
            raise LeaseRejected
        checkpoint = JobCheckpointRow(
            id=uuid4(),
            job_id=job_uuid,
            stage_name=stage_name,
            input_fingerprint=input_fingerprint,
            implementation_version=implementation_version,
            output_json=output,
            completed_at=now,
        )
        self._session.add(checkpoint)
        self._finish_attempt(job_uuid, worker_id, now=now, outcome="succeeded")
        self._session.flush([checkpoint])
        self._audit(
            row,
            action="job.stage_checkpointed",
            occurred_at=now,
            payload={
                "stage": stage_name,
                "next_stage": next_stage,
                "input_fingerprint": input_fingerprint,
                "implementation_version": implementation_version,
            },
        )
        return _job(row)

    def fail(
        self,
        job_id: str,
        worker_id: str,
        *,
        error: dict[str, Any],
        now: datetime,
    ) -> Job:
        row = self._terminal_from_active_lease(job_id, worker_id, JobStatus.FAILED, now=now)
        self._finish_attempt(_uuid(job_id), worker_id, now=now, outcome="failed", error=error)
        self._audit(row, action="job.failed", occurred_at=now, payload=error)
        return _job(row)

    def complete(self, job_id: str, worker_id: str, *, now: datetime) -> Job:
        row = self._terminal_from_active_lease(job_id, worker_id, JobStatus.COMPLETED, now=now)
        self._finish_attempt(_uuid(job_id), worker_id, now=now, outcome="succeeded")
        self._audit(row, action="job.completed", occurred_at=now)
        return _job(row)

    def request_cancel(self, project_id: str, job_id: str, *, now: datetime) -> Job:
        row = self._session.scalar(
            update(JobRow)
            .where(
                JobRow.id == _uuid(job_id),
                JobRow.project_id == _uuid(project_id),
                JobRow.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value]),
            )
            .values(
                status=JobStatus.CANCEL_REQUESTED.value,
                updated_at=now,
                version=JobRow.version + 1,
            )
            .returning(JobRow)
        )
        if row is None:
            existing = self.get(project_id, job_id)
            if existing.status is JobStatus.CANCEL_REQUESTED:
                return existing
            raise LeaseRejected
        self._audit(row, action="job.cancel_requested", occurred_at=now)
        return _job(row)

    def retry_failed(self, job_id: str, *, now: datetime) -> Job:
        transition(JobStatus.FAILED, JobStatus.QUEUED)
        row = self._session.scalar(
            update(JobRow)
            .where(JobRow.id == _uuid(job_id), JobRow.status == JobStatus.FAILED.value)
            .values(
                status=JobStatus.QUEUED.value,
                updated_at=now,
                version=JobRow.version + 1,
            )
            .returning(JobRow)
        )
        if row is None:
            raise LeaseRejected
        self._audit(row, action="job.retry_scheduled", occurred_at=now)
        return _job(row)

    def record_dead_letter(self, job_id: str, *, error: dict[str, Any], now: datetime) -> None:
        row = self._session.get(JobRow, _uuid(job_id))
        if row is None:
            raise ResourceNotFound
        if row.status != JobStatus.FAILED.value:
            raise LeaseRejected
        self._audit(row, action="job.dead_lettered", occurred_at=now, payload=error)

    def _terminal_from_active_lease(
        self,
        job_id: str,
        worker_id: str,
        target: JobStatus,
        *,
        now: datetime,
    ) -> JobRow:
        transition(JobStatus.RUNNING, target)
        row = self._session.scalar(
            update(JobRow)
            .where(*self._active_lease_conditions(job_id, worker_id, now))
            .values(
                status=target.value,
                lease_owner=None,
                lease_expires_at=None,
                updated_at=now,
                version=JobRow.version + 1,
            )
            .returning(JobRow)
        )
        if row is None:
            raise LeaseRejected
        return row

    @staticmethod
    def _active_lease_conditions(job_id: str, worker_id: str, now: datetime) -> tuple[Any, ...]:
        return (
            JobRow.id == _uuid(job_id),
            JobRow.status == JobStatus.RUNNING.value,
            JobRow.lease_owner == worker_id,
            JobRow.lease_expires_at > now,
        )

    def _finish_attempt(
        self,
        job_id: UUID,
        worker_id: str,
        *,
        now: datetime,
        outcome: str,
        error: dict[str, Any] | None = None,
    ) -> None:
        result = self._session.execute(
            update(StageAttemptRow)
            .where(
                StageAttemptRow.job_id == job_id,
                StageAttemptRow.worker_id == worker_id,
                StageAttemptRow.finished_at.is_(None),
            )
            .values(finished_at=now, outcome=outcome, error_json=error)
        )
        if result.rowcount != 1:  # type: ignore[attr-defined]
            raise LeaseRejected

    def _audit(
        self,
        job: JobRow,
        *,
        action: str,
        occurred_at: datetime,
        actor_user_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._session.add(
            AuditEventRow(
                id=uuid4(),
                occurred_at=occurred_at,
                actor_user_id=_uuid(actor_user_id) if actor_user_id else None,
                project_id=job.project_id,
                action=action,
                entity_type="job",
                entity_id=str(job.id),
                payload=payload or {},
            )
        )
