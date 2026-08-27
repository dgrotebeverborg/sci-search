"""Shared API schemas with strict input handling."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ApiSchema(BaseModel):
    """Base schema that rejects unrecognised client fields."""

    model_config = ConfigDict(extra="forbid")


class HealthResponse(ApiSchema):
    status: str


class SessionResponse(ApiSchema):
    user_id: str
    csrf_token: str


class ErrorResponse(ApiSchema):
    detail: str
