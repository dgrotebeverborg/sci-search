"""Same-origin researcher frontend routes and static assets."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from sci_search.application.sessions import InvalidSession

_FRONTEND_ROOT = Path(__file__).resolve().parents[1] / "frontend"
STATIC_DIRECTORY = _FRONTEND_ROOT / "static"
_templates = Jinja2Templates(directory=_FRONTEND_ROOT / "templates")
router = APIRouter(include_in_schema=False)


def static_asset_prefix() -> str:
    """A shared versioned directory keeps the entire ES-module graph in sync."""
    digest = hashlib.sha256()
    for path in sorted(STATIC_DIRECTORY.iterdir()):
        if path.suffix in {".js", ".css"}:
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return f"/static/v-{digest.hexdigest()[:16]}"


@router.get("/")
def root(request: Request) -> RedirectResponse:
    settings = request.app.state.api_settings
    token = request.cookies.get(settings.session_cookie_name, "")
    if not token:
        return RedirectResponse("/auth/login", status_code=303)
    try:
        request.app.state.api_services.sessions.authenticate(token)
    except InvalidSession:
        return RedirectResponse("/auth/login", status_code=303)
    return RedirectResponse("/app", status_code=303)


@router.get("/auth/login", response_class=HTMLResponse)
def login(request: Request) -> HTMLResponse:
    return _templates.TemplateResponse(
        request,
        "login.html",
        {
            "development_auth_enabled": request.app.state.api_settings.development_auth_enabled,
            "static_prefix": request.app.state.frontend_static_prefix,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/auth/development")
def development_login(
    request: Request,
    user_id: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
) -> RedirectResponse:
    settings = request.app.state.api_settings
    if not settings.development_auth_enabled or settings.environment == "production":
        return RedirectResponse("/auth/login", status_code=303)
    issued = request.app.state.api_services.sessions.create(user_id or settings.development_user_id)
    response = RedirectResponse("/app", status_code=303)
    response.set_cookie(
        settings.session_cookie_name,
        issued.token,
        secure=False,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/app", response_class=HTMLResponse)
def researcher_app(request: Request) -> HTMLResponse:
    return _templates.TemplateResponse(
        request,
        "app.html",
        {
            "static_prefix": request.app.state.frontend_static_prefix,
            "workspace_preview": request.app.state.api_settings.workspace_preview,
            "local_research_enabled": request.app.state.api_settings.local_research_enabled,
        },
        headers={"Cache-Control": "no-store"},
    )
