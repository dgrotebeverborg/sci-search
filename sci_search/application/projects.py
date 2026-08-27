"""Project and workspace tenancy contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class ProjectRole(StrEnum):
    """Roles granted at workspace or project scope."""

    OWNER = "owner"
    EDITOR = "editor"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


@dataclass(frozen=True, slots=True)
class Workspace:
    id: str
    name: str
    owner_user_id: str
    is_personal: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    workspace_id: str
    name: str
    owner_user_id: str
    is_private: bool
    created_at: datetime
    deleted_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Membership:
    id: str
    user_id: str
    role: ProjectRole
    active: bool
    created_at: datetime
    workspace_id: str | None = None
    project_id: str | None = None

    def __post_init__(self) -> None:
        if (self.workspace_id is None) == (self.project_id is None):
            raise ValueError("membership must target exactly one workspace or project")


class ProjectRepository(Protocol):
    def project_by_id(self, project_id: str) -> Project | None: ...

    def personal_workspace_for(self, user_id: str) -> Workspace | None: ...

    def membership_for_workspace(self, workspace_id: str, user_id: str) -> Membership | None: ...

    def membership_for_project(self, project_id: str, user_id: str) -> Membership | None: ...

    def add_workspace(self, workspace: Workspace) -> None: ...

    def add_project(self, project: Project) -> None: ...

    def add_membership(self, membership: Membership) -> None: ...


class InMemoryProjectRepository:
    """Small deterministic repository used until Program 3 adds persistence."""

    def __init__(self) -> None:
        self._workspaces: dict[str, Workspace] = {}
        self._projects: dict[str, Project] = {}
        self._memberships: dict[str, Membership] = {}

    def project_by_id(self, project_id: str) -> Project | None:
        return self._projects.get(project_id)

    def personal_workspace_for(self, user_id: str) -> Workspace | None:
        return next(
            (
                workspace
                for workspace in self._workspaces.values()
                if workspace.owner_user_id == user_id and workspace.is_personal
            ),
            None,
        )

    def add_workspace(self, workspace: Workspace) -> None:
        if workspace.id in self._workspaces:
            raise ValueError("workspace identifier already exists")
        if workspace.is_personal and self.personal_workspace_for(workspace.owner_user_id):
            raise ValueError("user already has a personal workspace")
        self._workspaces[workspace.id] = workspace

    def add_project(self, project: Project) -> None:
        if project.id in self._projects:
            raise ValueError("project identifier already exists")
        if project.workspace_id not in self._workspaces:
            raise ValueError("project workspace does not exist")
        self._projects[project.id] = project

    def add_membership(self, membership: Membership) -> None:
        if membership.id in self._memberships:
            raise ValueError("membership identifier already exists")
        self._memberships[membership.id] = membership

    def membership_for_workspace(self, workspace_id: str, user_id: str) -> Membership | None:
        return next(
            (
                membership
                for membership in self._memberships.values()
                if membership.workspace_id == workspace_id and membership.user_id == user_id
            ),
            None,
        )

    def membership_for_project(self, project_id: str, user_id: str) -> Membership | None:
        return next(
            (
                membership
                for membership in self._memberships.values()
                if membership.project_id == project_id and membership.user_id == user_id
            ),
            None,
        )

    def list_workspaces(self) -> list[Workspace]:
        return list(self._workspaces.values())

    def list_projects(self) -> list[Project]:
        return list(self._projects.values())

    def list_memberships(self) -> list[Membership]:
        return list(self._memberships.values())
