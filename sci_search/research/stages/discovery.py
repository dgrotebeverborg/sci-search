"""Provider-injected metadata discovery stage."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sci_search.research.stages.base import StageContext, StageResult, stage_result

DiscoveryFunction = Callable[
    [list[dict[str, Any]], int],
    tuple[list[dict[str, Any]], list[dict[str, Any]]],
]


class DiscoveryStage:
    name = "discovery"
    version = "discovery-v1"

    def __init__(self, discover: DiscoveryFunction) -> None:
        self._discover = discover

    def run(self, context: StageContext) -> StageResult:
        queries = context.inputs.get("queries")
        if not isinstance(queries, list) or not all(isinstance(item, dict) for item in queries):
            raise ValueError("discovery requires serialized queries")
        per_query = int(context.inputs.get("per_query") or 100)
        candidates, search_log = self._discover(queries, per_query)
        return stage_result(
            self.name,
            self.version,
            context,
            {"candidates": candidates, "search_log": search_log},
        )
