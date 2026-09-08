"""Uniform public API error mapping."""

from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from sci_search.application.authorization import ResourceNotFound
from sci_search.application.research_api import (
    InvalidDocument,
    InvalidRiskOfBiasReference,
    ResourceVersionConflict,
)


async def resource_not_found_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    assert isinstance(error, ResourceNotFound)
    del request, error
    return JSONResponse(status_code=404, content={"detail": "resource not found"})


async def version_conflict_handler(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, ResourceVersionConflict)
    del request, error
    return JSONResponse(status_code=409, content={"detail": "resource version conflict"})


async def invalid_document_handler(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, InvalidDocument)
    del request, error
    return JSONResponse(status_code=422, content={"detail": "invalid authorized upload"})


async def invalid_risk_of_bias_handler(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, InvalidRiskOfBiasReference)
    del request, error
    return JSONResponse(status_code=422, content={"detail": "invalid risk-of-bias judgment"})


async def request_validation_handler(request: Request, error: Exception) -> JSONResponse:
    """Return useful validation locations without reflecting uploaded/request values."""

    assert isinstance(error, RequestValidationError)
    del request
    details = [
        {
            "location": [str(part) for part in item.get("loc", ())],
            "message": str(item.get("msg", "invalid value")),
            "type": str(item.get("type", "value_error")),
        }
        for item in error.errors()
    ]
    return JSONResponse(
        status_code=422, content={"detail": "request validation failed", "errors": details}
    )
