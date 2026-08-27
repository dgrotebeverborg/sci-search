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

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
PERMISSIONS = {
    ProjectRole.OWNER: set(Action),
    ProjectRole.EDITOR: {Action.READ, Action.DOWNLOAD, Action.MANAGE_RUNS},
    ProjectRole.REVIEWER: {Action.READ, Action.DOWNLOAD, Action.REVIEW},
    ProjectRole.VIEWER: {Action.READ, Action.DOWNLOAD},
}


def _repository(role: ProjectRole, *, active: bool = True) -> InMemoryProjectRepository:
    repository = InMemoryProjectRepository()
    repository.add_workspace(Workspace("workspace", "Shared", "owner", False, NOW))
    repository.add_project(Project("project", "workspace", "Research", "owner", False, NOW))
    repository.add_membership(
        Membership(
            "membership",
            "researcher",
            role,
            active,
            NOW,
            workspace_id=None,
            project_id="project",
        )
    )
    return repository


@pytest.mark.parametrize(
    ("role", "action"),
    [(role, action) for role in ProjectRole for action in Action],
)
def test_literal_role_action_table(role: ProjectRole, action: Action) -> None:
    policy = ProjectPolicy(_repository(role))
    context = AuthorizationContext(user_id="researcher", workspace_id="workspace")

    if action in PERMISSIONS[role]:
        grant = policy.require(action, context, "project")
        assert grant.project_id == "project"
        assert grant.role is role
    else:
        with pytest.raises(ResourceNotFound, match="resource not found"):
            policy.require(action, context, "project")


@pytest.mark.parametrize("case", ["inactive", "deleted", "wrong-workspace", "guessed-id"])
def test_missing_and_inaccessible_projects_have_one_failure(case: str) -> None:
    repository = _repository(ProjectRole.OWNER, active=case != "inactive")
    project_id = "project"
    workspace_id = "workspace"
    if case == "deleted":
        repository = InMemoryProjectRepository()
        repository.add_workspace(Workspace("workspace", "Shared", "owner", False, NOW))
        repository.add_project(
            Project("project", "workspace", "Research", "owner", False, NOW, deleted_at=NOW)
        )
        repository.add_membership(
            Membership(
                "membership",
                "researcher",
                ProjectRole.OWNER,
                True,
                NOW,
                project_id="project",
            )
        )
    elif case == "wrong-workspace":
        workspace_id = "different-workspace"
    elif case == "guessed-id":
        project_id = "does-not-exist"

    with pytest.raises(ResourceNotFound) as error:
        ProjectPolicy(repository).require(
            Action.READ,
            AuthorizationContext("researcher", workspace_id),
            project_id,
        )

    assert error.value.args == ("resource not found",)
