"""Authentication callback and hardened session-cookie handling."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from starlette.requests import Request
from starlette.responses import RedirectResponse

from sci_search.application.identity import ProvisioningRepositories, provision_user
from sci_search.application.sessions import InvalidSession, SessionService
from sci_search.infrastructure.oidc import OidcPrincipal


class CallbackIdentityProvider(Protocol):
    async def exchange_callback(self, request: Request) -> OidcPrincipal: ...


class AuthController:
    def __init__(
        self,
        provider: CallbackIdentityProvider,
        repositories: ProvisioningRepositories,
        sessions: SessionService,
        *,
        clock: Callable[[], datetime],
        success_url: str,
        cookie_name: str = "sci_search_session",
    ) -> None:
        if not success_url.startswith("/") or success_url.startswith("//"):
            raise ValueError("success URL must be an application-relative path")
        self._provider = provider
        self._repositories = repositories
        self._sessions = sessions
        self._clock = clock
        self._success_url = success_url
        self._cookie_name = cookie_name

    async def callback(self, request: Request) -> RedirectResponse:
        principal = await self._provider.exchange_callback(request)
        provisioned = provision_user(
            principal.identity,
            principal.profile,
            self._repositories,
            self._clock,
        )
        previous_token = request.cookies.get(self._cookie_name)
        if previous_token:
            try:
                self._sessions.revoke(previous_token)
            except InvalidSession:
                pass
        issued = self._sessions.create(provisioned.user.id)
        max_age = max(0, int((issued.absolute_expires_at - self._clock()).total_seconds()))
        response = RedirectResponse(self._success_url, status_code=303)
        response.set_cookie(
            self._cookie_name,
            issued.token,
            max_age=max_age,
            secure=True,
            httponly=True,
            samesite="lax",
            path="/",
        )
        return response
