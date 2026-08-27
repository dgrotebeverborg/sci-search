"""Research landscape and literature-review publication stage."""

from __future__ import annotations

from sci_search.literature_review import build_literature_review
from sci_search.research.stages.base import StageContext, StageResult, stage_result
from sci_search.research_landscape import build_research_landscape


class ReportingStage:
    name = "reporting"
    version = "reporting-v1"

    def run(self, context: StageContext) -> StageResult:
        analysis = context.inputs.get("analysis")
        if not isinstance(analysis, dict):
            raise ValueError("reporting requires a serialized analysis")
        landscape = build_research_landscape(analysis)
        review = build_literature_review(analysis)
        return stage_result(
            self.name,
            self.version,
            context,
            {
                "research_landscape": landscape,
                "literature_review_report": review,
                "literature_review": {
                    "available": True,
                    "schema_version": review["schema_version"],
                    "artifact": "literature_review.json",
                },
            },
        )
