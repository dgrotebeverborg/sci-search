"""Uniform public API error mapping."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from sci_search.application.authorization import ResourceNotFound


async def resource_not_found_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    assert isinstance(error, ResourceNotFound)
    del request, error
    return JSONResponse(status_code=404, content={"detail": "resource not found"})
