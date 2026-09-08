from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route
from starlette.testclient import TestClient

from sci_search.api.auth import AuthController
from sci_search.application.identity import (
    ExternalIdentity,
    IdentityProfile,
    InMemoryIdentityRepository,
    ProvisioningRepositories,
)
from sci_search.application.projects import InMemoryProjectRepository
from sci_search.application.sessions import (
    InMemorySessionRepository,
    InvalidSession,
    SessionService,
)
from sci_search.infrastructure.oidc import OidcPrincipal

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


class FakeProvider:
    async def exchange_callback(self, request: Request) -> OidcPrincipal:
        return OidcPrincipal(
            ExternalIdentity("https://connect.surfconext.nl", "stable-subject"),
            IdentityProfile(email="researcher@example.test"),
        )


class TokenSource:
    def __init__(self) -> None:
        self.tokens = iter(("existing-browser-token", "rotated-browser-token"))

    def __call__(self, byte_count: int) -> str:
        assert byte_count == 32
        return next(self.tokens)


def test_callback_sets_hardened_bounded_cookie_and_replaces_existing_session() -> None:
    identities = InMemoryIdentityRepository()
    projects = InMemoryProjectRepository()
    sessions = InMemorySessionRepository()
    service = SessionService(
        sessions,
        clock=lambda: NOW,
        token_source=TokenSource(),
        absolute_lifetime=timedelta(hours=8),
        idle_lifetime=timedelta(minutes=30),
    )
    existing = service.create("previous-user")
    controller = AuthController(
        FakeProvider(),
        ProvisioningRepositories(identities, projects),
        service,
        clock=lambda: NOW,
        success_url="/projects",
    )

    async def callback(request: Request):
        return await controller.callback(request)

    app = Starlette(routes=[Route("/auth/callback", callback)])
    with TestClient(app, base_url="https://app.example.test") as client:
        response = client.get(
            "/auth/callback?code=valid&state=valid",
            headers={"cookie": f"sci_search_session={existing.token}"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/projects"
    set_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Max-Age=28800" in set_cookie
    parsed = SimpleCookie()
    parsed.load(set_cookie)
    new_token = parsed["sci_search_session"].value
    assert new_token == "rotated-browser-token"
    with pytest.raises(InvalidSession):
        service.authenticate(existing.token)
    authenticated = service.authenticate(new_token)
    assert authenticated.user_id == identities.list_users()[0].id
    assert "provider-access-token" not in response.text
    assert "client-secret" not in response.text
