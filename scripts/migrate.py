#!/usr/bin/env python3
"""Run Alembic migrations while holding Sci-Search's PostgreSQL advisory lock."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from scripts.backup import _secret_env

_LOCK = "sci-search-schema-migration-v1"


def migrate_with_lock(
    database_url: str,
    configuration_path: Path,
    *,
    revision: str = "head",
    engine_factory: Callable[[str], Any] = create_engine,
    upgrade: Callable[[Config, str], None] = command.upgrade,
) -> None:
    engine = engine_factory(database_url)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT pg_advisory_lock(hashtext(:name))"), {"name": _LOCK})
            try:
                configuration = Config(configuration_path)
                configuration.set_main_option("sqlalchemy.url", database_url)
                upgrade(configuration, revision)
            finally:
                connection.execute(
                    text("SELECT pg_advisory_unlock(hashtext(:name))"), {"name": _LOCK}
                )
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=_secret_env("SCI_SEARCH_DATABASE_URL"))
    parser.add_argument("--configuration", type=Path, default=Path("/app/alembic.ini"))
    parser.add_argument("--revision", default="head")
    arguments = parser.parse_args()
    if not arguments.database_url:
        parser.error("missing database URL")
    migrate_with_lock(arguments.database_url, arguments.configuration, revision=arguments.revision)


if __name__ == "__main__":
    main()
