"""Restart-safe execution of one durable research stage per queue message."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from dramatiq import Actor, actor
from dramatiq.broker import Broker

from sci_search.application.jobs import JobStatus
from sci_search.infrastructure.database import Database
from sci_search.infrastructure.jobs import LeaseRejected, SqlJobRepository
from sci_search.infrastructure.queue import JobQueue


@dataclass(frozen=True, slots=True)
class StageWork:
    output: dict[str, Any]
    next_stage: str
    input_fingerprint: str
    implementation_version: str


class StageExecutor(Protocol):
    def __call__(self, input_payload: dict[str, Any]) -> StageWork: ...


class TransientStageError(RuntimeError):
    """A bounded retry may succeed without changing the scientific input."""


class Worker:
    def __init__(
        self,
        database: Database,
        queue: JobQueue,
        stages: Mapping[str, StageExecutor],
        *,
        worker_id: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        lease_for: timedelta = timedelta(minutes=5),
        max_attempts: int = 3,
        after_checkpoint: Callable[[], None] | None = None,
    ) -> None:
        self._database = database
        self._queue = queue
        self._stages = stages
        self._worker_id = worker_id
        self._clock = clock
        self._lease_for = lease_for
        self._max_attempts = max_attempts
        self._after_checkpoint = after_checkpoint or (lambda: None)

    def execute(self, job_id: str, stage_name: str) -> str:
        with self._database.transaction() as session:
            current = SqlJobRepository(session).get_for_worker(job_id)
        if current.status in {JobStatus.COMPLETED, JobStatus.CANCELLED}:
            return "terminal"
        if current.status is JobStatus.FAILED:
            return "dead_lettered"
        if current.current_stage != stage_name:
            self._queue.enqueue(job_id, current.current_stage)
            return "already_checkpointed"

        now = self._clock()
        try:
            with self._database.transaction() as session:
                claimed = SqlJobRepository(session).claim(
                    job_id, self._worker_id, now=now, lease_for=self._lease_for
                )
        except LeaseRejected:
            return "busy"

        executor = self._stages.get(stage_name)
        if executor is None:
            return self._fail(job_id, ValueError("unknown stage"), transient=False)
        try:
            work = executor(claimed.input_payload)
        except TransientStageError as error:
            return self._fail(job_id, error, transient=True)
        except Exception as error:
            return self._fail(job_id, error, transient=False)

        with self._database.transaction() as session:
            SqlJobRepository(session).checkpoint(
                job_id,
                self._worker_id,
                stage_name=stage_name,
                input_fingerprint=work.input_fingerprint,
                implementation_version=work.implementation_version,
                output=work.output,
                next_stage=work.next_stage,
                now=self._clock(),
            )
        # This hook models a process dying after commit and before queue acknowledgement.
        self._after_checkpoint()
        self._queue.enqueue(job_id, work.next_stage)
        return "checkpointed"

    def _fail(self, job_id: str, error: Exception, *, transient: bool) -> str:
        details = {
            "category": "transient" if transient else "invalid_or_permanent",
            "type": type(error).__name__,
        }
        retry = False
        with self._database.transaction() as session:
            jobs = SqlJobRepository(session)
            failed = jobs.fail(job_id, self._worker_id, error=details, now=self._clock())
            if transient and failed.attempt_count < self._max_attempts:
                jobs.retry_failed(job_id, now=self._clock())
                retry = True
            else:
                jobs.record_dead_letter(job_id, error=details, now=self._clock())
        if retry:
            self._queue.enqueue(job_id, failed.current_stage)
            return "retry_scheduled"
        return "dead_lettered"


def register_worker_actor(
    broker: Broker,
    worker: Worker,
    *,
    queue_name: str = "sci-search",
    actor_name: str = "sci_search.execute_job",
) -> Actor:
    """Register the thin Dramatiq wakeup actor around a configured worker."""

    def execute_job(job_id: str, stage_name: str) -> str:
        return worker.execute(job_id, stage_name)

    return actor(
        execute_job,
        broker=broker,
        queue_name=queue_name,
        actor_name=actor_name,
        max_retries=0,  # Retry policy is bounded and persisted by Worker/SqlJobRepository.
    )
