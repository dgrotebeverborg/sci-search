"""FastAPI application factory with secure production defaults."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sci_search.api.dependencies import (
    ApiServices,
    AuthenticatedPrincipal,
    csrf_token_for,
    require_csrf,
    require_principal,
)
from sci_search.api.errors import resource_not_found_handler
from sci_search.api.routes.projects import router as projects_router
from sci_search.api.schemas import HealthResponse, SessionResponse
from sci_search.application.authorization import ResourceNotFound

Environment = Literal["development", "test", "production"]
_DEFAULT_SECRETS = frozenset({"change-me", "secret", "development-secret", "sci-search"})


@dataclass(frozen=True, slots=True)
class ApiSettings:
    environment: Environment
    allowed_origins: tuple[str, ...]
    oidc_callback_url: str
    session_secret: str
    session_cookie_name: str = "sci_search_session"
    csrf_header_name: str = "X-CSRF-Token"
    max_request_body_bytes: int = 10 * 1024 * 1024
    development_auth_enabled: bool = False

    def __post_init__(self) -> None:
        if self.max_request_body_bytes <= 0:
            raise ValueError("request body limit must be positive")
        if not self.session_cookie_name or not self.csrf_header_name:
            raise ValueError("security names must not be empty")
        if self.environment != "production":
            return
        if not self.allowed_origins or "*" in self.allowed_origins:
            raise ValueError("production requires explicit allowed origins")
        if any(urlparse(origin).scheme != "https" for origin in self.allowed_origins):
            raise ValueError("production origins must use HTTPS")
        callback = urlparse(self.oidc_callback_url)
        if callback.scheme != "https" or not callback.netloc:
            raise ValueError("production OIDC callback must use HTTPS")
        if self.development_auth_enabled:
            raise ValueError("development authentication is forbidden in production")
        if self.session_secret in _DEFAULT_SECRETS or len(self.session_secret) < 32:
            raise ValueError("production session secret is insecure")


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    (
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"no-referrer"),
                        (
                            b"content-security-policy",
                            b"default-src 'self'; object-src 'none'; base-uri 'self'; "
                            b"frame-ancestors 'none'; form-action 'self'",
                        ),
                        (
                            b"permissions-policy",
                            b"camera=(), microphone=(), geolocation=()",
                        ),
                    )
                )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, *, maximum_bytes: int) -> None:
        self.app = app
        self.maximum_bytes = maximum_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        content_length = Headers(scope=scope).get("content-length")
        if content_length is not None:
            try:
                too_large = int(content_length) > self.maximum_bytes
            except ValueError:
                too_large = True
            if too_large:
                await self._reject(scope, receive, send)
                return

        consumed = 0

        async def limited_receive() -> Message:
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.maximum_bytes:
                    raise _RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestBodyTooLarge:
            await self._reject(scope, receive, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            content={"detail": "request body too large"},
        )
        await response(scope, receive, send)


class _RequestBodyTooLarge(Exception):
    pass


def create_app(settings: ApiSettings, services: ApiServices) -> FastAPI:
    """Build the web process around explicit configuration and services."""

    app = FastAPI(title="Sci-Search API", version="1.0.0", docs_url=None, redoc_url=None)
    app.state.api_settings = settings
    app.state.api_services = services
    app.add_exception_handler(ResourceNotFound, resource_not_found_handler)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestBodyLimitMiddleware, maximum_bytes=settings.max_request_body_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", settings.csrf_header_name],
    )
    app.include_router(projects_router)

    @app.get("/api/v1/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/api/v1/session", response_model=SessionResponse)
    def current_session(
        principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
        csrf_token: Annotated[str, Depends(csrf_token_for)],
    ) -> SessionResponse:
        return SessionResponse(user_id=principal.user_id, csrf_token=csrf_token)

    @app.post("/api/v1/session/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout(
        request: Request,
        response: Response,
        principal: Annotated[AuthenticatedPrincipal, Depends(require_csrf)],
    ) -> None:
        del principal
        token = request.cookies[settings.session_cookie_name]
        services.sessions.revoke(token)
        response.delete_cookie(
            settings.session_cookie_name,
            path="/",
            secure=True,
            httponly=True,
            samesite="lax",
        )

    return app
