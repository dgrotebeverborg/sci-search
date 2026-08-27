from __future__ import annotations

import json
from pathlib import Path

import pytest

from sci_search.corpus import load_corpus
from sci_search.generic_research import GenericResearchEngine
from sci_search.research.stages.acquisition import AcquisitionStage
from sci_search.research.stages.analysis import AnalysisStage
from sci_search.research.stages.base import StageContext
from sci_search.research.stages.discovery import DiscoveryStage
from sci_search.research.stages.planning import PlanningStage
from sci_search.research.stages.reporting import ReportingStage

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = json.loads(
    (ROOT / "tests" / "fixtures" / "staged_run_reference.json").read_text(encoding="utf-8")
)


def _context(**inputs: object) -> StageContext:
    return StageContext(
        project_id="project-test",
        run_id="run-test",
        question=REFERENCE["question"],
        inputs=dict(inputs),
        prior_checkpoints={},
    )


def test_context_rejects_non_serializable_inputs() -> None:
    with pytest.raises(ValueError, match="JSON-serializable"):
        _context(invalid=object())


def test_planning_stage_matches_hand_checked_reference_and_is_deterministic() -> None:
    stage = PlanningStage()
    first = stage.run(_context())
    second = stage.run(_context())

    assert stage.name == "planning"
    assert stage.version == "planning-v1"
    assert first.input_fingerprint == second.input_fingerprint
    assert first.output["plan"]["profile_id"] == REFERENCE["profile_id"]
    assert first.output["plan"]["intent"] == REFERENCE["intent"]
    assert first.output["queries"]


def test_discovery_and_acquisition_stages_use_injected_providers() -> None:
    observed: list[object] = []

    def discover(queries: list[dict[str, object]], per_query: int):
        observed.append((queries, per_query))
        return ([{"id": "publication-1", "title": "A paper"}], [{"status": "ok"}])

    discovery = DiscoveryStage(discover)
    found = discovery.run(
        _context(queries=[{"id": "query-1", "text": "iron air", "purpose": "test"}], per_query=20)
    )
    assert found.output["candidates"][0]["id"] == "publication-1"
    assert observed[0][1] == 20

    acquisition = AcquisitionStage(
        lambda candidate: {
            "publication_id": candidate["id"],
            "status": "acquired",
            "blob_sha256": "a" * 64,
        }
    )
    acquired = acquisition.run(_context(candidate=found.output["candidates"][0]))
    assert acquired.output["status"] == "acquired"
    assert acquired.output["blob_sha256"] == "a" * 64


def test_analysis_and_reporting_preserve_reference_evidence_and_review() -> None:
    documents = load_corpus(ROOT / "fixtures" / "iron_air_pilot")
    analysis = AnalysisStage(
        lambda context: (
            GenericResearchEngine(documents)
            .investigate(context.question, session_id=context.run_id)
            .to_dict()
        )
    ).run(_context())

    assert [item["id"] for item in analysis.output["evidence"]] == REFERENCE["evidence_ids"]
    assert analysis.output["answer_adequacy"]["status"] == REFERENCE["answer_adequacy"]
    assert (
        analysis.output["coverage"]["publications_with_relevant_evidence"]
        == REFERENCE["publications_with_relevant_evidence"]
    )

    reporting = ReportingStage().run(_context(analysis=analysis.output))
    assert reporting.output["research_landscape"]["coverage"]["publications_cited_in_review"] == 1
    assert reporting.output["literature_review_report"]["schema_version"]
    assert reporting.output["literature_review"]["available"] is True
