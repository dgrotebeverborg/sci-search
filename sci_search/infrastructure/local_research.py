"""Durable loopback research workspace with saved scientific dashboards."""

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import RLock

from sci_search.application.authorization import Action, ResourceNotFound
from sci_search.application.research_api import InMemoryResearchApiService, ResourceVersionConflict
from sci_search.infrastructure.local_dashboards import LocalDashboardOperations
from sci_search.infrastructure.research_execution import _limits, _manager

logger = logging.getLogger(__name__)


class LocalResearchService(LocalDashboardOperations, InMemoryResearchApiService):
    """One worker with transactional run history, immutable revisions and feedback."""

    def __init__(self, projects, *, root, clock, id_source):
        super().__init__(projects, clock=clock, id_source=id_source)
        self.root = Path(root).resolve()
        self._lock = RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-research")
        self._scheduled = set()
        self._latest_runs = {}
        self._evidence_runs = {}
        self._export_runs = {}
        self._restore_catalog()

    def close(self):
        self._executor.shutdown(wait=True, cancel_futures=True)

    def start_run(self, user_id, project_id, **kwargs):
        with self._lock:
            run = super().start_run(user_id, project_id, **kwargs)
            if run.id not in self._scheduled:
                key = (project_id, run.id)
                self._metadata[key] = {
                    "user_id": user_id,
                    "idempotency_key": kwargs["idempotency_key"],
                    "question_brief": kwargs.get("question_brief"),
                    "current_revision": 0,
                    "feedback_sequence": 0,
                    "rebuild_status": "idle",
                }
                self._persist_run(key)
                self._latest_runs[project_id] = run.id
                self._scheduled.add(run.id)
                self._executor.submit(self._execute, project_id, run.id)
            return run

    def retry_run(self, user_id, project_id, run_id):
        with self._lock:
            run = super().retry_run(user_id, project_id, run_id)
            self._persist_run((project_id, run_id))
            self._executor.submit(self._execute, project_id, run_id)
            return run

    def cancel_run(self, user_id, project_id, run_id):
        with self._lock:
            run = super().cancel_run(user_id, project_id, run_id)
            self._persist_run((project_id, run_id))
            return run

    def list_evidence(self, user_id, project_id, **kwargs):
        with self._lock:
            self._require(Action.READ, user_id, project_id)
            run_id = self._latest_runs.get(project_id)
            revision = self._metadata.get((project_id, run_id), {}).get("current_revision", 0)
            with self.catalog.connect() as db:
                ids = {
                    row[0]
                    for row in db.execute(
                        "SELECT id FROM saved_evidence WHERE project_id=? AND run_id=? AND revision=?",
                        (project_id, run_id, revision),
                    )
                }
            records = [
                r
                for (p, identifier), r in self._evidence.items()
                if p == project_id and identifier in ids
            ]
            offset, limit = kwargs["offset"], kwargs["limit"]
            return records[offset : offset + limit], len(records)

    def list_exports(self, user_id, project_id):
        with self._lock:
            records = super().list_exports(user_id, project_id)
            run_id = self._latest_runs.get(project_id)
            revision = self._metadata.get((project_id, run_id), {}).get("current_revision", 0)
            with self.catalog.connect() as db:
                ids = {
                    row[0]
                    for row in db.execute(
                        "SELECT id FROM saved_downloads WHERE project_id=? AND run_id=? AND revision=? AND kind='export'",
                        (project_id, run_id, revision),
                    )
                }
            return [item for item in records if item.id in ids]

    def open_document(self, user_id, project_id, document_id):
        try:
            return self._open_saved_download(user_id, project_id, document_id, "document")
        except ResourceNotFound:
            return super().open_document(user_id, project_id, document_id)

    def open_export(self, user_id, project_id, export_id):
        try:
            return self._open_saved_download(user_id, project_id, export_id, "export")
        except ResourceNotFound:
            return super().open_export(user_id, project_id, export_id)

    def review_evidence(self, user_id, project_id, evidence_id, **kwargs):
        from dataclasses import asdict

        from sci_search.infrastructure.local_workspace import encode

        with self._lock:
            self._require(Action.REVIEW, user_id, project_id)
            with self.catalog.connect() as db:
                row = db.execute(
                    "SELECT run_id,revision FROM saved_evidence WHERE project_id=? AND id=?",
                    (project_id, evidence_id),
                ).fetchone()
            if (
                row
                and row["revision"]
                != self._metadata[(project_id, row["run_id"])]["current_revision"]
            ):
                raise ResourceVersionConflict
            record = super().review_evidence(user_id, project_id, evidence_id, **kwargs)
            with self.catalog.connect() as db:
                db.execute(
                    "UPDATE saved_evidence SET payload=? WHERE project_id=? AND id=?",
                    (encode(asdict(record)), project_id, evidence_id),
                )
            return record

    def _status(self, key, status):
        run = self._runs[key]
        self._runs[key] = replace(
            run, status=status, updated_at=self._clock(), version=run.version + 1
        )
        self._persist_run(key)

    def _attach_memory(self, manager, project_id, user_id):
        from sci_search.application.memory import MemoryContext
        from sci_search.infrastructure.local_memory import LocalScientificMemory

        memory = LocalScientificMemory(
            self.root,
            MemoryContext(user_id, project_id),
            authorize=lambda context: self._require(
                Action.READ, context.user_id, context.project_id
            ),
            feedback_reader=lambda: self._feedback_events(project_id),
            feedback_ranking_enabled=os.environ.get(
                "SCI_SEARCH_FEEDBACK_RANKING_ENABLED", ""
            ).lower()
            == "true",
            defer_ingestion=True,
        )
        manager.memory = memory
        return memory

    def _publish_memory(self, memory, revision, key):
        try:
            for event in self._feedback_events(key[0]):
                memory.record_feedback(event)
            memory.publish_pending(revision=revision, published_run_id=key[1])
            with self._lock:
                previous = self._metadata[key].get("memory_revision", 0)
                if revision == previous + 1:
                    self._metadata[key]["memory_revision"] = revision
                self._metadata[key]["memory_status"] = (
                    "complete"
                    if self._metadata[key].get("memory_revision", 0)
                    >= self._metadata[key].get("current_revision", revision)
                    else "pending"
                )
                self._persist_run(key)
            return True
        except Exception:
            logger.exception("Scientific memory publication will retry from retained revision")
            with self._lock:
                self._metadata[key]["memory_status"] = "pending"
                self._persist_run(key)
            return False

    def _recover_memory(self, project_id, run_id):
        import json

        key = (project_id, run_id)
        with self._lock:
            metadata = self._metadata[key]
            user_id = metadata.get("rebuild_actor", metadata["user_id"])
            with self.catalog.connect() as db:
                revisions = db.execute(
                    "SELECT * FROM dashboard_revisions WHERE project_id=? AND run_id=? AND revision>? ORDER BY revision",
                    (*key, metadata.get("memory_revision", 0)),
                ).fetchall()
        for row in revisions:
            try:
                state = json.loads(row["state"])
                corpus = self._object_path(str(Path(row["work_root"]) / state["run_id"] / "corpus"))
                manager = type("MemoryTarget", (), {})()
                memory = self._attach_memory(manager, project_id, user_id)
                if (corpus / "manifest.json").is_file():
                    memory.ingest_run(run_id, state["question"], corpus, state["result"])
                if not self._publish_memory(memory, row["revision"], key):
                    return
            except Exception:
                logger.exception("Pending scientific memory remains recoverable: %s", run_id)
                return

    def _execute(self, project_id, run_id):
        from uuid import uuid4

        key = (project_id, run_id)
        try:
            with self._lock:
                run = self._runs[key]
                if run.status == "cancel_requested":
                    self._status(key, "cancelled")
                    return
                user_id = self._metadata[key]["user_id"]
                self._require(Action.MANAGE_RUNS, user_id, project_id)
                self._status(key, "running")
            work_root = self.root / project_id / run_id / "attempts" / uuid4().hex
            for pending_key, pending in list(self._metadata.items()):
                if pending_key[0] == project_id and pending.get("memory_status") == "pending":
                    self._recover_memory(*pending_key)
            manager = _manager(work_root)
            memory = self._attach_memory(manager, project_id, user_id)
            brief = self._metadata[key].get("question_brief")
            state = manager.run_sync(
                run.question,
                limits=_limits(run.review_depth),
                **({"question_brief": brief} if brief else {}),
            )
            if state.get("status") != "complete" or not isinstance(state.get("result"), dict):
                raise RuntimeError("Research pipeline did not complete")
            with self._lock:
                if self._runs[key].status == "cancel_requested":
                    self._status(key, "cancelled")
                    return
            snapshot, downloads = self._prepare_revision(run, state, manager, work_root, 1, 0)
            with self._lock:
                self._require(Action.MANAGE_RUNS, user_id, project_id)
                if self._runs[key].status == "cancel_requested":
                    self._status(key, "cancelled")
                    return
                self._publish_revision(run, state, work_root, snapshot, downloads)
            self._publish_memory(memory, 1, key)
        except Exception:
            logger.exception("Local research run failed: %s", run_id)
            with self._lock:
                self._status(
                    key, "cancelled" if self._runs[key].status == "cancel_requested" else "failed"
                )
