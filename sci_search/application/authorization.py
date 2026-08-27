"""Centralized, default-deny project authorization."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sci_search.application.projects import ProjectRepository, ProjectRole


class Action(StrEnum):
    READ = "read"
    DOWNLOAD = "download"
    MANAGE_RUNS = "manage_runs"
    REVIEW = "review"
    MANAGE_MEMBERSHIP = "manage_membership"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class AuthorizationContext:
    user_id: str
    workspace_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectGrant:
    project_id: str
    workspace_id: str
    user_id: str
    role: ProjectRole


class ResourceNotFound(LookupError):
    """Uniform response for resources that are missing or inaccessible."""

    def __init__(self) -> None:
        super().__init__("resource not found")


_ROLE_ACTIONS: dict[ProjectRole, frozenset[Action]] = {
    ProjectRole.OWNER: frozenset(Action),
    ProjectRole.EDITOR: frozenset({Action.READ, Action.DOWNLOAD, Action.MANAGE_RUNS}),
    ProjectRole.REVIEWER: frozenset({Action.READ, Action.DOWNLOAD, Action.REVIEW}),
    ProjectRole.VIEWER: frozenset({Action.READ, Action.DOWNLOAD}),
}


class ProjectPolicy:
    def __init__(self, repository: ProjectRepository) -> None:
        self._repository = repository

    def require(
        self,
        action: Action,
        context: AuthorizationContext,
        project_id: str,
    ) -> ProjectGrant:
        project = self._repository.project_by_id(project_id)
        if project is None or project.deleted_at is not None:
            raise ResourceNotFound
        if context.workspace_id is not None and context.workspace_id != project.workspace_id:
            raise ResourceNotFound

        membership = self._repository.membership_for_project(project.id, context.user_id)
        if membership is None:
            membership = self._repository.membership_for_workspace(
                project.workspace_id, context.user_id
            )
        if membership is None or not membership.active:
            raise ResourceNotFound
        if action not in _ROLE_ACTIONS[membership.role]:
            raise ResourceNotFound

        return ProjectGrant(project.id, project.workspace_id, context.user_id, membership.role)
