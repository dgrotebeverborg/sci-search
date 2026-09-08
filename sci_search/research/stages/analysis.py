"""Evidence extraction and synthesis-input stage."""

from __future__ import annotations

from collections.abc import Callable

from sci_search.research.stages.base import StageContext, StageResult, stage_result

AnalysisFunction = Callable[[StageContext], dict[str, object]]


class AnalysisStage:
    name = "analysis"
    version = "analysis-v1"

    def __init__(self, analyze: AnalysisFunction) -> None:
        self._analyze = analyze

    def run(self, context: StageContext) -> StageResult:
        return stage_result(self.name, self.version, context, self._analyze(context))
