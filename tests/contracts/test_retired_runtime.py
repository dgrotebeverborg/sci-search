from __future__ import annotations

import importlib.util
import inspect

from sci_search.api import bootstrap
from sci_search.research_runs import ResearchRunManager


def test_legacy_http_runtime_and_embedded_ui_are_not_importable() -> None:
    assert importlib.util.find_spec("sci_search.web") is None
    assert importlib.util.find_spec("sci_search.ui") is None
    assert importlib.util.find_spec("sci_search.compatibility.local_web") is None


def test_production_composition_has_no_sqlite_or_legacy_runtime_dependency() -> None:
    source = inspect.getsource(bootstrap._build_production_application)
    assert "ScientificMemory" not in source
    assert "ResearchRunManager" not in source
    assert "sqlite" not in source.lower()
    assert "Thread" not in source


def test_legacy_manager_has_no_daemon_thread_start_method() -> None:
    assert not hasattr(ResearchRunManager, "start")
