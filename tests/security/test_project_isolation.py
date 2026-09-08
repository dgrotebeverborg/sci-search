from datetime import UTC, datetime

import pytest

from sci_search.application.authorization import (
    Action,
    AuthorizationContext,
    ProjectPolicy,
    ResourceNotFound,
)
from sci_search.application.projects import (
    InMemoryProjectRepository,
    Membership,
    Project,
    ProjectRole,
    Workspace,
)

pytestmark = pytest.mark.security
NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
ROLE_ACTIONS = {
    ProjectRole.OWNER: {action for action in Action},
    ProjectRole.EDITOR: {Action.READ, Action.DOWNLOAD, Action.MANAGE_RUNS},
    ProjectRole.REVIEWER: {Action.READ, Action.DOWNLOAD, Action.REVIEW},
    ProjectRole.VIEWER: {Action.READ, Action.DOWNLOAD},
}


@pytest.fixture
def isolation_repository() -> InMemoryProjectRepository:
    repository = InMemoryProjectRepository()
    repository.add_workspace(Workspace("alice-personal", "Alice", "alice", True, NOW))
    repository.add_workspace(Workspace("bob-personal", "Bob", "bob", True, NOW))
    repository.add_workspace(Workspace("shared", "Shared research", "alice", False, NOW))
    repository.add_project(
        Project("alice-private", "alice-personal", "Alice private", "alice", True, NOW)
    )
    repository.add_project(Project("bob-private", "bob-personal", "Bob private", "bob", True, NOW))
    repository.add_membership(
        Membership(
            "alice-private-owner",
            "alice",
            ProjectRole.OWNER,
            True,
            NOW,
            project_id="alice-private",
        )
    )
    repository.add_membership(
        Membership(
            "bob-private-owner",
            "bob",
            ProjectRole.OWNER,
            True,
            NOW,
            project_id="bob-private",
        )
    )
    for role in ProjectRole:
        project_id = f"shared-{role.value}"
        repository.add_project(Project(project_id, "shared", role.value, "alice", False, NOW))
        repository.add_membership(
            Membership(
                f"alice-{role.value}",
                "alice",
                role,
                True,
                NOW,
                project_id=project_id,
            )
        )
    return repository


@pytest.mark.parametrize(
    ("role", "action"),
    [(role, action) for role in ProjectRole for action in Action],
)
def test_every_protected_operation_obeys_role_and_project_scope(
    isolation_repository: InMemoryProjectRepository,
    role: ProjectRole,
    action: Action,
) -> None:
    policy = ProjectPolicy(isolation_repository)
    project_id = f"shared-{role.value}"

    if action in ROLE_ACTIONS[role]:
        grant = policy.require(action, AuthorizationContext("alice", "shared"), project_id)
        assert grant.user_id == "alice"
        assert grant.project_id == project_id
        assert grant.role is role
    else:
        with pytest.raises(ResourceNotFound):
            policy.require(action, AuthorizationContext("alice", "shared"), project_id)

    with pytest.raises(ResourceNotFound) as hidden:
        policy.require(action, AuthorizationContext("bob", "shared"), project_id)
    assert hidden.value.args == ("resource not found",)


@pytest.mark.parametrize(
    ("user_id", "guessed_project", "claimed_workspace"),
    [
        ("alice", "bob-private", "bob-personal"),
        ("bob", "alice-private", "alice-personal"),
        ("alice", "does-not-exist", "shared"),
        ("alice", "alice-private", "bob-personal"),
    ],
)
def test_guessed_and_cross_tenant_resources_are_indistinguishable(
    isolation_repository: InMemoryProjectRepository,
    user_id: str,
    guessed_project: str,
    claimed_workspace: str,
) -> None:
    with pytest.raises(ResourceNotFound) as hidden:
        ProjectPolicy(isolation_repository).require(
            Action.READ,
            AuthorizationContext(user_id, claimed_workspace),
            guessed_project,
        )

    assert hidden.value.args == ("resource not found",)
