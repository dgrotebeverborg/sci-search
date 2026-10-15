"""A research model choice is validated, isolated and retained as provenance."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from sci_search import model_provider as providers
from sci_search.dashboard import build_dashboard


def test_catalog_exposes_configured_models_without_credentials(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "private-mistral-key")
    monkeypatch.setenv("OPENAI_API_KEY", "private-openai-key")
    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_MODELS", '{"openai":["model-a","model-b"]}')
    catalog = providers.analysis_choices()
    assert {"provider": "openai", "model": "model-b", "available": True} in catalog["items"]
    assert "private-" not in str(catalog)
    assert providers.resolve_selection({"provider": "openai", "model": "model-b"}) == {
        "provider": "openai",
        "model": "model-b",
    }
    with pytest.raises(providers.InvalidAnalysisSelection):
        providers.resolve_selection({"provider": "openai", "model": "not-allowed"})
    monkeypatch.delenv("OPENAI_API_KEY")
    with pytest.raises(providers.InvalidAnalysisSelection):
        providers.resolve_selection({"provider": "openai", "model": "model-b"})


def test_parallel_selections_do_not_change_defaults_or_cross_requests(monkeypatch):
    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_PROVIDER", "mistral")
    monkeypatch.setenv("MISTRAL_API_KEY", "m-key")
    monkeypatch.setenv("OPENAI_API_KEY", "o-key")
    monkeypatch.setenv("MISTRAL_MODEL", "default-model")
    barrier = Barrier(2)

    def select(provider, model):
        with providers.analysis_scope({"provider": provider, "model": model}):
            barrier.wait(timeout=5)
            analyzer = providers.configured_analyzer()
            return analyzer.provider.name, analyzer.model

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(select, "openai", "model-a")
        b = pool.submit(select, "mistral", "model-b")
        assert a.result() == ("openai", "model-a")
        assert b.result() == ("mistral", "model-b")
    assert providers.configured_analyzer().model == "default-model"
    monkeypatch.delenv("OPENAI_API_KEY")
    with providers.analysis_scope({"provider": "openai", "model": "model-a"}):
        assert providers.configured_analyzer() is None
        assert providers.selected_profile().name == "openai"


def test_dashboard_distinguishes_requested_model_from_fallback():
    selection = {"provider": "openai", "model": "model-a"}
    result = {
        "question": "Question",
        "analysis_selection": selection,
        "ai_analysis": {
            "status": "unavailable",
            "provider": None,
            "model": None,
            "fallback_reason": "Model unavailable",
        },
    }
    dashboard = build_dashboard(result, run_id="run", revision=1)
    assert dashboard["analysis"]["selection"] == selection
    assert dashboard["analysis"]["status"] == "unavailable"
    assert dashboard["analysis"]["model"] is None
    assert dashboard["analysis"]["fallback_reason"] == "Model unavailable"


def test_secret_file_provider_is_available_without_exposing_key(monkeypatch, tmp_path):
    secret = tmp_path / "openai-key"
    secret.write_text("file-only-secret\n")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY_FILE", str(secret))
    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_PROVIDER", "openai")
    catalog = providers.analysis_choices()
    assert any(item["provider"] == "openai" and item["available"] for item in catalog["items"])
    assert "file-only-secret" not in str(catalog)
    assert providers.configured_analyzer() is not None


def test_production_stage_uses_persisted_choice_for_factory_and_execution(monkeypatch):
    from sci_search.infrastructure.research_execution import ProductionResearchStage
    from sci_search.worker import CancellationToken, StageInvocation

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_PROVIDER", "mistral")
    choice = {"provider": "openai", "model": "saved-model"}
    seen = []

    def record_choice():
        analyzer = providers.configured_analyzer()
        seen.append((analyzer.provider.name, analyzer.model))

    class Manager:
        def run_sync(self, question, *, limits):
            record_choice()
            return {"status": "complete", "run_id": "internal", "result": {}}

    def factory(root):
        record_choice()
        return Manager()

    class Stage(ProductionResearchStage):
        def _publish_corpus(self, *args):
            return {}

        def _publish_artifacts(self, project, run_id, question, state, *args):
            assert state["result"]["analysis_selection"] == choice
            return []

        def publish_dashboard(self, *args, **kwargs):
            return None

    stage = Stage(None, None, manager_factory=factory)
    result = stage(
        StageInvocation(
            {
                "question": "Question",
                "run_id": "run",
                "project_id": "project",
                "analysis_selection": choice,
            },
            CancellationToken(lambda: False),
        )
    )
    assert result.complete
    assert seen == [("openai", "saved-model")] * 2
    assert providers.selected_profile().name == "mistral"
