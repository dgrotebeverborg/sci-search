"""Federated identity contracts and first-login provisioning."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from sci_search.application.projects import (
    Membership,
    ProjectRepository,
    ProjectRole,
    Workspace,
)


def _normalize_issuer(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("issuer must be an absolute HTTP(S) URL")
    if parsed.query or parsed.fragment:
        raise ValueError("issuer must not contain a query or fragment")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))


@dataclass(frozen=True, slots=True)
class ExternalIdentity:
    issuer: str
    subject: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "issuer", _normalize_issuer(self.issuer))
        subject = self.subject.strip()
        if not subject:
            raise ValueError("subject must not be empty")
        object.__setattr__(self, "subject", subject)


@dataclass(frozen=True, slots=True)
class IdentityProfile:
    email: str | None = None
    display_name: str | None = None
    affiliation: str | None = None
    institution: str | None = None


@dataclass(frozen=True, slots=True)
class User:
    id: str
    created_at: datetime
    updated_at: datetime
    email: str | None = None
    display_name: str | None = None
    affiliation: str | None = None
    institution: str | None = None


class IdentityRepository(Protocol):
    def user_for_identity(self, identity: ExternalIdentity) -> User | None: ...

    def add_user(self, user: User, identity: ExternalIdentity) -> None: ...

    def update_user(self, user: User) -> None: ...


class InMemoryIdentityRepository:
    """In-memory identity repository keyed exclusively by issuer and subject."""

    def __init__(self) -> None:
        self._users: dict[str, User] = {}
        self._identity_users: dict[tuple[str, str], str] = {}

    def user_for_identity(self, identity: ExternalIdentity) -> User | None:
        user_id = self._identity_users.get((identity.issuer, identity.subject))
        return self._users.get(user_id) if user_id is not None else None

    def add_user(self, user: User, identity: ExternalIdentity) -> None:
        key = (identity.issuer, identity.subject)
        if key in self._identity_users:
            raise ValueError("external identity already exists")
        if user.id in self._users:
            raise ValueError("user identifier already exists")
        self._users[user.id] = user
        self._identity_users[key] = user.id

    def update_user(self, user: User) -> None:
        if user.id not in self._users:
            raise KeyError("unknown user")
        self._users[user.id] = user

    def list_users(self) -> list[User]:
        return list(self._users.values())


@dataclass(frozen=True, slots=True)
class ProvisioningRepositories:
    identities: IdentityRepository
    projects: ProjectRepository


@dataclass(frozen=True, slots=True)
class ProvisioningResult:
    identity: ExternalIdentity
    user: User
    workspace: Workspace
    membership: Membership
    created: bool


def _profile_values(profile: IdentityProfile) -> dict[str, str | None]:
    return {
        "email": profile.email,
        "display_name": profile.display_name,
        "affiliation": profile.affiliation,
        "institution": profile.institution,
    }


def provision_user(
    identity: ExternalIdentity,
    profile: IdentityProfile,
    repositories: ProvisioningRepositories,
    clock: Callable[[], datetime],
) -> ProvisioningResult:
    """Resolve an OIDC identity and ensure it owns one personal workspace."""

    now = clock()
    user = repositories.identities.user_for_identity(identity)
    created = user is None
    if user is None:
        user = User(
            id=str(uuid4()),
            created_at=now,
            updated_at=now,
            **_profile_values(profile),
        )
        repositories.identities.add_user(user, identity)
    else:
        user = replace(user, updated_at=now, **_profile_values(profile))
        repositories.identities.update_user(user)

    workspace = repositories.projects.personal_workspace_for(user.id)
    if workspace is None:
        workspace = Workspace(
            id=str(uuid4()),
            name="Personal workspace",
            owner_user_id=user.id,
            is_personal=True,
            created_at=now,
        )
        membership = Membership(
            id=str(uuid4()),
            workspace_id=workspace.id,
            project_id=None,
            user_id=user.id,
            role=ProjectRole.OWNER,
            active=True,
            created_at=now,
        )
        repositories.projects.add_workspace(workspace)
        repositories.projects.add_membership(membership)
    else:
        membership = repositories.projects.membership_for_workspace(workspace.id, user.id)
        if membership is None:
            raise RuntimeError("personal workspace has no owner membership")

    return ProvisioningResult(identity, user, workspace, membership, created)
