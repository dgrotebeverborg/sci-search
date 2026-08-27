"""FastAPI dependencies for authentication and request authorization."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from sci_search.application.sessions import InvalidSession, SessionService


@dataclass(frozen=True, slots=True)
class ApiServices:
    """Explicit services available to thin API routes."""

    sessions: SessionService


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    user_id: str
    session_id: str


def _session_token(request: Request) -> str:
    settings = request.app.state.api_settings
    token = request.cookies.get(settings.session_cookie_name, "")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    return token


def require_principal(request: Request) -> AuthenticatedPrincipal:
    """Authenticate an opaque browser session without exposing its token."""

    token = _session_token(request)
    services: ApiServices = request.app.state.api_services
    try:
        session = services.sessions.authenticate(token)
    except InvalidSession as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        ) from error
    return AuthenticatedPrincipal(user_id=session.user_id, session_id=session.id)


def csrf_token_for(request: Request) -> str:
    """Derive a session-bound CSRF value without persisting or exposing the session token."""

    settings = request.app.state.api_settings
    token = _session_token(request)
    return hmac.new(
        settings.session_secret.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def require_csrf(request: Request) -> AuthenticatedPrincipal:
    """Require authentication and a constant-time verified CSRF header."""

    principal = require_principal(request)
    settings = request.app.state.api_settings
    supplied = request.headers.get(settings.csrf_header_name, "")
    expected = csrf_token_for(request)
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed",
        )
    return principal
