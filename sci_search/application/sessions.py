"""Opaque, revocable server-side session management."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Protocol
from uuid import uuid4


class InvalidSession(PermissionError):
    def __init__(self) -> None:
        super().__init__("invalid session")


@dataclass(frozen=True, slots=True)
class Session:
    id: str
    user_id: str
    token_digest: str
    created_at: datetime
    last_seen_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class IssuedSession:
    token: str
    absolute_expires_at: datetime


class SessionRepository(Protocol):
    def session_by_digest(self, token_digest: str) -> Session | None: ...

    def save_session(self, session: Session) -> None: ...

    def sessions_for_user(self, user_id: str) -> list[Session]: ...


class InMemorySessionRepository:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def session_by_digest(self, token_digest: str) -> Session | None:
        return self._sessions.get(token_digest)

    def save_session(self, session: Session) -> None:
        existing = self._sessions.get(session.token_digest)
        if existing is not None and existing.id != session.id:
            raise ValueError("session token digest already exists")
        self._sessions[session.token_digest] = session

    def sessions_for_user(self, user_id: str) -> list[Session]:
        return [session for session in self._sessions.values() if session.user_id == user_id]

    def list_sessions(self) -> list[Session]:
        return list(self._sessions.values())


def _digest(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


class SessionService:
    def __init__(
        self,
        repository: SessionRepository,
        *,
        clock: Callable[[], datetime],
        token_source: Callable[[int], str] = secrets.token_urlsafe,
        absolute_lifetime: timedelta = timedelta(hours=8),
        idle_lifetime: timedelta = timedelta(minutes=30),
    ) -> None:
        if absolute_lifetime <= timedelta(0) or idle_lifetime <= timedelta(0):
            raise ValueError("session lifetimes must be positive")
        self._repository = repository
        self._clock = clock
        self._token_source = token_source
        self._absolute_lifetime = absolute_lifetime
        self._idle_lifetime = idle_lifetime

    def create(self, user_id: str) -> IssuedSession:
        now = self._clock()
        return self._issue(user_id, now, now + self._absolute_lifetime)

    def authenticate(self, token: str) -> Session:
        session = self._active_session(token)
        now = self._clock()
        refreshed = replace(
            session,
            last_seen_at=now,
            idle_expires_at=min(now + self._idle_lifetime, session.absolute_expires_at),
        )
        self._repository.save_session(refreshed)
        return refreshed

    def rotate(self, token: str) -> IssuedSession:
        session = self._active_session(token)
        now = self._clock()
        self._repository.save_session(replace(session, revoked_at=now))
        return self._issue(session.user_id, now, session.absolute_expires_at)

    def revoke(self, token: str) -> None:
        session = self._repository.session_by_digest(_digest(token))
        if session is None or session.revoked_at is not None:
            raise InvalidSession
        self._repository.save_session(replace(session, revoked_at=self._clock()))

    def revoke_user(self, user_id: str) -> int:
        now = self._clock()
        revoked = 0
        for session in self._repository.sessions_for_user(user_id):
            if session.revoked_at is None:
                self._repository.save_session(replace(session, revoked_at=now))
                revoked += 1
        return revoked

    def _active_session(self, token: str) -> Session:
        session = self._repository.session_by_digest(_digest(token))
        now = self._clock()
        if (
            session is None
            or session.revoked_at is not None
            or now >= session.idle_expires_at
            or now >= session.absolute_expires_at
        ):
            raise InvalidSession
        return session

    def _issue(
        self,
        user_id: str,
        now: datetime,
        absolute_expires_at: datetime,
    ) -> IssuedSession:
        if now >= absolute_expires_at:
            raise InvalidSession
        for _ in range(5):
            token = self._token_source(32)
            token_digest = _digest(token)
            if self._repository.session_by_digest(token_digest) is None:
                break
        else:
            raise RuntimeError("could not allocate a unique session token")
        session = Session(
            id=str(uuid4()),
            user_id=user_id,
            token_digest=token_digest,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=min(now + self._idle_lifetime, absolute_expires_at),
            absolute_expires_at=absolute_expires_at,
        )
        self._repository.save_session(session)
        return IssuedSession(token, absolute_expires_at)
