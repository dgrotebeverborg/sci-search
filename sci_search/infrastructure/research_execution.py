"""Durable worker adapter for the established generic online-research pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select

from sci_search.application.blobs import BlobStore, content_addressed_key
from sci_search.infrastructure.database import Database, lock_blob_key
from sci_search.infrastructure.repositories import SqlResearchRepository
from sci_search.infrastructure.tables import ArtifactRow, EvidenceRow
from sci_search.model_provider import configured_analyzer
from sci_search.research_runs import REVIEW_PROFILES, ResearchLimits, ResearchRunManager
from sci_search.scholarly_providers import CrossrefProvider, EuropePmcProvider, OpenAlexProvider
from sci_search.worker import StageInvocation, StageWork


class RunManager(Protocol):
    def run_sync(
        self, question: str, *, limits: ResearchLimits, question_brief: dict | None = None
    ) -> dict[str, Any]: ...

    def download_literature_review(self, run_id: str, output_format: str = "html") -> Any: ...

    def download_research_package(self, run_id: str) -> Any: ...


ManagerFactory = Callable[[Path], RunManager]


class ProductionResearchStage:
    """Execute one complete bounded review, then idempotently publish its evidence."""

    def __init__(
        self,
        database: Database,
        blobs: BlobStore,
        *,
        manager_factory: ManagerFactory | None = None,
    ) -> None:
        self._database = database
        self._blobs = blobs
        self._manager_factory = manager_factory or _manager

    def __call__(self, invocation: StageInvocation) -> StageWork:
        from sci_search.model_provider import analysis_scope

        with analysis_scope(invocation.input_payload.get("analysis_selection")):
            return self._execute_selected(invocation)

    def _execute_selected(self, invocation: StageInvocation) -> StageWork:
        inputs = invocation.input_payload
        question = str(inputs.get("question") or "").strip()
        project_id = str(inputs.get("project_id") or "")
        run_id = str(inputs.get("run_id") or "")
        review_depth = str(inputs.get("review_depth") or "focused")
        if not question or not project_id or not run_id:
            raise ValueError("research stage requires question, project, and run identifiers")
        invocation.cancellation.raise_if_requested()
        with tempfile.TemporaryDirectory(prefix="sci-search-research-") as temporary_name:
            root = Path(temporary_name)
            manager = self._manager_factory(root)
            memory = None
            if isinstance(manager, ResearchRunManager):
                from sci_search.infrastructure.sql_memory import memory_for_project

                memory = memory_for_project(root, project_id, run_id, self._database, self._blobs)
                manager.memory = memory
            brief = inputs.get("question_brief")
            state = manager.run_sync(
                question,
                limits=_limits(review_depth),
                **({"question_brief": brief} if isinstance(brief, dict) else {}),
            )
            invocation.cancellation.raise_if_requested()
            if state.get("status") != "complete" or not isinstance(state.get("result"), dict):
                raise RuntimeError("scientific research pipeline did not complete")
            result = state["result"]
            result["analysis_selection"] = inputs.get("analysis_selection")
            internal_run_id = str(state["run_id"])
            counts = self._publish_corpus(
                project_id,
                run_id,
                root / internal_run_id / "corpus",
                result,
            )
            artifacts = self._publish_artifacts(
                project_id,
                run_id,
                question,
                state,
                manager,
                internal_run_id,
            )
            revision = self.publish_dashboard(
                project_id, run_id, state, root, internal_run_id, artifacts, feedback_sequence=0
            )
            if memory is not None and revision is not None:
                self.publish_memory(memory, run_id, revision)
        return StageWork(
            output={**counts, "artifact_ids": artifacts},
            next_stage="complete",
            input_fingerprint=hashlib.sha256(
                f"{project_id}\x1f{run_id}\x1f{question}\x1f{review_depth}\x1f{json.dumps(inputs.get('analysis_selection'), sort_keys=True)}".encode()
            ).hexdigest(),
            implementation_version="production-research-v1",
            complete=True,
        )

    def publish_memory(self, memory: Any, run_id: str, revision: int) -> None:
        """A failed projection remains retryable without hiding a saved dashboard."""
        from sci_search.infrastructure.memory_tables import MemoryCheckpointRow

        try:
            memory.publish_pending(revision=revision, published_run_id=run_id)
        except Exception as error:
            with self._database.transaction() as session:
                session.merge(
                    MemoryCheckpointRow(
                        project_id=UUID(memory.context.project_id),
                        run_id=run_id,
                        revision=revision,
                        projection_version=memory.schema_version,
                        status="pending",
                        error=type(error).__name__,
                    )
                )

    def _publish_corpus(
        self,
        project_id: str,
        run_id: str,
        corpus: Path,
        result: dict[str, Any],
    ) -> dict[str, int]:
        manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
        document_ids: dict[str, str] = {}
        for record in manifest.get("documents", []):
            if not isinstance(record, dict):
                continue
            publication_id = str(record.get("id") or "")
            relative = str(record.get("download_path") or record.get("path") or "")
            source = (corpus / relative).resolve()
            try:
                source.relative_to(corpus.resolve())
            except ValueError as error:
                raise ValueError("research document escaped its corpus") from error
            if not publication_id or not source.is_file():
                continue
            maximum = max(source.stat().st_size, 1)
            canonical = str(record.get("doi") or publication_id).strip().casefold()
            with source.open("rb") as stream:
                expected_digest = hashlib.file_digest(stream, "sha256").hexdigest()
            with self._database.transaction() as session:
                lock_blob_key(session, content_addressed_key(expected_digest))
                with source.open("rb") as stream:
                    blob = self._blobs.put(
                        stream,
                        maximum,
                        content_type=str(record.get("content_type") or "application/octet-stream"),
                        expected_sha256=expected_digest,
                    )
                repository = SqlResearchRepository(session)
                document_id = repository.grant_document(
                    project_id,
                    canonical_publication_key=canonical,
                    title=str(record.get("title") or publication_id),
                    blob=blob,
                    metadata={
                        key: record.get(key)
                        for key in ("doi", "year", "authors", "source_url", "license")
                    },
                )
                repository.link_run_document(
                    project_id, run_id, document_id, relation="analyzed_full_text"
                )
            document_ids[publication_id] = document_id

        evidence_count = 0
        for evidence in result.get("evidence", []):
            if not isinstance(evidence, dict):
                continue
            document_id = document_ids.get(str(evidence.get("publication_id") or ""))
            statement = str(evidence.get("statement") or "").strip()
            passage = str(evidence.get("passage") or "").strip()
            if not document_id or not statement or not passage:
                continue
            with self._database.transaction() as session:
                existing = session.scalar(
                    select(EvidenceRow.id).where(
                        EvidenceRow.project_id == UUID(project_id),
                        EvidenceRow.run_id == UUID(run_id),
                        EvidenceRow.document_id == UUID(document_id),
                        EvidenceRow.statement == statement,
                        EvidenceRow.source_passage == passage,
                    )
                )
                if existing is not None:
                    continue
                repository = SqlResearchRepository(session)
                evidence_id = repository.add_evidence(
                    project_id,
                    document_id=document_id,
                    run_id=run_id,
                    statement=statement,
                    source_passage=passage,
                    section=str(evidence.get("section") or "") or None,
                    page=_optional_page(evidence.get("page")),
                    extraction_method=str(
                        evidence.get("extraction_method") or "extractive_scientific_evidence_v1"
                    ),
                    context={
                        key: value
                        for key, value in evidence.items()
                        if key
                        not in {
                            "statement",
                            "passage",
                            "publication_title",
                            "source_document",
                        }
                    },
                    created_at=_run_timestamp(),
                )
                for check in evidence.get("validation_checks", []):
                    if not isinstance(check, dict):
                        continue
                    repository.add_validation_check(
                        project_id,
                        evidence_id,
                        check_name=str(check.get("name") or check.get("check") or "grounding"),
                        status=str(check.get("status") or "unknown"),
                        details={
                            key: value
                            for key, value in check.items()
                            if key not in {"passage", "text", "prompt"}
                        },
                        created_at=_run_timestamp(),
                    )
                evidence_count += 1
        return {"documents": len(document_ids), "evidence": evidence_count}

    def _publish_artifacts(
        self,
        project_id: str,
        run_id: str,
        question: str,
        state: dict[str, Any],
        manager: RunManager,
        internal_run_id: str,
        feedback_sequence: int = 0,
    ) -> list[str]:
        payloads = [
            (
                "research-run.json",
                "application/json",
                (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode(),
            ),
        ]
        review = manager.download_literature_review(internal_run_id, "pdf")
        package = manager.download_research_package(internal_run_id)
        payloads.extend(
            [
                ("literature-review.pdf", str(review.content_type), bytes(review.body)),
                ("complete-research-package.zip", str(package.content_type), bytes(package.body)),
            ]
        )
        fingerprint = hashlib.sha256(f"{question}:{feedback_sequence}".encode()).hexdigest()
        artifact_ids: list[str] = []
        for kind, content_type, body in payloads:
            expected_digest = hashlib.sha256(body).hexdigest()
            with self._database.transaction() as session:
                lock_blob_key(session, content_addressed_key(expected_digest))
                blob = self._blobs.put(
                    BytesIO(body),
                    len(body),
                    content_type=content_type,
                    expected_sha256=expected_digest,
                )
                existing = session.scalar(
                    select(ArtifactRow.id).where(
                        ArtifactRow.project_id == UUID(project_id),
                        ArtifactRow.run_id == UUID(run_id),
                        ArtifactRow.kind == kind,
                        ArtifactRow.input_fingerprint == fingerprint,
                    )
                )
                if existing is None:
                    existing = UUID(
                        SqlResearchRepository(session).add_artifact(
                            project_id,
                            run_id=run_id,
                            kind=kind,
                            blob_key=blob.key,
                            input_fingerprint=fingerprint,
                            generator_version="production-research-v1",
                            created_at=_run_timestamp(),
                        )
                    )
                artifact_ids.append(str(existing))
        return artifact_ids

    def publish_dashboard(
        self,
        project_id: str,
        run_id: str,
        state: dict[str, Any],
        root: Path,
        internal_run_id: str,
        artifacts: list[str],
        *,
        feedback_sequence: int,
    ) -> int | None:
        from sci_search.dashboard import build_dashboard
        from sci_search.infrastructure.dashboard_repository import DashboardRepository

        archive = BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for path in sorted((root / internal_run_id).rglob("*")):
                if path.is_file() and not path.is_symlink():
                    target.write(path, str(path.relative_to(root)))
        body = archive.getvalue()
        digest = hashlib.sha256(body).hexdigest()
        with self._database.transaction() as session:
            lock_blob_key(session, content_addressed_key(digest))
            blob = self._blobs.put(
                BytesIO(body),
                max(1, len(body)),
                content_type="application/zip",
                expected_sha256=digest,
            )
            snapshot = build_dashboard(state["result"], run_id=run_id, revision=1)
            snapshot.update(
                candidate_ids=[str(c["id"]) for c in state.get("candidates", [])],
                source_archive_key=blob.key,
                internal_run_id=internal_run_id,
                artifacts=[],
                documents={},
            )
            manifest = json.loads((root / internal_run_id / "corpus" / "manifest.json").read_text())
            from sci_search.infrastructure.tables import (
                PublicationDocumentRow,
                PublicationRow,
                RunDocumentRow,
            )

            for record in manifest.get("documents", []):
                canonical = str(record.get("doi") or record.get("id") or "").strip().casefold()
                document_id = session.scalar(
                    select(PublicationDocumentRow.document_id)
                    .join(
                        PublicationRow, PublicationRow.id == PublicationDocumentRow.publication_id
                    )
                    .join(
                        RunDocumentRow,
                        RunDocumentRow.document_id == PublicationDocumentRow.document_id,
                    )
                    .where(
                        PublicationRow.canonical_key == canonical,
                        RunDocumentRow.run_id == UUID(run_id),
                    )
                    .limit(1)
                )
                if document_id:
                    snapshot["documents"][str(record["id"])] = {
                        "url": f"/api/v1/projects/{project_id}/documents/{document_id}",
                        "title": str(record.get("title") or record["id"]),
                    }
            for identifier in artifacts:
                row = session.get(ArtifactRow, UUID(identifier))
                if row:
                    from sci_search.infrastructure.production_services import _artifact_metadata

                    filename, content_type = _artifact_metadata(row.kind, row.id)
                    snapshot["artifacts"].append(
                        {
                            "id": identifier,
                            "filename": filename,
                            "content_type": content_type,
                            "url": f"/api/v1/projects/{project_id}/exports/{identifier}",
                        }
                    )
            # Archive remains an artifact so storage GC tracks its durable reference.
            existing = session.scalar(
                select(ArtifactRow.id).where(
                    ArtifactRow.run_id == UUID(run_id),
                    ArtifactRow.kind == "retained-source-archive",
                    ArtifactRow.input_fingerprint == digest,
                )
            )
            if existing is None:
                SqlResearchRepository(session).add_artifact(
                    project_id,
                    run_id=run_id,
                    kind="retained-source-archive",
                    blob_key=blob.key,
                    input_fingerprint=digest,
                    generator_version="dashboard-v1",
                    created_at=_run_timestamp(),
                )
            revision = DashboardRepository(session).publish(
                project_id,
                run_id,
                snapshot,
                feedback_sequence=feedback_sequence,
                created_at=_run_timestamp(),
            )
        return revision


def _manager(root: Path, *, memory: Any = None) -> ResearchRunManager:
    api_key = os.environ.get("OPENALEX_API_KEY", "").strip()
    providers: tuple[Any, ...]
    if api_key:
        providers = (OpenAlexProvider(api_key), EuropePmcProvider(), CrossrefProvider())
    else:
        providers = (EuropePmcProvider(), CrossrefProvider())
    return ResearchRunManager(
        root,
        memory=memory,
        providers=providers,
        openalex_api_key=api_key or "not-configured-provider-disabled",
        analyzer=configured_analyzer(),
    )


def _limits(review_depth: str) -> ResearchLimits:
    mode = "deep" if review_depth == "deep" else "quick"
    profile = REVIEW_PROFILES[mode]
    return ResearchLimits(
        per_query=profile["per_query"],
        max_selected=profile["selected"],
        max_full_texts=profile["maximum"],
        max_acquisition_attempts=profile["attempts"],
        citation_seed_count=profile["seeds"],
        citation_neighbors_per_seed=profile["neighbors"],
        review_mode=mode,
        initial_full_texts=profile["initial"],
        acquisition_batch_size=profile["batch"],
    )


def _optional_page(value: object) -> int | None:
    if not isinstance(value, (int, str)):
        return None
    try:
        page = int(value)
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None


def _run_timestamp() -> datetime:
    return datetime.now(UTC)
