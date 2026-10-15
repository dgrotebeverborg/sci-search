"""Importable Dramatiq production composition for the worker container."""

from __future__ import annotations

import os
import socket
from pathlib import Path

import boto3
import dramatiq
from botocore.config import Config
from dramatiq.brokers.redis import RedisBroker

from sci_search.infrastructure.dashboard_rebuild import ProductionDashboardRebuildStage
from sci_search.infrastructure.database import Database
from sci_search.infrastructure.queue import RedisJobQueue
from sci_search.infrastructure.research_execution import ProductionResearchStage
from sci_search.infrastructure.s3_blobs import S3BlobStore
from sci_search.infrastructure.settings import ProductionSettings
from sci_search.worker import Worker, register_worker_actor

settings = ProductionSettings.from_environment()
for variable in ("OPENALEX_API_KEY", "MISTRAL_API_KEY", "OPENAI_API_KEY"):
    filename = os.environ.get(f"{variable}_FILE", "")
    if filename:
        os.environ[variable] = Path(filename).read_text(encoding="utf-8").strip()
database = Database(settings.database_url)
object_client = boto3.client(
    "s3",
    endpoint_url=settings.s3_endpoint,
    aws_access_key_id=settings.s3_access_key,
    aws_secret_access_key=settings.s3_secret_key,
    config=Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 2}),
)
blobs = S3BlobStore(object_client, settings.s3_bucket)
broker = RedisBroker(url=settings.redis_url)
dramatiq.set_broker(broker)
queue = RedisJobQueue(broker)
worker = Worker(
    database,
    queue,
    {
        "research": ProductionResearchStage(database, blobs),
        "dashboard_rebuild": ProductionDashboardRebuildStage(database, blobs),
    },
    worker_id=f"{socket.gethostname()}:{os.getpid()}",
)
execute_job = register_worker_actor(broker, worker)
