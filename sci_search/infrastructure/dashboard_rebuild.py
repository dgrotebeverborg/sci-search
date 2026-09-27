"""Rebuild snapshots from retained immutable sources without provider discovery."""

from __future__ import annotations

import hashlib
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

from sci_search.infrastructure.dashboard_repository import DashboardRepository
from sci_search.infrastructure.feedback_repository import FeedbackRepository
from sci_search.infrastructure.research_execution import ProductionResearchStage, _manager
from sci_search.research_runs import ResearchRunManager
from sci_search.worker import StageInvocation, StageWork


def rebuild_decisions(
    manager: ResearchRunManager, run_id: str, decisions: dict[str, Any]
) -> dict[str, Any]:
    manager.get(run_id)
    manager._update(run_id, review_decisions=decisions)
    manager._rebuild_evidence(run_id)
    return manager.get(run_id)


class ProductionDashboardRebuildStage(ProductionResearchStage):
    def __call__(self, invocation: StageInvocation) -> StageWork:
        inputs = invocation.input_payload
        project_id, run_id = str(inputs["project_id"]), str(inputs["run_id"])
        sequence = int(inputs["feedback_sequence"])
        with self._database.transaction() as session:
            repo = DashboardRepository(session)
            source = repo.get(project_id, run_id, 1).snapshot_json
            current = repo.sequence(run_id)
            decisions = FeedbackRepository(session).effective(run_id, sequence)
            actor = (
                repo.require_reviewer(project_id, run_id, sequence) if current == sequence else None
            )
        if current != sequence:
            return StageWork(
                output={"superseded": True},
                next_stage="complete",
                input_fingerprint=str(sequence),
                implementation_version="dashboard-rebuild-v1",
                complete=True,
            )
        invocation.cancellation.raise_if_requested()
        with self._blobs.open(source["source_archive_key"]) as stream:
            body = stream.read()
        with tempfile.TemporaryDirectory(prefix="sci-dashboard-rebuild-") as temporary:
            root = Path(temporary)
            with zipfile.ZipFile(BytesIO(body)) as archive:
                for item in archive.infolist():
                    target = (root / item.filename).resolve()
                    if not target.is_relative_to(root.resolve()):
                        raise ValueError("invalid retained archive path")
                archive.extractall(root)
            internal = str(source["internal_run_id"])
            manager = _manager(root)
            from sci_search.infrastructure.sql_memory import memory_for_project

            memory = memory_for_project(
                root, project_id, run_id, self._database, self._blobs, user_id=actor
            )
            manager.memory = memory
            state = rebuild_decisions(manager, internal, decisions)
            invocation.cancellation.raise_if_requested()
            self._publish_corpus(project_id, run_id, root / internal / "corpus", state["result"])
            artifacts = self._publish_artifacts(
                project_id,
                run_id,
                str(state["question"]),
                state,
                manager,
                internal,
                feedback_sequence=sequence,
            )
            revision = self.publish_dashboard(
                project_id, run_id, state, root, internal, artifacts, feedback_sequence=sequence
            )
            if revision is not None:
                self.publish_memory(memory, run_id, revision)
        return StageWork(
            output={"revision": revision, "feedback_sequence": sequence},
            next_stage="complete",
            input_fingerprint=hashlib.sha256(f"{run_id}:{sequence}".encode()).hexdigest(),
            implementation_version="dashboard-rebuild-v1",
            complete=True,
        )
