"""Bounded metrics, correlation context, and payload-safe structured logging."""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar, Token
from enum import StrEnum
from time import perf_counter
from typing import Any
from uuid import uuid4

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_CORRELATION_ID: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SAFE_EVENT = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "content",
        "document",
        "document_text",
        "full_text",
        "id_token",
        "password",
        "passage",
        "prompt",
        "question",
        "refresh_token",
        "secret",
        "session",
        "source_passage",
        "text",
        "token",
    }
)
_ROUTES = frozenset(
    {
        "/",
        "/api/v1/audit",
        "/api/v1/documents/{document_id}",
        "/api/v1/evidence",
        "/api/v1/exports",
        "/api/v1/exports/{export_id}",
        "/api/v1/projects",
        "/api/v1/projects/{project_id}",
        "/api/v1/projects/{project_id}/members",
        "/api/v1/risk-of-bias",
        "/api/v1/runs",
        "/api/v1/runs/{run_id}",
        "/api/v1/session",
        "/api/v1/session/logout",
        "/api/v1/validation",
        "/api/v1/workspaces",
        "/auth/callback",
        "/auth/login",
        "/health/live",
        "/health/ready",
        "/metrics",
        "/static/{path}",
        "unmatched",
    }
)
_METHODS = frozenset({"DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"})
_ROLES = frozenset({"anonymous", "owner", "editor", "reviewer", "viewer", "unknown"})
_STAGES = frozenset(
    {"discover", "acquire", "parse", "extract", "normalize", "analyze", "report", "export"}
)
_PROVIDERS = frozenset(
    {"crossref", "europe_pmc", "openalex", "scientific_memory", "mistral", "openai", "codex", "other"}
)
_ACQUISITION_OUTCOMES = frozenset(
    {"acquired", "not_open", "not_found", "invalid", "too_large", "failed"}
)
_WITHHOLDING_REASONS = frozenset(
    {"insufficient_evidence", "incomplete_coverage", "validation_failed", "other"}
)
_REJECTION_REASONS = frozenset(
    {"ungrounded", "invalid_schema", "incorrect_provenance", "unsafe_content", "other"}
)


class StageOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProviderOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"


def correlation_id() -> str | None:
    return _CORRELATION_ID.get()


