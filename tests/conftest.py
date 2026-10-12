"""Explicit opt-ins for retained research data and live statistical API checks."""

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
    parser.addoption(
        "--run-live-data",
        action="store_true",
        default=False,
        help="Run the live acceptance against real statistical APIs and the configured model.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    opt_ins = [
        (
            "--run-retained-corpus",
            "retained_corpus",
            "requires retained research data; enable explicitly with --run-retained-corpus",
        ),
        (
            "--run-live-data",
            "live_data",
            "queries real statistical APIs and a paid model; enable with --run-live-data",
        ),
    ]
    for option, marker, reason in opt_ins:
        if config.getoption(option):
            continue
        skip = pytest.mark.skip(reason=reason)
        for item in items:
            if item.get_closest_marker(marker) is not None:
                item.add_marker(skip)
