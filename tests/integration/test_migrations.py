import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from sci_search.infrastructure.database import Database

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.environ.get(
    "SCI_SEARCH_TEST_DATABASE_URL",
    "postgresql+psycopg://sci_search:sci_search_test@127.0.0.1:55432/sci_search_test",
)


@pytest.fixture
def empty_database() -> str:
    if not DATABASE_URL.rsplit("/", 1)[-1].startswith("sci_search_test"):
        pytest.fail("integration migration tests require a dedicated sci_search_test database")
    engine = create_engine(DATABASE_URL)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    return DATABASE_URL


def _configuration(database_url: str) -> Config:
    configuration = Config(ROOT / "alembic.ini")
    configuration.set_main_option("sqlalchemy.url", database_url)
    return configuration


def test_empty_postgres_upgrades_downgrades_and_upgrades_again(empty_database: str) -> None:
    configuration = _configuration(empty_database)

    command.upgrade(configuration, "head")
    engine = create_engine(empty_database)
    expected_tables = {
        "alembic_version",
        "audit_events",
        "external_identities",
        "project_memberships",
        "projects",
        "sessions",
        "users",
        "workspace_memberships",
        "workspaces",
    }
    assert expected_tables <= set(inspect(engine).get_table_names())

    command.downgrade(configuration, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]

    command.upgrade(configuration, "head")
    assert expected_tables <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_application_database_startup_does_not_mutate_schema(empty_database: str) -> None:
    database = Database(empty_database)

    with database.transaction() as session:
        assert session.scalar(text("SELECT 1")) == 1

    assert inspect(database.engine).get_table_names() == []
    database.dispose()
