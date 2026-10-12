"""Analysis cache identity covers the source context and provenance it reviews."""

import hashlib
import json

import pytest

from sci_search.mistral_analysis import MistralAnalyzer
from sci_search.research_runs import ResearchRunManager


class AnalysisMemory:
    def __init__(self):
        self.results = {}

    def cached_analysis(self, key):
        return self.results.get(key)

    def cache_analysis(self, key, result):
        self.results[key] = result


def manager_with_local_analysis(tmp_path, monkeypatch):
    calls = []

    def analyze(question, evidence, analyzer, adequacy):
        calls.append(evidence)
        return {"analysis_number": len(calls)}

    monkeypatch.setattr("sci_search.research_runs.analyze_if_configured", analyze)
    memory = AnalysisMemory()
    manager = ResearchRunManager(
        tmp_path,
        openalex_api_key="test",
        memory=memory,
        analyzer=MistralAnalyzer("test", model="mistral-small-latest"),
    )
    return manager, memory, calls


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("publication_title", "A prospective cohort study of Australians"),
        ("publication_id", "p2"),
        ("locations", ["Australia"]),
        ("study_design", "observational cohort"),
        ("evidence_type", "empirical"),
        ("time_mentions", ["2010"]),
        ("section", "Results"),
        ("page", 3),
        ("direction", "negative"),
        ("trend_evidence", True),
        ("retrieval_score", 0.99),
        ("document_sha256", "changed-document"),
        ("evidence_fingerprint", "changed-evidence"),
        ("schema_version", "changed-schema"),
        ("validator_version", "changed-validator"),
        ("validation_status", "changed-status"),
        ("review_state", "changed-review"),
    ],
)
def test_changed_context_or_provenance_recomputes_analysis(tmp_path, monkeypatch, field, value):
    manager, _, calls = manager_with_local_analysis(tmp_path, monkeypatch)
    original = {"id": "e1", "passage": "Tree canopy was associated with lower incidence."}
    assert manager._analyze("Question", [original], {}) == {"analysis_number": 1}
    assert manager._analyze("Question", [dict(original)], {}) == {"analysis_number": 1}
    assert manager._analyze("Question", [{**original, field: value}], {}) == {"analysis_number": 2}
    assert len(calls) == 2


def test_v6_semantic_cache_is_invalidated_even_with_empty_evidence(tmp_path, monkeypatch):
    manager, memory, calls = manager_with_local_analysis(tmp_path, monkeypatch)
    old_key = hashlib.sha256(
        json.dumps(
            {
                "question": "Question",
                "model": "mistral-small-latest",
                "analysis_contract": "scientific_analysis_v6_semantic_support",
                "adequacy": {},
                "feedback": [],
                "evidence": [],
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    memory.results[old_key] = {"analysis_number": "stale"}
    assert manager._analyze("Question", [], {}) == {"analysis_number": 1}
    assert len(calls) == 1
