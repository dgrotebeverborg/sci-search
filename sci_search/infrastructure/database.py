"""Explicit SQLAlchemy database and transaction boundary."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker


class Database:
    """Create connections and transactions without implicitly changing schema."""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.engine: Engine = create_engine(url, echo=echo, pool_pre_ping=True)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self._sessions.begin() as session:
            yield session

    def dispose(self) -> None:
        self.engine.dispose()


def lock_blob_key(session: Any, blob_key: str) -> None:
    """Serialize a content-addressed reference change with physical deletion."""
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    lock_id = int.from_bytes(sha256(blob_key.encode()).digest()[:8], "big", signed=True)
    session.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id})
