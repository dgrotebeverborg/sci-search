from datetime import UTC, datetime

from sci_search.application.identity import (
    ExternalIdentity,
    IdentityProfile,
    InMemoryIdentityRepository,
    ProvisioningRepositories,
    provision_user,
)
from sci_search.application.projects import InMemoryProjectRepository, ProjectRole

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def test_first_login_provisions_private_workspace() -> None:
    identities = InMemoryIdentityRepository()
    projects = InMemoryProjectRepository()

    result = provision_user(
        ExternalIdentity("https://connect.surfconext.nl/", "stable-subject"),
        IdentityProfile(email="researcher@example.test", display_name="Researcher"),
        ProvisioningRepositories(identities=identities, projects=projects),
        clock=lambda: NOW,
    )

    assert result.created is True
    assert result.identity.issuer == "https://connect.surfconext.nl"
    assert identities.list_users() == [result.user]
    assert projects.list_workspaces() == [result.workspace]
    assert projects.list_memberships() == [result.membership]
    assert result.workspace.is_personal is True
    assert result.workspace.owner_user_id == result.user.id
    assert result.membership.workspace_id == result.workspace.id
    assert result.membership.project_id is None
    assert result.membership.user_id == result.user.id
    assert result.membership.role is ProjectRole.OWNER
    assert result.membership.active is True


def test_email_is_profile_data_not_an_identity_key() -> None:
    identities = InMemoryIdentityRepository()
    projects = InMemoryProjectRepository()
    repositories = ProvisioningRepositories(identities=identities, projects=projects)

    first = provision_user(
        ExternalIdentity("https://connect.surfconext.nl", "subject-one"),
        IdentityProfile(email="shared@example.test"),
        repositories,
        clock=lambda: NOW,
    )
    second = provision_user(
        ExternalIdentity("https://connect.surfconext.nl", "subject-two"),
        IdentityProfile(email="shared@example.test"),
        repositories,
        clock=lambda: NOW,
    )

    assert first.user.id != second.user.id
    assert len(identities.list_users()) == 2
    assert len(projects.list_workspaces()) == 2


def test_changed_profile_email_reuses_the_issuer_subject_user() -> None:
    identities = InMemoryIdentityRepository()
    projects = InMemoryProjectRepository()
    repositories = ProvisioningRepositories(identities=identities, projects=projects)
    identity = ExternalIdentity("https://connect.surfconext.nl", "stable-subject")

    first = provision_user(
        identity,
        IdentityProfile(email="old@example.test"),
        repositories,
        clock=lambda: NOW,
    )
    repeated = provision_user(
        identity,
        IdentityProfile(email="new@example.test"),
        repositories,
        clock=lambda: NOW,
    )

    assert repeated.created is False
    assert repeated.user.id == first.user.id
    assert repeated.user.email == "new@example.test"
    assert repeated.workspace.id == first.workspace.id
    assert repeated.membership.id == first.membership.id
    assert len(identities.list_users()) == 1
    assert len(projects.list_workspaces()) == 1
    assert len(projects.list_memberships()) == 1
