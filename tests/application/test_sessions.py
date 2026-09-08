from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from sci_search.application.sessions import (
    InMemorySessionRepository,
    InvalidSession,
    SessionService,
)

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


class MutableClock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class TokenSource:
    def __init__(self, *tokens: str) -> None:
        self._tokens = iter(tokens)

    def __call__(self, byte_count: int) -> str:
        assert byte_count == 32
        return next(self._tokens)


def _service(
    repository: InMemorySessionRepository,
    clock: MutableClock,
    *tokens: str,
) -> SessionService:
    return SessionService(
        repository,
        clock=clock,
        token_source=TokenSource(*tokens),
        absolute_lifetime=timedelta(hours=8),
        idle_lifetime=timedelta(minutes=30),
    )


def test_create_persists_only_a_sha256_token_digest() -> None:
    repository = InMemorySessionRepository()
    clock = MutableClock()

    issued = _service(repository, clock, "browser-secret").create("user")
    persisted = repository.list_sessions()[0]

    assert issued.token == "browser-secret"
    assert persisted.token_digest == sha256(b"browser-secret").hexdigest()
    assert issued.token not in repr(persisted)
    assert persisted.absolute_expires_at == NOW + timedelta(hours=8)
    assert persisted.idle_expires_at == NOW + timedelta(minutes=30)


@pytest.mark.parametrize("expiry", ["idle", "absolute"])
def test_authentication_rejects_expired_sessions(expiry: str) -> None:
    repository = InMemorySessionRepository()
    clock = MutableClock()
    service = _service(repository, clock, "browser-secret")
    service.create("user")

    clock.now += timedelta(minutes=30) if expiry == "idle" else timedelta(hours=8)

    with pytest.raises(InvalidSession, match="invalid session"):
        service.authenticate("browser-secret")


def test_rotation_invalidates_old_token_without_extending_absolute_expiry() -> None:
    repository = InMemorySessionRepository()
    clock = MutableClock()
    service = _service(repository, clock, "old-secret", "new-secret")
    original = service.create("user")
    clock.now += timedelta(minutes=10)

    rotated = service.rotate(original.token)

    with pytest.raises(InvalidSession):
        service.authenticate(original.token)
    authenticated = service.authenticate(rotated.token)
    assert authenticated.user_id == "user"
    assert rotated.absolute_expires_at == original.absolute_expires_at


def test_explicit_revoke_invalidates_token() -> None:
    repository = InMemorySessionRepository()
    clock = MutableClock()
    service = _service(repository, clock, "browser-secret")
    issued = service.create("user")

    service.revoke(issued.token)

    with pytest.raises(InvalidSession):
        service.authenticate(issued.token)


def test_revoke_user_invalidates_all_of_the_users_sessions_only() -> None:
    repository = InMemorySessionRepository()
    clock = MutableClock()
    service = _service(repository, clock, "first", "second", "other")
    first = service.create("user")
    second = service.create("user")
    other = service.create("other-user")

    assert service.revoke_user("user") == 2

    for token in (first.token, second.token):
        with pytest.raises(InvalidSession):
            service.authenticate(token)
    assert service.authenticate(other.token).user_id == "other-user"
