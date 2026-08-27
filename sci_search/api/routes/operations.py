"""Liveness, readiness, and Prometheus-compatible operational routes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from botocore.config import Config
from fastapi import APIRouter, Response, status
from redis import Redis
from sqlalchemy import create_engine, text

from sci_search.infrastructure.observability import Metrics
from sci_search.infrastructure.settings import ProductionSettings


@dataclass(frozen=True, slots=True)
class OperationalChecks:
    database: Callable[[], bool]
    redis: Callable[[], bool]
    object_store: Callable[[], bool]


def production_operational_checks(settings: ProductionSettings) -> OperationalChecks:
    """Build bounded, side-effect-free dependency probes for production readiness."""

    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_timeout=2,
        connect_args={"connect_timeout": 2},
    )
    redis = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=2,
        socket_timeout=2,
        decode_responses=False,
    )
    import boto3

    object_store = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        config=Config(connect_timeout=2, read_timeout=2, retries={"max_attempts": 1}),
    )

    def database_ready() -> bool:
        with engine.connect() as connection:
            return connection.scalar(text("SELECT 1")) == 1

    def redis_ready() -> bool:
        return bool(redis.ping())

    def object_store_ready() -> bool:
        object_store.head_bucket(Bucket=settings.s3_bucket)
        return True

    return OperationalChecks(database_ready, redis_ready, object_store_ready)


def create_operations_router(checks: OperationalChecks, metrics: Metrics) -> APIRouter:
    router = APIRouter(include_in_schema=False)

    @router.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/health/ready")
    def ready(response: Response) -> dict[str, object]:
        dependencies: dict[str, str] = {}
        for name, check in (
            ("database", checks.database),
            ("redis", checks.redis),
            ("object_store", checks.object_store),
        ):
            try:
                healthy = check()
            except Exception:
                healthy = False
            dependencies[name] = "ok" if healthy else "failed"
        ready_now = all(value == "ok" for value in dependencies.values())
        if not ready_now:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "ready" if ready_now else "not_ready", "dependencies": dependencies}

    @router.get("/metrics")
    def prometheus_metrics() -> Response:
        return Response(
            metrics.render(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    return router
