"""Serializable contracts shared by every research stage."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise ValueError("stage inputs and outputs must be JSON-serializable") from error


@dataclass(frozen=True, slots=True)
class StageContext:
    project_id: str
    run_id: str
    question: str
    inputs: dict[str, Any]
    prior_checkpoints: dict[str, dict[str, Any]]

    def __post_init__(self) -> None:
        _canonical_json(
            {
                "project_id": self.project_id,
                "run_id": self.run_id,
                "question": self.question,
                "inputs": self.inputs,
                "prior_checkpoints": self.prior_checkpoints,
            }
        )


@dataclass(frozen=True, slots=True)
class StageResult:
    stage_name: str
    implementation_version: str
    input_fingerprint: str
    output: dict[str, Any]


class ResearchStage(Protocol):
    name: str
    version: str

    def run(self, context: StageContext) -> StageResult: ...


def stage_result(stage_name: str, version: str, context: StageContext, output: dict[str, Any]):
    _canonical_json(output)
    fingerprint_payload = {
        "stage": stage_name,
        "version": version,
        "question": context.question,
        "inputs": context.inputs,
        "prior_checkpoints": context.prior_checkpoints,
    }
    fingerprint = hashlib.sha256(_canonical_json(fingerprint_payload).encode("utf-8")).hexdigest()
    return StageResult(stage_name, version, fingerprint, output)
