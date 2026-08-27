"""SQLAlchemy repository implementations for Program 2 contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session as OrmSession

from sci_search.application.identity import (
    ExternalIdentity,
    IdentityRepository,
    ProvisioningRepositories,
    User,
)
from sci_search.application.projects import (
    Membership,
    Project,
    ProjectRepository,
    ProjectRole,
    Workspace,
)
from sci_search.application.sessions import Session, SessionRepository
from sci_search.infrastructure.tables import (
    AuditEventRow,
    ExternalIdentityRow,
    ProjectMembershipRow,
    ProjectRow,
    SessionRow,
    UserRow,
    WorkspaceMembershipRow,
    WorkspaceRow,
)


class OptimisticConflict(RuntimeError):
    def __init__(self) -> None:
        super().__init__("resource was modified by another transaction")


def _uuid(value: str) -> UUID:
    return UUID(value)


def _user(row: UserRow) -> User:
    return User(
        str(row.id),
        row.created_at,
        row.updated_at,
        row.email,
        row.display_name,
        row.affiliation,
        row.institution,
    )


def _workspace(row: WorkspaceRow) -> Workspace:
    return Workspace(
        str(row.id),
        row.name,
        str(row.owner_user_id),
        row.is_personal,
        row.created_at,
    )


def _project(row: ProjectRow) -> Project:
    return Project(
        str(row.id),
        str(row.workspace_id),
        row.name,
        str(row.owner_user_id),
        row.is_private,
        row.created_at,
        row.deleted_at,
    )


def _workspace_membership(row: WorkspaceMembershipRow) -> Membership:
    return Membership(
        str(row.id),
        str(row.user_id),
        ProjectRole(row.role),
        row.active,
        row.created_at,
        workspace_id=str(row.workspace_id),
    )


def _project_membership(row: ProjectMembershipRow) -> Membership:
    return Membership(
        str(row.id),
        str(row.user_id),
        ProjectRole(row.role),
        row.active,
        row.created_at,
        project_id=str(row.project_id),
    )


class SqlIdentityRepository(IdentityRepository):
    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def user_for_identity(self, identity: ExternalIdentity) -> User | None:
        statement = (
            select(UserRow)
            .join(ExternalIdentityRow, ExternalIdentityRow.user_id == UserRow.id)
            .where(
                ExternalIdentityRow.issuer == identity.issuer,
                ExternalIdentityRow.subject == identity.subject,
            )
        )
        row = self._session.scalar(statement)
        return _user(row) if row is not None else None

    def add_user(self, user: User, identity: ExternalIdentity) -> None:
        user_row = UserRow(
            id=_uuid(user.id),
            email=user.email,
            display_name=user.display_name,
            affiliation=user.affiliation,
            institution=user.institution,
            created_at=user.created_at,
            updated_at=user.updated_at,
            version=1,
        )
        self._session.add(user_row)
        # These mappings intentionally avoid ORM relationships; flush the FK
        # parent explicitly so ordering never depends on mapper discovery.
        self._session.flush([user_row])
        self._session.add(
            ExternalIdentityRow(
                id=uuid4(),
                user_id=_uuid(user.id),
                issuer=identity.issuer,
                subject=identity.subject,
                created_at=user.created_at,
            )
        )

    def update_user(self, user: User) -> None:
        row = self._session.get(UserRow, _uuid(user.id))
        if row is None:
            raise KeyError("unknown user")
        row.email = user.email
        row.display_name = user.display_name
        row.affiliation = user.affiliation
        row.institution = user.institution
        row.updated_at = user.updated_at
        row.version += 1

    def list_users(self) -> list[User]:
        return [_user(row) for row in self._session.scalars(select(UserRow)).all()]


class SqlProjectRepository(ProjectRepository):
    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def project_by_id(self, project_id: str) -> Project | None:
        row = self._session.get(ProjectRow, _uuid(project_id))
        return _project(row) if row is not None else None

    def personal_workspace_for(self, user_id: str) -> Workspace | None:
        row = self._session.scalar(
            select(WorkspaceRow).where(
                WorkspaceRow.owner_user_id == _uuid(user_id),
                WorkspaceRow.is_personal.is_(True),
            )
        )
        return _workspace(row) if row is not None else None

    def membership_for_workspace(self, workspace_id: str, user_id: str) -> Membership | None:
        row = self._session.scalar(
            select(WorkspaceMembershipRow).where(
                WorkspaceMembershipRow.workspace_id == _uuid(workspace_id),
                WorkspaceMembershipRow.user_id == _uuid(user_id),
            )
        )
        return _workspace_membership(row) if row is not None else None

    def membership_for_project(self, project_id: str, user_id: str) -> Membership | None:
        row = self._session.scalar(
            select(ProjectMembershipRow).where(
                ProjectMembershipRow.project_id == _uuid(project_id),
                ProjectMembershipRow.user_id == _uuid(user_id),
            )
        )
        return _project_membership(row) if row is not None else None

    def add_workspace(self, workspace: Workspace) -> None:
        row = WorkspaceRow(
            id=_uuid(workspace.id),
            name=workspace.name,
            owner_user_id=_uuid(workspace.owner_user_id),
            is_personal=workspace.is_personal,
            created_at=workspace.created_at,
            updated_at=workspace.created_at,
            version=1,
        )
        self._session.add(row)
        self._session.flush([row])

    def add_project(self, project: Project) -> None:
        row = ProjectRow(
            id=_uuid(project.id),
            workspace_id=_uuid(project.workspace_id),
            owner_user_id=_uuid(project.owner_user_id),
            name=project.name,
            is_private=project.is_private,
            created_at=project.created_at,
            updated_at=project.created_at,
            deleted_at=project.deleted_at,
            version=1,
        )
        self._session.add(row)
        self._session.flush([row])

    def add_membership(self, membership: Membership) -> None:
        values = {
            "id": _uuid(membership.id),
            "user_id": _uuid(membership.user_id),
            "role": membership.role.value,
            "active": membership.active,
            "created_at": membership.created_at,
            "updated_at": membership.created_at,
            "version": 1,
        }
        if membership.workspace_id is not None:
            self._session.add(
                WorkspaceMembershipRow(
                    workspace_id=_uuid(membership.workspace_id),
                    **values,
                )
            )
        elif membership.project_id is not None:
            self._session.add(
                ProjectMembershipRow(project_id=_uuid(membership.project_id), **values)
            )
        else:  # Membership validates this, but keep the persistence boundary defensive.
            raise ValueError("membership has no scope")

    def list_workspaces(self) -> list[Workspace]:
        self._session.flush()
        return [_workspace(row) for row in self._session.scalars(select(WorkspaceRow)).all()]

    def list_projects(self) -> list[Project]:
        self._session.flush()
        return [_project(row) for row in self._session.scalars(select(ProjectRow)).all()]

    def list_memberships(self) -> list[Membership]:
        self._session.flush()
        workspace_memberships = [
            _workspace_membership(row)
            for row in self._session.scalars(select(WorkspaceMembershipRow)).all()
        ]
        project_memberships = [
            _project_membership(row)
            for row in self._session.scalars(select(ProjectMembershipRow)).all()
        ]
        return workspace_memberships + project_memberships

    def update_project_membership_role(
        self,
        project_id: str,
        user_id: str,
        role: ProjectRole,
        *,
        expected_version: int,
    ) -> int:
        result = self._session.execute(
            update(ProjectMembershipRow)
            .where(
                ProjectMembershipRow.project_id == _uuid(project_id),
                ProjectMembershipRow.user_id == _uuid(user_id),
                ProjectMembershipRow.version == expected_version,
            )
            .values(
                role=role.value,
                version=expected_version + 1,
                updated_at=func.now(),
            )
        )
        if result.rowcount != 1:  # type: ignore[attr-defined]
            raise OptimisticConflict
        return expected_version + 1


def _session(row: SessionRow) -> Session:
    return Session(
        str(row.id),
        str(row.user_id),
        row.token_digest,
        row.created_at,
        row.last_seen_at,
        row.idle_expires_at,
        row.absolute_expires_at,
        row.revoked_at,
    )


class SqlSessionRepository(SessionRepository):
    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def session_by_digest(self, token_digest: str) -> Session | None:
        row = self._session.scalar(
            select(SessionRow).where(SessionRow.token_digest == token_digest)
        )
        return _session(row) if row is not None else None

    def save_session(self, session: Session) -> None:
        row = self._session.get(SessionRow, _uuid(session.id))
        if row is None:
            self._session.add(
                SessionRow(
                    id=_uuid(session.id),
                    user_id=_uuid(session.user_id),
                    token_digest=session.token_digest,
                    created_at=session.created_at,
                    last_seen_at=session.last_seen_at,
                    idle_expires_at=session.idle_expires_at,
                    absolute_expires_at=session.absolute_expires_at,
                    revoked_at=session.revoked_at,
                    version=1,
                )
            )
            return
        row.last_seen_at = session.last_seen_at
        row.idle_expires_at = session.idle_expires_at
        row.absolute_expires_at = session.absolute_expires_at
        row.revoked_at = session.revoked_at
        row.version += 1

    def sessions_for_user(self, user_id: str) -> list[Session]:
        rows = self._session.scalars(
            select(SessionRow).where(SessionRow.user_id == _uuid(user_id))
        ).all()
        return [_session(row) for row in rows]


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: str
    occurred_at: datetime
    action: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    actor_user_id: str | None = None
    workspace_id: str | None = None
    project_id: str | None = None

    @classmethod
    def role_changed(
        cls,
        *,
        actor_user_id: str,
        project_id: str,
        subject_user_id: str,
        role: ProjectRole,
        occurred_at: datetime,
    ) -> AuditEvent:
        return cls(
            id=str(uuid4()),
            occurred_at=occurred_at,
            actor_user_id=actor_user_id,
            project_id=project_id,
            action="project_membership.role_changed",
            entity_type="project_membership",
            entity_id=f"{project_id}:{subject_user_id}",
            payload={"subject_user_id": subject_user_id, "role": role.value},
        )


class SqlAuditRepository:
    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def add(self, event: AuditEvent) -> None:
        self._session.add(
            AuditEventRow(
                id=_uuid(event.id),
                occurred_at=event.occurred_at,
                actor_user_id=_uuid(event.actor_user_id) if event.actor_user_id else None,
                workspace_id=_uuid(event.workspace_id) if event.workspace_id else None,
                project_id=_uuid(event.project_id) if event.project_id else None,
                action=event.action,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                payload=event.payload,
            )
        )


class SqlUnitOfWork:
    """Repository bundle sharing the transaction owned by ``Database``."""

    def __init__(self, session: OrmSession) -> None:
        self.identities = SqlIdentityRepository(session)
        self.projects = SqlProjectRepository(session)
        self.sessions = SqlSessionRepository(session)
        self.audit = SqlAuditRepository(session)
        self.provisioning = ProvisioningRepositories(self.identities, self.projects)
