"""Metadata review uses the configured provider when no analyzer is injected."""

from sci_search import model_provider
from sci_search.research_runs import ResearchRunManager


def test_manager_without_injected_analyzer_uses_configured_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "test-key")
    sentinel = object()
    monkeypatch.setattr(model_provider, "configured_analyzer", lambda: sentinel)
    manager = ResearchRunManager(tmp_path)
    assert manager._metadata_reviewer() is sentinel


def test_injected_analyzer_takes_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "test-key")
    injected = object()
    monkeypatch.setattr(model_provider, "configured_analyzer", lambda: object())
    manager = ResearchRunManager(tmp_path, analyzer=injected)
    assert manager._metadata_reviewer() is injected
