from __future__ import annotations

import json
import logging
from collections.abc import Callable

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from sci_search.api.routes.operations import OperationalChecks, create_operations_router
from sci_search.infrastructure.observability import (
    CorrelationIdMiddleware,
    JsonLogFormatter,
    Metrics,
    ProviderOutcome,
    StageOutcome,
    redact,
)


def test_correlation_id_is_propagated_or_safely_replaced() -> None:
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/probe")
    def probe(request: Request) -> dict[str, str]:
        return {"request_id": request.state.correlation_id}

    client = TestClient(app)
    supplied = client.get("/probe", headers={"X-Request-ID": "req-0123_test"})
    unsafe = client.get("/probe", headers={"X-Request-ID": "question text / token=secret"})

    assert supplied.headers["X-Request-ID"] == "req-0123_test"
    assert supplied.json() == {"request_id": "req-0123_test"}
    assert unsafe.headers["X-Request-ID"] != "question text / token=secret"
    assert len(unsafe.headers["X-Request-ID"]) == 36


def test_json_logs_redact_secrets_and_scientific_payloads() -> None:
    record = logging.LogRecord(
        "sci_search",
        logging.INFO,
        __file__,
        1,
        "provider.completed",
        (),
        None,
    )
    record.request_id = "request-1"  # type: ignore[attr-defined]
    record.context = {  # type: ignore[attr-defined]
        "project_id": "project-1",
        "token": "bearer-secret",
        "question": "sensitive research question",
        "nested": {"source_passage": "raw paper text", "status": "accepted"},
    }

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["request_id"] == "request-1"
    assert payload["context"]["project_id"] == "project-1"
    assert payload["context"]["token"] == "<redacted>"
    assert payload["context"]["question"] == "<redacted>"
    assert payload["context"]["nested"]["source_passage"] == "<redacted>"
    assert "bearer-secret" not in json.dumps(payload)
    assert "raw paper text" not in json.dumps(payload)


def test_unstructured_log_messages_are_not_emitted() -> None:
    record = logging.LogRecord(
        "sci_search",
        logging.WARNING,
        __file__,
        1,
        "failed while processing %s",
        ("a raw scientific passage",),
        None,
    )
    payload = json.loads(JsonLogFormatter().format(record))
    assert payload["event"] == "unstructured.redacted"
    assert "raw scientific passage" not in json.dumps(payload)


def test_redaction_is_recursive_and_does_not_mutate_input() -> None:
    source = {"authorization": "secret", "items": [{"prompt": "private", "count": 3}]}
    result = redact(source)
    assert result == {
        "authorization": "<redacted>",
        "items": [{"prompt": "<redacted>", "count": 3}],
    }
    assert source["authorization"] == "secret"


def test_health_distinguishes_liveness_and_dependency_readiness() -> None:
    state = {"database": True, "redis": True, "object_store": True}

    def check(name: str) -> Callable[[], bool]:
        return lambda: state[name]

    app = FastAPI()
    app.include_router(
        create_operations_router(
            OperationalChecks(
                database=check("database"),
                redis=check("redis"),
                object_store=check("object_store"),
            ),
            Metrics(),
        )
    )
    client = TestClient(app)

    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {
        "status": "ready",
        "dependencies": {"database": "ok", "redis": "ok", "object_store": "ok"},
    }
    state["redis"] = False
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["dependencies"]["redis"] == "failed"
    assert client.get("/health/live").status_code == 200


def test_metrics_expose_only_bounded_labels() -> None:
    metrics = Metrics()
    metrics.observe_request("GET", "/api/v1/projects/{project_id}", 200, 0.04)
    metrics.record_authorization_denial("viewer")
    metrics.record_stage("extract", StageOutcome.SUCCEEDED, 1.2)
    metrics.record_provider("mistral", ProviderOutcome.REJECTED)
    metrics.record_acquisition("acquired")
    metrics.set_queue(depth=2, oldest_age_seconds=7.0, active_leases=1)
    metrics.set_storage_bytes(1024)
    metrics.record_evidence(3)
    metrics.record_withholding("insufficient_evidence")
    metrics.record_model_rejection("ungrounded")

    output = metrics.render().decode("utf-8")
    assert "/api/v1/projects/{project_id}" in output
    assert "sci_search_queue_depth 2.0" in output
    assert "sci_search_evidence_total 3.0" in output
    assert "question" not in output.casefold()
    assert "document" not in output.casefold()


@pytest.mark.parametrize(
    ("operation", "value"),
    [
        ("route", "/api/v1/projects/project-user-controlled"),
        ("role", "owner@example.org"),
        ("stage", "a user supplied stage"),
        ("provider", "provider/model/user-value"),
        ("acquisition", "paper title as status"),
        ("withholding", "the entire question"),
        ("rejection", "raw provider error string"),
    ],
)
def test_metrics_reject_unbounded_label_values(operation: str, value: str) -> None:
    metrics = Metrics()
    with pytest.raises(ValueError, match="bounded"):
        if operation == "route":
            metrics.observe_request("GET", value, 200, 0.01)
        elif operation == "role":
            metrics.record_authorization_denial(value)
        elif operation == "stage":
            metrics.record_stage(value, StageOutcome.SUCCEEDED, 0.1)
        elif operation == "provider":
            metrics.record_provider(value, ProviderOutcome.FAILED)
        elif operation == "withholding":
            metrics.record_withholding(value)
        elif operation == "acquisition":
            metrics.record_acquisition(value)
        else:
            metrics.record_model_rejection(value)
