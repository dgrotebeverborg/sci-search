"""Minimal queue contract and Dramatiq Redis delivery adapter."""

from __future__ import annotations

from typing import Protocol

from dramatiq import Message
from dramatiq.broker import Broker


class JobQueue(Protocol):
    def enqueue(self, job_id: str, stage_name: str) -> None: ...


class RedisJobQueue:
    """Deliver opaque wakeups; PostgreSQL remains authoritative for execution."""

    def __init__(
        self,
        broker: Broker,
        *,
        queue_name: str = "sci-search",
        actor_name: str = "sci_search.execute_job",
    ) -> None:
        self._broker = broker
        self._queue_name = queue_name
        self._actor_name = actor_name
        broker.declare_queue(queue_name)

    def enqueue(self, job_id: str, stage_name: str) -> None:
        self._broker.enqueue(
            Message(
                queue_name=self._queue_name,
                actor_name=self._actor_name,
                args=(job_id, stage_name),
                kwargs={},
                options={},
            )
        )
