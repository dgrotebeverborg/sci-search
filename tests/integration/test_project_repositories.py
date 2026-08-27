from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import func, select

from sci_search.application.identity import ExternalIdentity, IdentityProfile, provision_user
from sci_search.application.projects import Membership, Project, ProjectRole
from sci_search.application.sessions import InvalidSession, SessionService
from sci_search.infrastructure.database import Database
from sci_search.infrastructure.repositories import (
    AuditEvent,
    OptimisticConflict,
    SqlAuditRepository,
    SqlIdentityRepository,
    SqlProjectRepository,
    SqlSessionRepository,
    SqlUnitOfWork,
)
from sci_search.infrastructure.tables import AuditEventRow, ProjectMembershipRow, UserRow
from tests.integration.test_migrations import DATABASE_URL, _configuration

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


@pytest.fixture
def database() -> Database:
    configuration = _configuration(DATABASE_URL)
    command.downgrade(configuration, "base")
    command.upgrade(configuration, "head")
    database = Database(DATABASE_URL)
    try:
        yield database
    finally:
        database.dispose()


def _provision(database: Database, subject: str = "stable-subject"):
    with database.transaction() as session:
        repositories = SqlUnitOfWork(session)
        return provision_user(
            ExternalIdentity("https://connect.surfconext.nl", subject),
            IdentityProfile(email=f"{subject}@example.test"),
            repositories.provisioning,
            clock=lambda: NOW,
        )


def test_sql_provisioning_is_idempotent_and_email_is_profile_only(database: Database) -> None:
    first = _provision(database)
    with database.transaction() as session:
        repositories = SqlUnitOfWork(session)
        repeated = provision_user(
            ExternalIdentity("https://connect.surfconext.nl/", "stable-subject"),
            IdentityProfile(email="changed@example.test"),
            repositories.provisioning,
            clock=lambda: NOW + timedelta(minutes=1),
        )
        counts = (
            session.scalar(select(func.count()).select_from(UserRow)),
            len(repositories.projects.list_workspaces()),
            len(repositories.projects.list_memberships()),
        )

    assert repeated.created is False
    assert repeated.user.id == first.user.id
    assert repeated.user.email == "changed@example.test"
    assert counts == (1, 1, 1)


def test_role_updates_are_optimistic_and_audited(database: Database) -> None:
    owner = _provision(database)
    project = Project(
        str(uuid4()), owner.workspace.id, "Shared evidence", owner.user.id, False, NOW
    )
    membership = Membership(
        str(uuid4()),
        owner.user.id,
        ProjectRole.EDITOR,
        True,
        NOW,
        project_id=project.id,
    )
    with database.transaction() as session:
        projects = SqlProjectRepository(session)
        projects.add_project(project)
        projects.add_membership(membership)

    with database.transaction() as session:
        projects = SqlProjectRepository(session)
        audits = SqlAuditRepository(session)
        version = projects.update_project_membership_role(
            project.id,
            owner.user.id,
            ProjectRole.REVIEWER,
            expected_version=1,
        )
        audits.add(
            AuditEvent.role_changed(
                actor_user_id=owner.user.id,
                project_id=project.id,
                subject_user_id=owner.user.id,
                role=ProjectRole.REVIEWER,
                occurred_at=NOW,
            )
        )

    assert version == 2
    with database.transaction() as session:
        with pytest.raises(OptimisticConflict):
            SqlProjectRepository(session).update_project_membership_role(
                project.id,
                owner.user.id,
                ProjectRole.VIEWER,
                expected_version=1,
            )
        assert session.scalar(select(func.count()).select_from(AuditEventRow)) == 1


def test_session_rotation_persists_digest_and_invalidates_old_token(database: Database) -> None:
    user = _provision(database).user
    tokens = iter(("old-token", "new-token"))
    with database.transaction() as session:
        service = SessionService(
            SqlSessionRepository(session),
            clock=lambda: NOW,
            token_source=lambda byte_count: next(tokens),
        )
        old = service.create(user.id)
        new = service.rotate(old.token)
        with pytest.raises(InvalidSession):
            service.authenticate(old.token)
        assert service.authenticate(new.token).user_id == user.id


def test_domain_and_audit_changes_roll_back_together(database: Database) -> None:
    owner = _provision(database)
    project = Project(str(uuid4()), owner.workspace.id, "Rollback", owner.user.id, False, NOW)
    membership = Membership(
        str(uuid4()),
        owner.user.id,
        ProjectRole.EDITOR,
        True,
        NOW,
        project_id=project.id,
    )
    with database.transaction() as session:
        projects = SqlProjectRepository(session)
        projects.add_project(project)
        projects.add_membership(membership)

    with pytest.raises(RuntimeError, match="forced failure"):
        with database.transaction() as session:
            SqlProjectRepository(session).update_project_membership_role(
                project.id,
                owner.user.id,
                ProjectRole.REVIEWER,
                expected_version=1,
            )
            SqlAuditRepository(session).add(
                AuditEvent.role_changed(
                    actor_user_id=owner.user.id,
                    project_id=project.id,
                    subject_user_id=owner.user.id,
                    role=ProjectRole.REVIEWER,
                    occurred_at=NOW,
                )
            )
            raise RuntimeError("forced failure")

    with database.transaction() as session:
        row = session.scalar(
            select(ProjectMembershipRow).where(ProjectMembershipRow.project_id == project.id)
        )
        assert row is not None
        assert row.role == ProjectRole.EDITOR
        assert session.scalar(select(func.count()).select_from(AuditEventRow)) == 0


def test_guessed_project_id_cannot_cross_repository_scope(database: Database) -> None:
    alice = _provision(database, "alice")
    bob = _provision(database, "bob")
    alice_project = Project(
        str(uuid4()), alice.workspace.id, "Alice private", alice.user.id, True, NOW
    )
    with database.transaction() as session:
        projects = SqlProjectRepository(session)
        projects.add_project(alice_project)
        projects.add_membership(
            Membership(
                str(uuid4()),
                alice.user.id,
                ProjectRole.OWNER,
                True,
                NOW,
                project_id=alice_project.id,
            )
        )

    with database.transaction() as session:
        projects = SqlProjectRepository(session)
        assert projects.membership_for_project(alice_project.id, bob.user.id) is None
        assert projects.membership_for_project(str(uuid4()), alice.user.id) is None
        assert (
            SqlIdentityRepository(session).user_for_identity(
                ExternalIdentity("https://connect.surfconext.nl", "alice")
            )
            == alice.user
        )
