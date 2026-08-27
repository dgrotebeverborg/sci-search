"""Shared API schemas with strict input handling."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from sci_search.application.projects import ProjectRole


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


class ProjectCreate(ApiSchema):
    workspace_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=300)
    is_private: bool = True


class ProjectUpdate(ApiSchema):
    name: str = Field(min_length=1, max_length=300)


class ProjectResponse(ApiSchema):
    id: str
    workspace_id: str
    name: str
    owner_user_id: str
    is_private: bool
    created_at: datetime


class ProjectListResponse(ApiSchema):
    items: list[ProjectResponse]


class MembershipCreate(ApiSchema):
    user_id: str = Field(min_length=1, max_length=100)
    role: ProjectRole


class MembershipUpdate(ApiSchema):
    role: ProjectRole


class MembershipResponse(ApiSchema):
    id: str
    user_id: str
    role: ProjectRole
    active: bool
    created_at: datetime


class MembershipListResponse(ApiSchema):
    items: list[MembershipResponse]