def redact(value: Any, *, key: str | None = None) -> Any:
    """Return a recursively sanitized copy suitable for operational logs."""

    if key is not None and key.casefold() in _SENSITIVE_KEYS:
        return "<redacted>"
    if isinstance(value, dict):
        return {str(item_key): redact(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


class JsonLogFormatter(logging.Formatter):
    """One-line JSON formatter with an allowlisted event envelope."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        payload: dict[str, Any] = {
            "level": record.levelname.casefold(),
            "logger": record.name,
            "event": message if _SAFE_EVENT.fullmatch(message) else "unstructured.redacted",
        }
        request_id = getattr(record, "request_id", None) or correlation_id()
        if request_id:
            payload["request_id"] = request_id
        context = getattr(record, "context", None)
        if context is not None:
            payload["context"] = redact(context)
        if record.exc_info:
            exception_type = record.exc_info[0]
            if exception_type is not None:
                payload["exception_type"] = exception_type.__name__
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def configure_json_logging(level: int = logging.INFO) -> None:
    """Install a single redacting JSON handler for application and dependency logs."""

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("authlib.integrations.base_client.sync_app").setLevel(logging.INFO)


class CorrelationIdMiddleware:
    """Propagate an opaque safe request identifier through response and log context."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        supplied = headers.get(b"x-request-id", b"").decode("ascii", errors="ignore")
        request_id = supplied if _SAFE_REQUEST_ID.fullmatch(supplied) else str(uuid4())
        scope.setdefault("state", {})["correlation_id"] = request_id
        token: Token[str | None] = _CORRELATION_ID.set(request_id)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append(
                    (b"x-request-id", request_id.encode("ascii"))
                )
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            _CORRELATION_ID.reset(token)


class Metrics:
    """Private registry whose public methods enforce finite-cardinality labels."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        self._requests = Histogram(
            "sci_search_http_request_duration_seconds",
            "HTTP request latency",
            ("method", "route", "status_class"),
            registry=self.registry,
        )
        self._denials = Counter(
            "sci_search_authorization_denials",
            "Authorization denials",
            ("role",),
            registry=self.registry,
        )
        self._stage = Histogram(
            "sci_search_stage_duration_seconds",
            "Pipeline stage latency",
            ("stage", "outcome"),
            registry=self.registry,
        )
        self._providers = Counter(
            "sci_search_provider_outcomes",
            "Provider outcomes",
            ("provider", "outcome"),
            registry=self.registry,
        )
        self._acquisitions = Counter(
            "sci_search_acquisition_outcomes",
            "Full-text acquisition outcomes",
            ("outcome",),
            registry=self.registry,
        )
        self._queue_depth = Gauge("sci_search_queue_depth", "Queued jobs", registry=self.registry)
        self._queue_age = Gauge(
            "sci_search_queue_oldest_age_seconds",
            "Age of oldest queued job",
            registry=self.registry,
        )
        self._leases = Gauge(
            "sci_search_active_leases", "Active worker leases", registry=self.registry
        )
        self._storage = Gauge(
            "sci_search_storage_bytes", "Object storage bytes", registry=self.registry
        )
        self._evidence = Counter(
            "sci_search_evidence", "Evidence records published", registry=self.registry
        )
        self._withholding = Counter(
            "sci_search_answer_withholding",
            "Answers withheld by bounded reason",
            ("reason",),
            registry=self.registry,
        )
        self._model_rejections = Counter(
            "sci_search_model_validation_rejections",
            "Model outputs rejected by validation",
            ("reason",),
            registry=self.registry,
        )

    def observe_request(self, method: str, route: str, status: int, seconds: float) -> None:
        self._require(method, _METHODS)
        self._require(route, _ROUTES)
        status_class = f"{status // 100}xx" if 100 <= status <= 599 else "other"
        self._requests.labels(method, route, status_class).observe(max(0.0, seconds))

    def record_authorization_denial(self, role: str) -> None:
        self._require(role, _ROLES)
        self._denials.labels(role).inc()

    def record_stage(self, stage: str, outcome: StageOutcome, seconds: float) -> None:
        self._require(stage, _STAGES)
        self._stage.labels(stage, outcome.value).observe(max(0.0, seconds))

    def record_provider(self, provider: str, outcome: ProviderOutcome) -> None:
        self._require(provider, _PROVIDERS)
        self._providers.labels(provider, outcome.value).inc()

    def record_acquisition(self, outcome: str) -> None:
        self._require(outcome, _ACQUISITION_OUTCOMES)
        self._acquisitions.labels(outcome).inc()

    def set_queue(self, *, depth: int, oldest_age_seconds: float, active_leases: int) -> None:
        self._queue_depth.set(max(0, depth))
        self._queue_age.set(max(0.0, oldest_age_seconds))
        self._leases.set(max(0, active_leases))

    def set_storage_bytes(self, value: int) -> None:
        self._storage.set(max(0, value))

    def record_evidence(self, amount: int = 1) -> None:
        if amount < 0:
            raise ValueError("metric increments must be non-negative")
        self._evidence.inc(amount)

    def record_withholding(self, reason: str) -> None:
        self._require(reason, _WITHHOLDING_REASONS)
        self._withholding.labels(reason).inc()

    def record_model_rejection(self, reason: str) -> None:
        self._require(reason, _REJECTION_REASONS)
        self._model_rejections.labels(reason).inc()

    def render(self) -> bytes:
        return generate_latest(self.registry)

    @staticmethod
    def _require(value: str, allowed: frozenset[str]) -> None:
        if value not in allowed:
            raise ValueError("metric label must use a bounded allowlisted value")


class RequestMetricsMiddleware:
    """Measure requests using Starlette's resolved route template when available."""

    def __init__(self, app: ASGIApp, metrics: Metrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = perf_counter()
        status = 500

        async def capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            route_object = scope.get("route")
            route = getattr(route_object, "path", "unmatched")
            if route not in _ROUTES:
                route = "unmatched"
            method = str(scope.get("method", "GET"))
            if method not in _METHODS:
                method = "GET"
            self.metrics.observe_request(method, route, status, perf_counter() - started)
