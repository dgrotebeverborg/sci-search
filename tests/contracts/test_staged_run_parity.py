from __future__ import annotations

from pathlib import Path

from sci_search.corpus import load_corpus
from sci_search.generic_research import GenericResearchEngine
from sci_search.literature_review import build_literature_review
from sci_search.research.stages.analysis import AnalysisStage
from sci_search.research.stages.base import StageContext
from sci_search.research.stages.reporting import ReportingStage

ROOT = Path(__file__).resolve().parents[2]
QUESTION = "What measured round-trip efficiency is reported?"


def test_staged_analysis_matches_synchronous_scientific_artifacts() -> None:
    documents = load_corpus(ROOT / "fixtures" / "iron_air_pilot")
    synchronous = (
        GenericResearchEngine(documents).investigate(QUESTION, session_id="parity-run").to_dict()
    )
    context = StageContext("project", "parity-run", QUESTION, {}, {})
    staged = AnalysisStage(
        lambda stage_context: (
            GenericResearchEngine(documents)
            .investigate(stage_context.question, session_id=stage_context.run_id)
            .to_dict()
        )
    ).run(context)

    assert staged.output["question"] == synchronous["question"]
    assert [item["id"] for item in staged.output["evidence"]] == [
        item["id"] for item in synchronous["evidence"]
    ]
    assert [item["passage"] for item in staged.output["evidence"]] == [
        item["passage"] for item in synchronous["evidence"]
    ]
    assert staged.output["answer_adequacy"] == synchronous["answer_adequacy"]
    assert [item["publication_id"] for item in staged.output["evidence"]] == [
        item["publication_id"] for item in synchronous["evidence"]
    ]

    reporting = ReportingStage().run(
        StageContext("project", "parity-run", QUESTION, {"analysis": staged.output}, {})
    )
    staged_review = dict(reporting.output["literature_review_report"])
    synchronous_review = build_literature_review(synchronous)
    staged_review.pop("generated_at")
    synchronous_review.pop("generated_at")
    assert staged_review == synchronous_review
