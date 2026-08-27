from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from sci_search.api.app import ApiSettings, create_app
from sci_search.api.dependencies import ApiServices, AuthenticatedPrincipal, require_principal
from sci_search.application.authorization import ResourceNotFound
from sci_search.application.sessions import (
    InMemorySessionRepository,
    InvalidSession,
    SessionService,
)

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
ORIGIN = "https://app.example.test"
STRONG_SECRET = "test-only-secret-that-is-at-least-32-characters"


@pytest.fixture
def session_service() -> SessionService:
    return SessionService(
        InMemorySessionRepository(),
        clock=lambda: NOW,
        token_source=lambda _: "valid-browser-session-token",
    )


@pytest.fixture
def api_settings() -> ApiSettings:
    return ApiSettings(
        environment="test",
        allowed_origins=(ORIGIN,),
        oidc_callback_url=f"{ORIGIN}/auth/callback",
        session_secret=STRONG_SECRET,
        max_request_body_bytes=64,
    )


@pytest.fixture
def client(api_settings: ApiSettings, session_service: SessionService) -> TestClient:
    app = create_app(api_settings, ApiServices(sessions=session_service))
    return TestClient(app, base_url=ORIGIN)


def test_session_endpoint_denies_unauthenticated_request(client: TestClient) -> None:
    response = client.get("/api/v1/session")

    assert response.status_code == 401
    assert response.json() == {"detail": "authentication required"}


def test_every_response_has_restrictive_security_headers(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "unsafe-inline" not in response.headers["content-security-policy"]
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"


def test_cors_allows_only_the_configured_same_origin(client: TestClient) -> None:
    allowed = client.options(
        "/api/v1/session",
        headers={
            "origin": ORIGIN,
            "access-control-request-method": "GET",
        },
    )
    denied = client.options(
        "/api/v1/session",
        headers={
            "origin": "https://attacker.example",
            "access-control-request-method": "GET",
        },
    )

    assert allowed.headers["access-control-allow-origin"] == ORIGIN
    assert "access-control-allow-origin" not in denied.headers


def test_request_body_limit_is_enforced_before_route_processing(client: TestClient) -> None:
    response = client.post(
        "/api/v1/session/logout",
        content=b"x" * 65,
        headers={"content-type": "application/octet-stream"},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "request body too large"}


def test_state_change_requires_session_bound_csrf_token(
    api_settings: ApiSettings,
    session_service: SessionService,
) -> None:
    issued = session_service.create("researcher-1")
    app = create_app(api_settings, ApiServices(sessions=session_service))
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set(api_settings.session_cookie_name, issued.token)
        rejected = client.post("/api/v1/session/logout")
        session = client.get("/api/v1/session")
        accepted = client.post(
            "/api/v1/session/logout",
            headers={api_settings.csrf_header_name: session.json()["csrf_token"]},
        )

    assert rejected.status_code == 403
    assert rejected.json() == {"detail": "CSRF validation failed"}
    assert accepted.status_code == 204
    assert api_settings.session_cookie_name not in accepted.cookies
    with pytest.raises(InvalidSession):
        session_service.authenticate(issued.token)


def test_missing_and_inaccessible_resources_have_identical_responses(
    api_settings: ApiSettings,
    session_service: SessionService,
) -> None:
    issued = session_service.create("researcher-1")
    app = create_app(api_settings, ApiServices(sessions=session_service))

    @app.get("/api/v1/security-probe/{resource_state}")
    def probe(
        resource_state: str,
        principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
    ) -> None:
        assert principal.user_id == "researcher-1"
        assert resource_state in {"missing", "inaccessible"}
        raise ResourceNotFound

    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set(api_settings.session_cookie_name, issued.token)
        missing = client.get("/api/v1/security-probe/missing")
        inaccessible = client.get("/api/v1/security-probe/inaccessible")

    assert missing.status_code == inaccessible.status_code == 404
    assert missing.content == inaccessible.content
    assert missing.json() == {"detail": "resource not found"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("allowed_origins", ("*",)),
        ("allowed_origins", ("http://app.example.test",)),
        ("oidc_callback_url", "http://app.example.test/auth/callback"),
        ("development_auth_enabled", True),
        ("session_secret", "change-me"),
    ],
)
def test_production_rejects_insecure_configuration(field: str, value: object) -> None:
    arguments: dict[str, object] = {
        "environment": "production",
        "allowed_origins": (ORIGIN,),
        "oidc_callback_url": f"{ORIGIN}/auth/callback",
        "session_secret": STRONG_SECRET,
    }
    arguments[field] = value

    with pytest.raises(ValueError):
        ApiSettings(**arguments)  # type: ignore[arg-type]
