"""PostgreSQL-scoped scientific graph with content-addressed source/engine state.

The established extraction engine uses an ephemeral local SQLite working copy;
its durable checkpoint and every source are stored in BlobStore, while graph
nodes, edges and projection checkpoints live in the production database. A
project row lock serializes publication and prevents concurrent lost updates.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sci_search.application.blobs import BlobHashMismatch, BlobStore, content_addressed_key
from sci_search.application.memory import MemoryContext
from sci_search.discovery import PublicationCandidate
from sci_search.infrastructure.database import Database, lock_blob_key
from sci_search.infrastructure.local_memory import LocalScientificMemory
from sci_search.infrastructure.memory_tables import (
    MemoryCheckpointRow,
    MemoryEdgeRow,
    MemoryNodeRow,
    MemoryStateRow,
)
from sci_search.infrastructure.tables import ProjectRow
from sci_search.scientific_memory import _canonical_key


class SqlScientificMemory(LocalScientificMemory):
    def __init__(
        self,
        root: Path,
        context: MemoryContext,
        database: Database,
        blobs: BlobStore,
        *,
        authorize: Callable[[MemoryContext], None],
        feedback_reader: Callable[[], list[dict[str, Any]]] | None = None,
        feedback_ranking_enabled: bool = False,
    ) -> None:
        self._sql = database
        self._blobs = blobs
        self._manifest: dict[str, Any] = {}
        self._pending_analyses: dict[str, dict[str, Any]] = {}
        self._pending_feedback: list[dict[str, Any]] = []
        super().__init__(
            root,
            context,
            authorize=authorize,
            feedback_reader=feedback_reader,
            feedback_ranking_enabled=feedback_ranking_enabled,
            defer_ingestion=True,
        )
        with self._sql.transaction() as session:
            self._refresh(session)

    def _fetch(self, entry: dict[str, Any], target: Path) -> None:
        self._authorize(self.context)
        with self._blobs.open(str(entry["key"])) as stream:
            data = stream.read()
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise BlobHashMismatch("scientific memory object failed integrity validation")
        target.resolve().relative_to(self.root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def _refresh(self, session: Session) -> None:
        self._authorize(self.context)
        state = session.get(MemoryStateRow, UUID(self.context.project_id))
        if state is None:
            return
        manifest = state.manifest_json
        if manifest.get("schema_version") != self.schema_version:
            raise ValueError("unsupported scientific memory checkpoint schema")
        self._manifest = dict(manifest)
        # No connection may be open while replacing the scratch database.
        for suffix in ("-wal", "-shm"):
            Path(str(self.database) + suffix).unlink(missing_ok=True)
        self._fetch(manifest["database"], self.database)
        with self._connect() as connection:
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("scientific memory database failed integrity validation")

    def reuse_document(
        self, candidate: PublicationCandidate, corpus_directory: Path
    ) -> tuple[str, int, str] | None:
        self._authorize(self.context)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT cache_path,download_cache_path FROM publications WHERE publication_id=? OR canonical_key=? OR publication_id=(SELECT publication_id FROM publication_aliases WHERE alias_id=?)",
                (candidate.id, _canonical_key(candidate.doi, candidate.title), candidate.id),
            ).fetchall()
        for row in rows:
            for relative in row:
                if not relative:
                    continue
                path = (self.root / relative).resolve()
                path.relative_to(self.root)
                entry = self._manifest.get("documents", {}).get(relative)
                if not path.is_file() and entry:
                    self._fetch(entry, path)
        return super().reuse_document(candidate, corpus_directory)

    def cache_analysis(self, cache_key: str, payload: dict[str, Any]) -> None:
        super().cache_analysis(cache_key, payload)
        if payload.get("status") == "complete":
            self._pending_analyses[cache_key] = payload

    def record_feedback(self, event: dict[str, Any]) -> None:
        super().record_feedback(event)
        self._pending_feedback.append(event)

    def publish_pending(
        self, *, revision: int = 1, published_run_id: str | None = None
    ) -> dict[str, int]:
        self._authorize(self.context)
        if not self._pending:
            return {}
        if published_run_id is not None:
            self._pending = [
                (published_run_id, question, corpus, payload)
                for _, question, corpus, payload in self._pending
            ]
        pending = list(self._pending)
        try:
            with self._sql.transaction() as session:
                project = session.scalar(
                    select(ProjectRow)
                    .where(
                        ProjectRow.id == UUID(self.context.project_id),
                        ProjectRow.deleted_at.is_(None),
                    )
                    .with_for_update()
                )
                if project is None:
                    raise PermissionError("memory project unavailable")
                self._refresh(session)
                for cache_key, payload in self._pending_analyses.items():
                    super().cache_analysis(cache_key, payload)
                events = self.feedback_events() if self._feedback_reader else self._pending_feedback
                for event in events:
                    super().record_feedback(event)
                counts = super().publish_pending(revision=revision)
                counts.update(self._project_graph(session))
                self._persist(session)
                for run_id, _, _, _ in pending:
                    session.merge(
                        MemoryCheckpointRow(
                            project_id=UUID(self.context.project_id),
                            run_id=run_id,
                            revision=revision,
                            projection_version=self.schema_version,
                            status="complete",
                            error=None,
                        )
                    )
            self._pending_analyses.clear()
            self._pending_feedback.clear()
            return counts
        except Exception:
            # Dashboard publication is independent; caller records retryable work.
            self._pending = pending
            raise

    def _persist(self, session: Session) -> None:
        self._authorize(self.context)
        documents = dict(self._manifest.get("documents") or {})
        for path in self.documents.iterdir():
            if not path.is_file():
                continue
            relative = path.relative_to(self.root).as_posix()
            if relative in documents:
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != path.stem:
                raise BlobHashMismatch("cached source does not match its content address")
            lock_blob_key(session, content_addressed_key(digest))
            with path.open("rb") as stream:
                blob = self._blobs.put(
                    stream, maximum_bytes=path.stat().st_size, expected_sha256=digest
                )
            lock_blob_key(session, blob.key)
            documents[relative] = {"key": blob.key, "sha256": blob.sha256}
        checkpoint = self.root / "checkpoint.sqlite3"
        with self._connect() as connection, sqlite3.connect(checkpoint) as target:
            connection.backup(target)
        checkpoint_digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
        lock_blob_key(session, content_addressed_key(checkpoint_digest))
        with checkpoint.open("rb") as stream:
            blob = self._blobs.put(
                stream, maximum_bytes=checkpoint.stat().st_size, expected_sha256=checkpoint_digest
            )
        lock_blob_key(session, blob.key)
        checkpoint.unlink()
        self._manifest = {
            "schema_version": self.schema_version,
            "database": {"key": blob.key, "sha256": blob.sha256},
            "documents": documents,
        }
        row = session.get(MemoryStateRow, UUID(self.context.project_id))
        if row is None:
            session.add(
                MemoryStateRow(
                    project_id=UUID(self.context.project_id),
                    manifest_json=self._manifest,
                    version=1,
                )
            )
        else:
            row.manifest_json = self._manifest
            row.version += 1

    def _project_graph(self, session: Session) -> dict[str, int]:
        project = UUID(self.context.project_id)
        new_nodes = 0
        new_edges = 0
        # Internal full projection is not the bounded public graph view.
        with self._connect() as connection:
            for row in connection.execute("SELECT * FROM nodes"):
                key = (project, row["node_id"])
                if session.get(MemoryNodeRow, key) is None:
                    new_nodes += 1
                session.merge(
                    MemoryNodeRow(
                        project_id=project,
                        node_id=row["node_id"],
                        node_type=row["node_type"],
                        properties_json=json.loads(row["properties_json"]),
                    )
                )
            for row in connection.execute("SELECT * FROM edges"):
                key = (project, row["edge_id"])
                if session.get(MemoryEdgeRow, key) is None:
                    new_edges += 1
                session.merge(
                    MemoryEdgeRow(
                        project_id=project,
                        edge_id=row["edge_id"],
                        source_id=row["source_id"],
                        relation_type=row["relation_type"],
                        target_id=row["target_id"],
                        properties_json=json.loads(row["properties_json"]),
                    )
                )
        return {"new_nodes": new_nodes, "new_edges": new_edges}

    def graph_snapshot(self, *, limit: int = 500) -> dict[str, Any]:
        self._authorize(self.context)
        project = UUID(self.context.project_id)
        bounded = max(1, min(limit, 5000))
        with self._sql.transaction() as session:
            nodes = session.scalars(
                select(MemoryNodeRow)
                .where(MemoryNodeRow.project_id == project)
                .order_by(MemoryNodeRow.node_id)
                .limit(bounded)
            ).all()
            node_ids = [row.node_id for row in nodes]
            edges = session.scalars(
                select(MemoryEdgeRow)
                .where(
                    MemoryEdgeRow.project_id == project,
                    MemoryEdgeRow.source_id.in_(node_ids),
                    MemoryEdgeRow.target_id.in_(node_ids),
                )
                .order_by(MemoryEdgeRow.edge_id)
                .limit(bounded)
            ).all()
            return {
                "schema_version": self.schema_version,
                "bounded": True,
                "limit": bounded,
                "nodes": [
                    {"id": row.node_id, "type": row.node_type, "properties": row.properties_json}
                    for row in nodes
                ],
                "edges": [
                    {
                        "id": row.edge_id,
                        "source": row.source_id,
                        "target": row.target_id,
                        "relation": row.relation_type,
                        "properties": row.properties_json,
                    }
                    for row in edges
                ],
            }


def memory_for_project(
    root: Path,
    project_id: str,
    run_id: str,
    database: Database,
    blobs: BlobStore,
    *,
    user_id: str | None = None,
) -> SqlScientificMemory:
    """Create a worker adapter with membership checked again for every operation."""
    import os

    from sci_search.application.authorization import (
        Action,
        AuthorizationContext,
        ProjectPolicy,
        ResourceNotFound,
    )
    from sci_search.infrastructure.repositories import SqlProjectRepository
    from sci_search.infrastructure.tables import ArticleFeedbackRow, ResearchRunRow

    with database.transaction() as session:
        run = session.get(ResearchRunRow, UUID(run_id))
        if run is None or str(run.project_id) != project_id:
            raise ResourceNotFound
        context = MemoryContext(user_id or str(run.created_by_user_id), project_id)

    def authorize(bound: MemoryContext) -> None:
        with database.transaction() as session:
            ProjectPolicy(SqlProjectRepository(session)).require(
                Action.READ, AuthorizationContext(bound.user_id), bound.project_id
            )

    def feedback() -> list[dict[str, Any]]:
        authorize(context)
        with database.transaction() as session:
            rows = session.execute(
                select(ArticleFeedbackRow, ResearchRunRow.question)
                .join(ResearchRunRow, ArticleFeedbackRow.run_id == ResearchRunRow.id)
                .where(
                    ArticleFeedbackRow.project_id == UUID(project_id),
                    ResearchRunRow.project_id == UUID(project_id),
                )
            ).all()
            return [
                {
                    "id": f"{row.run_id}:{row.sequence}",
                    "project_id": project_id,
                    "run_id": str(row.run_id),
                    "publication_id": row.publication_id,
                    "question": question,
                    "decision": row.decision,
                    "reason": row.reason,
                    "user_id": str(row.user_id),
                    "created_at": row.created_at.isoformat(),
                    "reviewed_revision": row.reviewed_revision,
                    "source_fingerprint": row.source_fingerprint,
                    "question_context": row.context_json,
                }
                for row, question in rows
            ]

    memory = SqlScientificMemory(
        root / "scientific-memory",
        context,
        database,
        blobs,
        authorize=authorize,
        feedback_reader=feedback,
        feedback_ranking_enabled=os.environ.get(
            "SCI_SEARCH_FEEDBACK_RANKING_ENABLED", ""
        ).casefold()
        in {"1", "true"},
    )
    recover_project_memory(memory)
    return memory


def recover_project_memory(memory: SqlScientificMemory, *, limit: int = 25) -> dict[str, int]:
    """Replay a bounded number of archives fairly, skipping unrecoverable legacy rows.

    Missing checkpoints cover a worker crash after dashboard commit. Unattempted
    work precedes retries, which rotate by last attempt time. A legacy snapshot
    without an archive is terminally unavailable rather than permanently pending.
    """
    import tempfile
    import zipfile
    from datetime import UTC, datetime
    from io import BytesIO

    from sqlalchemy import String, and_, case, func, or_, tuple_

    from sci_search.infrastructure.tables import DashboardRevisionRow

    memory._authorize(memory.context)
    project = UUID(memory.context.project_id)
    bounded = max(1, min(limit, 100))
    counts = {"recovered": 0, "pending": 0}
    seen: set[tuple[UUID, int]] = set()
    while counts["recovered"] + counts["pending"] < bounded:
        remaining = bounded - counts["recovered"] - counts["pending"]
        with memory._sql.transaction() as session:
            statement = (
                select(DashboardRevisionRow)
                .outerjoin(
                    MemoryCheckpointRow,
                    and_(
                        MemoryCheckpointRow.project_id == DashboardRevisionRow.project_id,
                        func.replace(MemoryCheckpointRow.run_id, "-", "")
                        == func.replace(DashboardRevisionRow.run_id.cast(String), "-", ""),
                        MemoryCheckpointRow.revision == DashboardRevisionRow.revision,
                        MemoryCheckpointRow.projection_version == memory.schema_version,
                    ),
                )
                .where(
                    DashboardRevisionRow.project_id == project,
                    or_(
                        MemoryCheckpointRow.status.is_(None),
                        MemoryCheckpointRow.status.not_in(("complete", "unavailable")),
                    ),
                )
                .order_by(
                    case(
                        (MemoryCheckpointRow.error.like("____-__-__T%"), MemoryCheckpointRow.error),
                        else_="",
                    ),
                    DashboardRevisionRow.created_at,
                    DashboardRevisionRow.run_id,
                    DashboardRevisionRow.revision,
                )
                .limit(remaining)
            )
            if seen:
                statement = statement.where(
                    tuple_(DashboardRevisionRow.run_id, DashboardRevisionRow.revision).not_in(seen)
                )
            rows = session.scalars(statement).all()
        if not rows:
            break
        for row in rows:
            seen.add((row.run_id, row.revision))
            snapshot = row.snapshot_json
            if not snapshot.get("source_archive_key") or not snapshot.get("internal_run_id"):
                with memory._sql.transaction() as session:
                    session.merge(
                        MemoryCheckpointRow(
                            project_id=project,
                            run_id=str(row.run_id),
                            revision=row.revision,
                            projection_version=memory.schema_version,
                            status="unavailable",
                            error="No retained source archive for this legacy revision",
                        )
                    )
                counts["unavailable"] = counts.get("unavailable", 0) + 1
                continue
            try:
                memory._authorize(memory.context)
                with memory._blobs.open(snapshot["source_archive_key"]) as stream:
                    archive_bytes = stream.read()
                with tempfile.TemporaryDirectory(prefix="sci-memory-replay-") as temporary:
                    root = Path(temporary)
                    with zipfile.ZipFile(BytesIO(archive_bytes)) as archive:
                        for entry in archive.infolist():
                            (root / entry.filename).resolve().relative_to(root)
                        archive.extractall(root)
                    run_root = root / str(snapshot["internal_run_id"])
                    run_root.resolve().relative_to(root)
                    payload = json.loads((run_root / "investigation.json").read_text())
                    memory.ingest_run(
                        str(row.run_id), str(payload["question"]), run_root / "corpus", payload
                    )
                    memory.publish_pending(revision=row.revision, published_run_id=str(row.run_id))
                counts["recovered"] += 1
            except Exception as error:
                memory._pending.clear()
                with memory._sql.transaction() as session:
                    session.merge(
                        MemoryCheckpointRow(
                            project_id=project,
                            run_id=str(row.run_id),
                            revision=row.revision,
                            projection_version=memory.schema_version,
                            status="pending",
                            error=f"{datetime.now(UTC).isoformat()} {type(error).__name__}",
                        )
                    )
                counts["pending"] += 1
    return counts
