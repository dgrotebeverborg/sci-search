"""Project and workspace tenancy contracts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
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

    def list_projects(self) -> list[Project]: ...

    def list_workspaces(self) -> list[Workspace]: ...

    def list_memberships(self) -> list[Membership]: ...

    def update_project(self, project: Project) -> None: ...

    def update_membership(self, membership: Membership) -> None: ...


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

    def update_project(self, project: Project) -> None:
        if project.id not in self._projects:
            raise KeyError("unknown project")
        self._projects[project.id] = project

    def update_membership(self, membership: Membership) -> None:
        if membership.id not in self._memberships:
            raise KeyError("unknown membership")
        self._memberships[membership.id] = membership


@dataclass(frozen=True, slots=True)
class ProjectAuditRecord:
    occurred_at: datetime
    actor_user_id: str
    action: str
    entity_type: str
    entity_id: str
    project_id: str
    payload: dict[str, str]


class ProjectAuditRepository(Protocol):
    def add(self, event: ProjectAuditRecord) -> None: ...


class InMemoryProjectAuditRepository:
    def __init__(self) -> None:
        self.events: list[ProjectAuditRecord] = []

    def add(self, event: ProjectAuditRecord) -> None:
        self.events.append(event)


class ProjectService:
    """Project-scoped use cases shared by HTTP and future command adapters."""

    def __init__(
        self,
        repository: ProjectRepository,
        audits: ProjectAuditRepository,
        *,
        clock: Callable[[], datetime],
        id_source: Callable[[], str],
    ) -> None:
        self.repository = repository
        self._audits = audits
        self._clock = clock
        self._id_source = id_source

    def list_for_user(self, user_id: str) -> list[Project]:
        visible: list[Project] = []
        for project in self.repository.list_projects():
            if project.deleted_at is not None:
                continue
            direct = self.repository.membership_for_project(project.id, user_id)
            inherited = self.repository.membership_for_workspace(project.workspace_id, user_id)
            if (direct is not None and direct.active) or (inherited is not None and inherited.active):
                visible.append(project)
        return sorted(visible, key=lambda project: (project.created_at, project.id))

    def list_workspaces_for_user(self, user_id: str) -> list[Workspace]:
        workspaces = [
            workspace
            for workspace in self.repository.list_workspaces()
            if (
                (membership := self.repository.membership_for_workspace(workspace.id, user_id))
                is not None
                and membership.active
            )
        ]
        return sorted(workspaces, key=lambda workspace: (not workspace.is_personal, workspace.name))

    def get(self, user_id: str, project_id: str) -> Project:
        self._require(ProjectRole.VIEWER, user_id, project_id)
        project = self.repository.project_by_id(project_id)
        if project is None:
            raise LookupError("resource not found")
        return project

    def role_for_user(self, user_id: str, project_id: str) -> ProjectRole:
        from sci_search.application.authorization import ResourceNotFound

        project = self.repository.project_by_id(project_id)
        if project is None or project.deleted_at is not None:
            raise ResourceNotFound
        membership = self.repository.membership_for_project(project_id, user_id)
        if membership is None:
            membership = self.repository.membership_for_workspace(project.workspace_id, user_id)
        if membership is None or not membership.active:
            raise ResourceNotFound
        return membership.role

    def create(self, user_id: str, workspace_id: str, name: str, is_private: bool) -> Project:
        membership = self.repository.membership_for_workspace(workspace_id, user_id)
        if membership is None or not membership.active or membership.role is not ProjectRole.OWNER:
            from sci_search.application.authorization import ResourceNotFound

            raise ResourceNotFound
        now = self._clock()
        project = Project(self._id_source(), workspace_id, name, user_id, is_private, now)
        owner = Membership(
            self._id_source(),
            user_id,
            ProjectRole.OWNER,
            True,
            now,
            project_id=project.id,
        )
        self.repository.add_project(project)
        self.repository.add_membership(owner)
        self._record(user_id, "project.created", "project", project.id, project.id)
        return project

    def rename(self, user_id: str, project_id: str, name: str) -> Project:
        self._require(ProjectRole.OWNER, user_id, project_id)
        project = self.repository.project_by_id(project_id)
        if project is None:
            from sci_search.application.authorization import ResourceNotFound

            raise ResourceNotFound
        updated = replace(project, name=name)
        self.repository.update_project(updated)
        self._record(user_id, "project.updated", "project", project.id, project.id)
        return updated

    def delete(self, user_id: str, project_id: str) -> None:
        self._require(ProjectRole.OWNER, user_id, project_id)
        project = self.repository.project_by_id(project_id)
        if project is None:
            from sci_search.application.authorization import ResourceNotFound

            raise ResourceNotFound
        self.repository.update_project(replace(project, deleted_at=self._clock()))
        self._record(user_id, "project.deleted", "project", project.id, project.id)

    def list_members(self, user_id: str, project_id: str) -> list[Membership]:
        self._require(ProjectRole.VIEWER, user_id, project_id)
        memberships = [
            membership
            for membership in self.repository.list_memberships()
            if membership.project_id == project_id and membership.active
        ]
        return sorted(
            memberships,
            key=lambda membership: (
                membership.role is not ProjectRole.OWNER,
                membership.created_at,
                membership.id,
            ),
        )

    def add_member(
        self,
        actor_user_id: str,
        project_id: str,
        subject_user_id: str,
        role: ProjectRole,
    ) -> Membership:
        self._require(ProjectRole.OWNER, actor_user_id, project_id)
        if self.repository.membership_for_project(project_id, subject_user_id) is not None:
            raise ValueError("project membership already exists")
        membership = Membership(
            self._id_source(),
            subject_user_id,
            role,
            True,
            self._clock(),
            project_id=project_id,
        )
        self.repository.add_membership(membership)
        self._record(
            actor_user_id,
            "project_membership.added",
            "project_membership",
            f"{project_id}:{subject_user_id}",
            project_id,
            {"subject_user_id": subject_user_id, "role": role.value},
        )
        return membership

    def change_member_role(
        self,
        actor_user_id: str,
        project_id: str,
        subject_user_id: str,
        role: ProjectRole,
    ) -> Membership:
        self._require(ProjectRole.OWNER, actor_user_id, project_id)
        membership = self.repository.membership_for_project(project_id, subject_user_id)
        if membership is None or not membership.active:
            from sci_search.application.authorization import ResourceNotFound

            raise ResourceNotFound
        updated = replace(membership, role=role)
        self.repository.update_membership(updated)
        self._record(
            actor_user_id,
            "project_membership.role_changed",
            "project_membership",
            f"{project_id}:{subject_user_id}",
            project_id,
            {"subject_user_id": subject_user_id, "role": role.value},
        )
        return updated

    def remove_member(self, actor_user_id: str, project_id: str, subject_user_id: str) -> None:
        self._require(ProjectRole.OWNER, actor_user_id, project_id)
        project = self.repository.project_by_id(project_id)
        if project is not None and project.owner_user_id == subject_user_id:
            raise ValueError("project owner cannot be removed")
        membership = self.repository.membership_for_project(project_id, subject_user_id)
        if membership is None or not membership.active:
            from sci_search.application.authorization import ResourceNotFound

            raise ResourceNotFound
        self.repository.update_membership(replace(membership, active=False))
        self._record(
            actor_user_id,
            "project_membership.removed",
            "project_membership",
            f"{project_id}:{subject_user_id}",
            project_id,
            {"subject_user_id": subject_user_id},
        )

    def _require(self, minimum_role: ProjectRole, user_id: str, project_id: str) -> None:
        from sci_search.application.authorization import ResourceNotFound

        project = self.repository.project_by_id(project_id)
        if project is None or project.deleted_at is not None:
            raise ResourceNotFound
        membership = self.repository.membership_for_project(project_id, user_id)
        if membership is None:
            membership = self.repository.membership_for_workspace(project.workspace_id, user_id)
        if membership is None or not membership.active:
            raise ResourceNotFound
        allowed = {
            ProjectRole.OWNER: {ProjectRole.OWNER},
            ProjectRole.EDITOR: {ProjectRole.OWNER, ProjectRole.EDITOR},
            ProjectRole.REVIEWER: {
                ProjectRole.OWNER,
                ProjectRole.EDITOR,
                ProjectRole.REVIEWER,
            },
            ProjectRole.VIEWER: set(ProjectRole),
        }
        if membership.role not in allowed[minimum_role]:
            raise ResourceNotFound

    def _record(
        self,
        actor_user_id: str,
        action: str,
        entity_type: str,
        entity_id: str,
        project_id: str,
        payload: dict[str, str] | None = None,
    ) -> None:
        self._audits.add(
            ProjectAuditRecord(
                occurred_at=self._clock(),
                actor_user_id=actor_user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                project_id=project_id,
                payload=payload or {},
            )
        )
