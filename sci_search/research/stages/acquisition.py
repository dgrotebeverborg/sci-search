"""Injected full-text acquisition stage."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sci_search.research.stages.base import StageContext, StageResult, stage_result

AcquisitionFunction = Callable[[dict[str, Any]], dict[str, Any]]


class AcquisitionStage:
    name = "acquisition"
    version = "acquisition-v1"

    def __init__(self, acquire: AcquisitionFunction) -> None:
        self._acquire = acquire

    def run(self, context: StageContext) -> StageResult:
        candidate = context.inputs.get("candidate")
        if not isinstance(candidate, dict):
            raise ValueError("acquisition requires one serialized candidate")
        return stage_result(self.name, self.version, context, self._acquire(candidate))
