from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from alembic import command
from dramatiq.brokers.redis import RedisBroker
from redis import Redis
from sqlalchemy import func, select

from sci_search.infrastructure.database import Database
from sci_search.infrastructure.jobs import SqlJobRepository
from sci_search.infrastructure.queue import RedisJobQueue
from sci_search.infrastructure.tables import AuditEventRow, JobCheckpointRow, JobRow
from sci_search.worker import StageWork, TransientStageError, Worker
from tests.integration.test_migrations import DATABASE_URL, _configuration
from tests.integration.test_research_storage import _project

NOW = datetime(2026, 8, 27, 16, 0, tzinfo=UTC)
REDIS_URL = os.environ.get("SCI_SEARCH_TEST_REDIS_URL", "redis://127.0.0.1:56379/15")


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


def _job(database: Database) -> str:
    project_id, user_id = _project(database, "worker-owner")
    with database.transaction() as session:
        return (
            SqlJobRepository(session)
            .create(
                project_id,
                created_by_user_id=user_id,
                idempotency_key="worker-test",
                first_stage="planning",
                input_payload={"question": "What is known?"},
                created_at=NOW,
            )
            .id
        )


def test_duplicate_delivery_executes_stage_side_effect_once(database: Database) -> None:
    job_id = _job(database)
    queue = RecordingQueue()
    side_effects: list[str] = []

    def planning(_input: dict[str, object]) -> StageWork:
        side_effects.append("planned")
        return StageWork(
            output={"plan": ["query"]},
            next_stage="discovery",
            input_fingerprint="question-v1",
            implementation_version="planning-v1",
        )

    worker = Worker(
        database, queue, {"planning": planning}, worker_id="worker-a", clock=lambda: NOW
    )
    assert worker.execute(job_id, "planning") == "checkpointed"
    assert worker.execute(job_id, "planning") == "already_checkpointed"

    assert side_effects == ["planned"]
    assert queue.messages == [(job_id, "discovery"), (job_id, "discovery")]
    with database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(JobCheckpointRow)) == 1


def test_redelivery_after_checkpoint_before_ack_advances_without_repeating_stage(
    database: Database,
) -> None:
    job_id = _job(database)
    queue = RecordingQueue()
    side_effects: list[str] = []
    crashed = False

    def planning(_input: dict[str, object]) -> StageWork:
        side_effects.append("planned")
        return StageWork({}, "discovery", "question-v1", "planning-v1")

    def crash_once() -> None:
        nonlocal crashed
        if not crashed:
            crashed = True
            raise RuntimeError("simulated process death after commit")

    first_worker = Worker(
        database,
        queue,
        {"planning": planning},
        worker_id="worker-before-crash",
        clock=lambda: NOW,
        after_checkpoint=crash_once,
    )
    with pytest.raises(RuntimeError, match="simulated process death"):
        first_worker.execute(job_id, "planning")
    assert queue.messages == []

    recovered = Worker(
        database,
        queue,
        {"planning": planning},
        worker_id="worker-after-crash",
        clock=lambda: NOW,
    )
    assert recovered.execute(job_id, "planning") == "already_checkpointed"
    assert side_effects == ["planned"]
    assert queue.messages == [(job_id, "discovery")]


def test_permanent_failure_dead_letters_once(database: Database) -> None:
    job_id = _job(database)
    queue = RecordingQueue()

    def invalid(_input: dict[str, object]) -> StageWork:
        raise ValueError("invalid scientific input")

    worker = Worker(database, queue, {"planning": invalid}, worker_id="worker-a", clock=lambda: NOW)
    assert worker.execute(job_id, "planning") == "dead_lettered"
    assert queue.messages == []
    with database.transaction() as session:
        job = session.get(JobRow, _uuid(job_id))
        assert job is not None
        assert job.status == "failed"
        actions = set(session.scalars(select(AuditEventRow.action)).all())
        assert {"job.failed", "job.dead_lettered"} <= actions


def test_transient_failures_retry_only_to_the_configured_bound(database: Database) -> None:
    job_id = _job(database)
    queue = RecordingQueue()
    attempts = 0

    def unavailable(_input: dict[str, object]) -> StageWork:
        nonlocal attempts
        attempts += 1
        raise TransientStageError("provider temporarily unavailable")

    worker = Worker(
        database,
        queue,
        {"planning": unavailable},
        worker_id="worker-a",
        clock=lambda: NOW,
        max_attempts=2,
    )
    assert worker.execute(job_id, "planning") == "retry_scheduled"
    assert worker.execute(job_id, "planning") == "dead_lettered"
    assert attempts == 2
    assert queue.messages == [(job_id, "planning")]


def test_redis_queue_round_trip_uses_only_opaque_job_and_stage_ids() -> None:
    Redis.from_url(REDIS_URL).flushdb()
    broker = RedisBroker(url=REDIS_URL, middleware=[])
    queue = RedisJobQueue(broker, queue_name="sci-search-test")
    queue.enqueue("10000000-0000-0000-0000-000000000099", "planning")

    consumer = broker.consume("sci-search-test", prefetch=1, timeout=1000)
    message = next(consumer)
    try:
        assert message.args == ("10000000-0000-0000-0000-000000000099", "planning")
        assert message.kwargs == {}
    finally:
        consumer.ack(message)
        consumer.close()
        broker.close()


def _uuid(value: str):
    from uuid import UUID

    return UUID(value)
