"""Project-bound local memory, durable contextual feedback and publication barrier."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from sci_search.application.memory import MemoryCandidate, MemoryContext
from sci_search.discovery import PublicationCandidate
from sci_search.feedback_ranking import rank_candidates, score_feedback
from sci_search.question_planning import ResearchPlan
from sci_search.scientific_memory import ScientificMemory, _canonical_key, _now


class LocalScientificMemory(ScientificMemory):
    """Bind one authorized project, with no implicit import of global CLI memory.

    ``root`` is the application memory root; files live at root/project_id/memory.
    Production must pass a live authorization callback. Local single-owner apps
    authorize at their service boundary and can omit that callback.
    """

    def __init__(
        self,
        root: Path,
        context: MemoryContext,
        *,
        authorize: Callable[[MemoryContext], None] | None = None,
        feedback_reader: Callable[[], list[dict[str, Any]]] | None = None,
        feedback_ranking_enabled: bool = False,
        defer_ingestion: bool = True,
    ) -> None:
        if not context.user_id or not re.fullmatch(r"[A-Za-z0-9_-]+", context.project_id):
            raise ValueError("valid memory owner and project are required")
        self.context = context
        self._authorize = authorize or (lambda context: None)
        self._feedback_reader = feedback_reader
        self.feedback_ranking_enabled = feedback_ranking_enabled
        self.defer_ingestion = defer_ingestion
        self._pending: list[tuple[str, str, Path, dict[str, Any]]] = []
        self._authorize(context)
        super().__init__(root / context.project_id / "memory")
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS contextual_feedback (
                    event_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS revision_checkpoints (
                    run_id TEXT NOT NULL, revision INTEGER NOT NULL, projection_version TEXT NOT NULL,
                    PRIMARY KEY(run_id, revision, projection_version));
            """)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self._authorize(self.context)
        with super()._connect() as connection:
            yield connection

    def feedback_events(self) -> list[dict[str, Any]]:
        self._authorize(self.context)
        if self._feedback_reader is not None:
            # The authoritative store handles project filtering and Reset immediately.
            return self._feedback_reader()
        with self._connect() as connection:
            return [
                json.loads(row[0])
                for row in connection.execute(
                    "SELECT payload_json FROM contextual_feedback ORDER BY event_id"
                )
            ]

    def record_feedback(self, event: dict[str, Any]) -> None:
        self._authorize(self.context)
        required = ("id", "run_id", "publication_id", "question", "decision")
        if any(not event.get(key) for key in required):
            raise ValueError("feedback requires id, run, publication, question and decision")
        if event["decision"] not in {"include", "exclude", "background", "reset"}:
            raise ValueError("unknown relevance decision")
        if event.get("project_id", self.context.project_id) != self.context.project_id:
            raise PermissionError("feedback belongs to another project")
        payload = {
            **event,
            "project_id": self.context.project_id,
            "user_id": event.get("user_id") or self.context.user_id,
            "created_at": event.get("created_at") or _now(),
        }
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT payload_json FROM contextual_feedback WHERE event_id=?", (str(event["id"]),)
            ).fetchone()
            if existing:
                stored = json.loads(existing[0])
                if any(stored.get(key) != payload.get(key) for key in required):
                    raise ValueError("feedback event IDs are immutable")
                return
            connection.execute(
                "INSERT INTO contextual_feedback VALUES (?,?)",
                (str(event["id"]), json.dumps(payload)),
            )
            node = "feedback:" + str(event["id"])
            self._node(connection, node, "FeedbackEvent", str(event["id"]), payload)
            self._edge(connection, node, "ABOUT", "publication:" + str(event["publication_id"]), {})
            context_id = "question-context:" + str(event["run_id"])
            researcher_id = "researcher:" + str(payload["user_id"])
            self._node(
                connection,
                context_id,
                "QuestionContext",
                str(event["run_id"]),
                {"question": event["question"], "run_id": event["run_id"]},
            )
            self._node(
                connection,
                researcher_id,
                "Researcher",
                str(payload["user_id"]),
                {"user_id": payload["user_id"]},
            )
            self._edge(connection, node, "IN_CONTEXT", context_id, {})
            self._edge(connection, node, "MADE_BY", researcher_id, {})

    def ingest_run(
        self, run_id: str, question: str, corpus_directory: Path, investigation: dict[str, Any]
    ) -> dict[str, int]:
        self._authorize(self.context)
        if self.defer_ingestion:
            self._pending.append((run_id, question, corpus_directory, investigation))
            return {"pending_publication": 1}
        return super().ingest_run(run_id, question, corpus_directory, investigation)

    def publish_pending(
        self, *, revision: int = 1, published_run_id: str | None = None
    ) -> dict[str, int]:
        """Call only after the corresponding immutable dashboard has published.

        Failures leave this adapter's work pending; the authoritative dashboard
        archive can replay ingestion after process restart.
        """
        self._authorize(self.context)
        if published_run_id is not None:
            self._pending = [
                (published_run_id, question, corpus, payload)
                for _, question, corpus, payload in self._pending
            ]
        totals: dict[str, int] = {}
        if self._feedback_reader is not None:
            for event in self.feedback_events():
                self.record_feedback(event)
        while self._pending:
            run_id, question, corpus, payload = self._pending[0]
            with self._connect() as connection:
                done = connection.execute(
                    "SELECT 1 FROM revision_checkpoints WHERE run_id=? AND revision=? AND projection_version=?",
                    (run_id, revision, self.schema_version),
                ).fetchone()
                latest = connection.execute(
                    "SELECT MAX(revision) FROM revision_checkpoints WHERE run_id=? AND projection_version=?",
                    (run_id, self.schema_version),
                ).fetchone()[0]
            if not done:
                counts = (
                    super().ingest_run(run_id, question, corpus, payload)
                    if latest is None or revision > latest
                    else {"historical_revision_skipped": 1}
                )
                with self._connect() as connection:
                    revision_id = f"revision:{run_id}:{revision}"
                    self._node(
                        connection,
                        revision_id,
                        "Revision",
                        revision_id,
                        {"run_id": run_id, "revision": revision, "question": question},
                    )
                    self._edge(connection, f"run:{run_id}", "HAS_REVISION", revision_id, {})
                    connection.execute(
                        "INSERT OR IGNORE INTO revision_checkpoints VALUES (?,?,?)",
                        (run_id, revision, self.schema_version),
                    )
                for key, value in counts.items():
                    totals[key] = totals.get(key, 0) + value
            self._pending.pop(0)
        return totals

    def rank_for_acquisition(
        self, plan: ResearchPlan, candidates: tuple[PublicationCandidate, ...]
    ) -> tuple[PublicationCandidate, ...]:
        self._authorize(self.context)
        if not self.feedback_ranking_enabled:
            return candidates
        events = self.feedback_events()
        # Provider aliases resolve to the same canonical DOI before scoring.
        aliases = {
            _canonical_key(candidate.doi, candidate.title): candidate.id for candidate in candidates
        }
        normalized_events = []
        with self._connect() as connection:
            for event in events:
                canonical = _canonical_key(str(event.get("doi")), "") if event.get("doi") else None
                if canonical is None:
                    row = connection.execute(
                        "SELECT canonical_key FROM publications WHERE publication_id=? OR publication_id=(SELECT publication_id FROM publication_aliases WHERE alias_id=?)",
                        (
                            str(event.get("publication_id") or ""),
                            str(event.get("publication_id") or ""),
                        ),
                    ).fetchone()
                    canonical = row[0] if row is not None else None
                if canonical in aliases:
                    event = dict(event)
                    event["publication_id"] = aliases[canonical]
                normalized_events.append(event)
        scored = score_feedback(plan, normalized_events)
        ranked = rank_candidates(
            tuple(
                MemoryCandidate(
                    item,
                    item.relevance_score,
                    float(scored.get(item.id, {}).get("adjustment", 0)),
                    tuple(scored.get(item.id, {}).get("explanations", ())),
                )
                for item in candidates
            )
        )
        return tuple(
            replace(
                item.publication,
                screening_reason=item.publication.screening_reason
                + (
                    " | Feedback suggestion: " + " ".join(item.explanations)
                    if item.explanations
                    else ""
                ),
            )
            for item in ranked
        )
