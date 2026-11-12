"""FastAPI application factory with secure production defaults."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sci_search.api.dependencies import (
    ApiServices,
    AuthenticatedPrincipal,
    csrf_token_for,
    require_csrf,
    require_principal,
)
from sci_search.api.errors import (
    invalid_document_handler,
    invalid_risk_of_bias_handler,
    request_validation_handler,
    resource_not_found_handler,
    version_conflict_handler,
)
from sci_search.api.frontend import STATIC_DIRECTORY, static_asset_prefix
from sci_search.api.frontend import router as frontend_router
from sci_search.api.routes.audit import router as audit_router
from sci_search.api.routes.dashboards import router as dashboards_router
from sci_search.api.routes.documents import router as documents_router
from sci_search.api.routes.exports import router as exports_router
from sci_search.api.routes.operations import OperationalChecks, create_operations_router
from sci_search.api.routes.projects import router as projects_router
from sci_search.api.routes.reviews import router as reviews_router
from sci_search.api.routes.runs import router as runs_router
from sci_search.api.routes.workspaces import router as workspaces_router
from sci_search.api.schemas import HealthResponse, SessionResponse
from sci_search.application.authorization import ResourceNotFound
from sci_search.application.research_api import (
    InvalidDocument,
    InvalidRiskOfBiasReference,
    ResourceVersionConflict,
)
from sci_search.infrastructure.observability import (
    CorrelationIdMiddleware,
    Metrics,
    RequestMetricsMiddleware,
)
from sci_search.model_provider import InvalidAnalysisSelection

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
    development_user_id: str = "development-researcher"
    workspace_preview: bool = False
    local_research_enabled: bool = False

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
        if self.local_research_enabled:
            raise ValueError("local research is forbidden in production")
        if self.workspace_preview:
            raise ValueError("workspace preview is forbidden in production")
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


def create_app(
    settings: ApiSettings,
    services: ApiServices,
    operational_checks: OperationalChecks | None = None,
    authentication_router: APIRouter | None = None,
    shutdown: Callable[[], None] | None = None,
) -> FastAPI:
    """Build the web process around explicit configuration and services."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        if shutdown is not None:
            shutdown()

    app = FastAPI(
        title="Sci-Search API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.api_settings = settings
    app.state.api_services = services
    metrics = Metrics()
    app.state.metrics = metrics

    async def invalid_analysis_selection(request: Request, error: InvalidAnalysisSelection):
        return JSONResponse(status_code=422, content={"detail": str(error)})

    app.add_exception_handler(InvalidAnalysisSelection, invalid_analysis_selection)
    app.add_exception_handler(ResourceNotFound, resource_not_found_handler)
    app.add_exception_handler(ResourceVersionConflict, version_conflict_handler)
    app.add_exception_handler(InvalidDocument, invalid_document_handler)
    app.add_exception_handler(InvalidRiskOfBiasReference, invalid_risk_of_bias_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(RequestMetricsMiddleware, metrics=metrics)
    if authentication_router is not None:
        app.add_middleware(
            SessionMiddleware,
            secret_key=settings.session_secret,
            session_cookie="sci_search_oidc_state",
            max_age=600,
            same_site="lax",
            https_only=settings.environment == "production",
        )
    app.add_middleware(RequestBodyLimitMiddleware, maximum_bytes=settings.max_request_body_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", settings.csrf_header_name],
    )
    app.state.frontend_static_prefix = static_asset_prefix()
    app.mount(
        app.state.frontend_static_prefix,
        StaticFiles(directory=STATIC_DIRECTORY),
        name="versioned-static",
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIRECTORY), name="static")
    app.include_router(frontend_router)
    app.include_router(workspaces_router)
    app.include_router(projects_router)
    app.include_router(runs_router)
    app.include_router(dashboards_router)
    app.include_router(documents_router)
    app.include_router(reviews_router)
    app.include_router(exports_router)
    app.include_router(audit_router)
    if authentication_router is not None:
        app.include_router(authentication_router)
    app.include_router(
        create_operations_router(
            operational_checks
            or OperationalChecks(
                database=lambda: True,
                redis=lambda: True,
                object_store=lambda: True,
            ),
            metrics,
        )
    )

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
