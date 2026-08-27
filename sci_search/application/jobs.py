"""Durable research-job state and transition contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"


class JobTransitionError(ValueError):
    pass


_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED}),
    JobStatus.RUNNING: frozenset(
        {JobStatus.CANCEL_REQUESTED, JobStatus.FAILED, JobStatus.COMPLETED}
    ),
    JobStatus.CANCEL_REQUESTED: frozenset({JobStatus.CANCELLED}),
    JobStatus.CANCELLED: frozenset(),
    JobStatus.FAILED: frozenset({JobStatus.QUEUED}),
    JobStatus.COMPLETED: frozenset(),
}


def transition(current: JobStatus, target: JobStatus) -> JobStatus:
    if target not in _TRANSITIONS[current]:
        raise JobTransitionError(f"invalid job transition: {current.value} -> {target.value}")
    return target


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    project_id: str
    created_by_user_id: str
    idempotency_key: str
    status: JobStatus
    current_stage: str
    input_payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    lease_owner: str | None
    lease_expires_at: datetime | None
    version: int
    attempt_count: int


@dataclass(frozen=True, slots=True)
class StageAttempt:
    id: str
    job_id: str
    stage_name: str
    worker_id: str
    attempt_number: int
    started_at: datetime
    finished_at: datetime | None
    outcome: str | None
    error: dict[str, Any] | None
