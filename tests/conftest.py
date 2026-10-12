"""Explicit opt-in for scientific checks requiring untracked retained research data."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_cli_configuration(monkeypatch):
    """CLI tests must never import the developer's live provider credentials."""
    # Both contract tests and investigation tests invoke main(), even --help
    # loads .env.local before parsing. Test configuration explicitly instead.
    monkeypatch.setattr("sci_search.cli.load_env_file", lambda path: ())


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-retained-corpus",
        action="store_true",
        default=False,
        help="Run retained-corpus checks; missing local assets are failures, never skipped.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-retained-corpus"):
        return
    skip = pytest.mark.skip(
        reason="requires retained research data; enable explicitly with --run-retained-corpus"
    )
    for item in items:
        if item.get_closest_marker("retained_corpus") is not None:
            item.add_marker(skip)
