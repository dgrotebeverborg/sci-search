"""Question interpretation and query-planning stage."""

from __future__ import annotations

from sci_search.discovery import plan_search_queries
from sci_search.models import dataclass_to_dict
from sci_search.research.stages.base import StageContext, StageResult, stage_result


class PlanningStage:
    name = "planning"
    version = "planning-v1"

    def run(self, context: StageContext) -> StageResult:
        plan, queries = plan_search_queries(context.question)
        return stage_result(
            self.name,
            self.version,
            context,
            {"plan": dataclass_to_dict(plan), "queries": dataclass_to_dict(queries)},
        )
