"""Institutional OIDC authorization-code routes with durable opaque sessions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, Request
from starlette.responses import RedirectResponse

from sci_search.application.identity import provision_user
from sci_search.application.sessions import InvalidSession, SessionService
from sci_search.infrastructure.database import Database
from sci_search.infrastructure.oidc import OidcProvider
from sci_search.infrastructure.repositories import SqlSessionRepository, SqlUnitOfWork


def create_authentication_router(
    provider: OidcProvider,
    database: Database,
    *,
    clock: Callable[[], datetime],
    cookie_name: str = "sci_search_session",
) -> APIRouter:
    router = APIRouter(tags=["authentication"])

    @router.get("/auth/oidc/start")
    async def oidc_start(request: Request) -> RedirectResponse:
        return await provider.authorization_redirect(request)

    @router.get("/auth/callback")
    async def oidc_callback(request: Request) -> RedirectResponse:
        principal = await provider.exchange_callback(request)
        with database.transaction() as session:
            repositories = SqlUnitOfWork(session)
            provisioned = provision_user(
                principal.identity,
                principal.profile,
                repositories.provisioning,
                clock,
            )
            sessions = SessionService(SqlSessionRepository(session), clock=clock)
            previous = request.cookies.get(cookie_name)
            if previous:
                try:
                    sessions.revoke(previous)
                except InvalidSession:
                    pass
            issued = sessions.create(provisioned.user.id)
        max_age = max(0, int((issued.absolute_expires_at - clock()).total_seconds()))
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            cookie_name,
            issued.token,
            max_age=max_age,
            secure=True,
            httponly=True,
            samesite="lax",
            path="/",
        )
        return response

    return router
