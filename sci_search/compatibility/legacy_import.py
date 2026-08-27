"""Read-only, fingerprinted import of legacy Sci-Search memory and run files."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select

from sci_search.application.blobs import BlobStore
from sci_search.infrastructure.database import Database
from sci_search.infrastructure.repositories import SqlResearchRepository
from sci_search.infrastructure.tables import (
    AuditEventRow,
    DocumentRow,
    LegacyImportRow,
    PublicationRow,
)


@dataclass(frozen=True, slots=True)
class LegacyPublication:
    source_id: str
    canonical_key: str
    title: str
    metadata: dict[str, Any]
    document_path: Path
    sha256: str
    size: int
    content_type: str


@dataclass(frozen=True, slots=True)
class LegacyEvidence:
    source_id: str
    publication_id: str
    statement: str
    source_passage: str
    section: str | None
    page: int | None
    extraction_method: str
    context: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class LegacyRun:
    source_id: str
    question: str
    status: str
    created_at: datetime
    publication_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ImportManifest:
    root: Path
    source_fingerprint: str
    publications: tuple[LegacyPublication, ...]
    runs: tuple[LegacyRun, ...]
    evidence: tuple[LegacyEvidence, ...]

    @property
    def publication_count(self) -> int:
        return len(self.publications)

    @property
    def run_count(self) -> int:
        return len(self.runs)

    @property
    def evidence_count(self) -> int:
        return len(self.evidence)

    @property
    def blob_count(self) -> int:
        return len({item.sha256 for item in self.publications})


@dataclass(frozen=True, slots=True)
class LegacyImportTarget:
    database: Database
    project_id: str
    actor_user_id: str


@dataclass(frozen=True, slots=True)
class ImportResult:
    dry_run: bool
    source_fingerprint: str
    publications_added: int
    runs_added: int
    evidence_added: int
    blobs_added: int
    already_imported: bool = False


def scan_legacy(root: Path) -> ImportManifest:
    """Validate and fingerprint supported legacy files without modifying them."""
    resolved_root = root.resolve(strict=True)
    memory_root = resolved_root / "scientific_memory"
    database_path = memory_root / "memory.sqlite3"
    if not database_path.is_file():
        raise ValueError("legacy scientific_memory/memory.sqlite3 is required")

    tracked_paths: set[Path] = {database_path}
    publications = _scan_publications(resolved_root, memory_root, database_path, tracked_paths)
    known_publications = {item.source_id for item in publications}
    evidence = _scan_evidence(database_path, known_publications)
    runs = _scan_runs(resolved_root, known_publications, tracked_paths)
    fingerprint = _source_fingerprint(resolved_root, tracked_paths)
    return ImportManifest(
        root=resolved_root,
        source_fingerprint=fingerprint,
        publications=tuple(publications),
        runs=tuple(runs),
        evidence=tuple(evidence),
    )


def apply_import(
    manifest: ImportManifest,
    target: LegacyImportTarget,
    blob_store: BlobStore,
    *,
    apply: bool = False,
) -> ImportResult:
    """Copy a validated manifest; dry-run unless ``apply=True`` is explicit."""
    if not apply:
        return ImportResult(True, manifest.source_fingerprint, 0, 0, 0, 0)

    with target.database.transaction() as session:
        imported = session.scalar(
            select(LegacyImportRow.id).where(
                LegacyImportRow.project_id == _uuid(target.project_id),
                LegacyImportRow.source_fingerprint == manifest.source_fingerprint,
            )
        )
    if imported is not None:
        return ImportResult(False, manifest.source_fingerprint, 0, 0, 0, 0, True)

    blobs_by_publication: dict[str, Any] = {}
    for publication in manifest.publications:
        with publication.document_path.open("rb") as source:
            blobs_by_publication[publication.source_id] = blob_store.put(
                source,
                max(publication.size, 1),
                content_type=publication.content_type,
                expected_sha256=publication.sha256,
            )

    with target.database.transaction() as session:
        # Recheck inside the write transaction for retries or competing operators.
        imported = session.scalar(
            select(LegacyImportRow.id).where(
                LegacyImportRow.project_id == _uuid(target.project_id),
                LegacyImportRow.source_fingerprint == manifest.source_fingerprint,
            )
        )
        if imported is not None:
            return ImportResult(False, manifest.source_fingerprint, 0, 0, 0, 0, True)

        research = SqlResearchRepository(session)
        publication_count_before = int(
            session.scalar(select(func.count()).select_from(PublicationRow)) or 0
        )
        document_count_before = int(
            session.scalar(select(func.count()).select_from(DocumentRow)) or 0
        )
        document_ids: dict[str, str] = {}
        for publication in manifest.publications:
            document_ids[publication.source_id] = research.grant_document(
                target.project_id,
                canonical_publication_key=publication.canonical_key,
                title=publication.title,
                blob=blobs_by_publication[publication.source_id],
                metadata=publication.metadata,
            )

        run_ids: dict[str, str] = {}
        for run in manifest.runs:
            run_id = research.create_run(
                target.project_id,
                created_by_user_id=target.actor_user_id,
                question=run.question,
                configuration={"legacy_source_id": run.source_id},
                created_at=run.created_at,
                status=run.status,
            )
            run_ids[run.source_id] = run_id
            for publication_id in run.publication_ids:
                document_id = document_ids.get(publication_id)
                if document_id is not None:
                    research.link_run_document(
                        target.project_id, run_id, document_id, relation="legacy_included"
                    )

        for item in manifest.evidence:
            document_id = document_ids[item.publication_id]
            research.add_evidence(
                target.project_id,
                document_id=document_id,
                statement=item.statement,
                source_passage=item.source_passage,
                section=item.section,
                page=item.page,
                extraction_method=item.extraction_method,
                created_at=item.created_at,
                context={**item.context, "legacy_source_id": item.source_id},
            )

        session.flush()
        publications_added = (
            int(session.scalar(select(func.count()).select_from(PublicationRow)) or 0)
            - publication_count_before
        )
        blobs_added = (
            int(session.scalar(select(func.count()).select_from(DocumentRow)) or 0)
            - document_count_before
        )
        counts = {
            "publications": publications_added,
            "runs": len(run_ids),
            "evidence": len(manifest.evidence),
            "blobs": blobs_added,
        }
        session.add(
            LegacyImportRow(
                id=uuid4(),
                project_id=_uuid(target.project_id),
                source_fingerprint=manifest.source_fingerprint,
                source_root=str(manifest.root),
                manifest_json=_manifest_summary(manifest),
                counts_json=counts,
                applied_at=datetime.now(UTC),
            )
        )
        session.add(
            AuditEventRow(
                id=uuid4(),
                occurred_at=datetime.now(UTC),
                actor_user_id=_uuid(target.actor_user_id),
                project_id=_uuid(target.project_id),
                action="legacy_import.applied",
                entity_type="legacy_import",
                entity_id=manifest.source_fingerprint,
                payload=counts,
            )
        )
        return ImportResult(
            False,
            manifest.source_fingerprint,
            publications_added,
            len(run_ids),
            len(manifest.evidence),
            blobs_added,
        )


def _scan_publications(
    root: Path,
    memory_root: Path,
    database_path: Path,
    tracked_paths: set[Path],
) -> list[LegacyPublication]:
    with _read_only_sqlite(database_path) as connection:
        _require_columns(
            connection,
            "publications",
            {"publication_id", "canonical_key", "metadata_json", "content_sha256", "cache_path"},
        )
        rows = connection.execute(
            "SELECT publication_id,canonical_key,metadata_json,content_sha256,cache_path "
            "FROM publications WHERE cache_path IS NOT NULL ORDER BY publication_id"
        ).fetchall()
    result: list[LegacyPublication] = []
    for row in rows:
        metadata = _json_object(row["metadata_json"], "publication metadata")
        path = _contained_path(root, memory_root / str(row["cache_path"]))
        if not path.is_file():
            raise ValueError(f"legacy document does not exist: {row['cache_path']}")
        digest = _sha256_file(path)
        declared = str(row["content_sha256"] or "")
        if declared and declared != digest:
            raise ValueError(f"legacy document hash mismatch: {row['publication_id']}")
        tracked_paths.add(path)
        result.append(
            LegacyPublication(
                source_id=str(row["publication_id"]),
                canonical_key=str(row["canonical_key"]),
                title=str(metadata.get("title") or "Untitled legacy publication"),
                metadata=metadata,
                document_path=path,
                sha256=digest,
                size=path.stat().st_size,
                content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            )
        )
    return result


def _scan_evidence(database_path: Path, publication_ids: set[str]) -> list[LegacyEvidence]:
    with _read_only_sqlite(database_path) as connection:
        _require_columns(
            connection,
            "evidence_records",
            {"evidence_id", "publication_id", "extraction_method", "payload_json", "first_seen_at"},
        )
        rows = connection.execute(
            "SELECT evidence_id,publication_id,extraction_method,payload_json,first_seen_at "
            "FROM evidence_records ORDER BY evidence_id"
        ).fetchall()
    result: list[LegacyEvidence] = []
    for row in rows:
        publication_id = str(row["publication_id"])
        if publication_id not in publication_ids:
            continue
        payload = _json_object(row["payload_json"], "evidence payload")
        statement = str(payload.get("statement") or "").strip()
        source_passage = str(payload.get("source_passage") or payload.get("passage") or "").strip()
        if not statement or not source_passage:
            raise ValueError(f"legacy evidence lacks exact provenance: {row['evidence_id']}")
        page_value = payload.get("page")
        result.append(
            LegacyEvidence(
                source_id=str(row["evidence_id"]),
                publication_id=publication_id,
                statement=statement,
                source_passage=source_passage,
                section=str(payload["section"]) if payload.get("section") is not None else None,
                page=int(page_value) if page_value is not None else None,
                extraction_method=str(row["extraction_method"]),
                context=payload,
                created_at=_parse_datetime(str(row["first_seen_at"])),
            )
        )
    return result


def _scan_runs(root: Path, publication_ids: set[str], tracked_paths: set[Path]) -> list[LegacyRun]:
    runs_root = root / "research_runs"
    if not runs_root.exists():
        return []
    result: list[LegacyRun] = []
    for path in sorted(runs_root.glob("*/run.json")):
        path = _contained_path(root, path)
        payload = _json_object(path.read_text(encoding="utf-8"), "research run")
        source_id = str(payload.get("run_id") or path.parent.name)
        question = str(payload.get("question") or "").strip()
        if not question:
            raise ValueError(f"legacy run has no question: {source_id}")
        raw_run_result = payload.get("result")
        run_result: dict[str, Any] = raw_run_result if isinstance(raw_run_result, dict) else {}
        raw_research_run = run_result.get("research_run")
        research_run: dict[str, Any] = (
            raw_research_run if isinstance(raw_research_run, dict) else {}
        )
        selected_values = payload.get("active_publication_ids") or research_run.get(
            "active_publication_ids", []
        )
        selected = tuple(
            item
            for item in dict.fromkeys(str(value) for value in selected_values)
            if item in publication_ids
        )
        tracked_paths.add(path)
        result.append(
            LegacyRun(
                source_id=source_id,
                question=question,
                status=str(payload.get("status") or "imported"),
                created_at=_parse_datetime(str(payload.get("created_at") or "")),
                publication_ids=selected,
            )
        )
    return result


def _read_only_sqlite(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _require_columns(connection: sqlite3.Connection, table: str, required: set[str]) -> None:
    columns = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
    missing = required - columns
    if missing:
        raise ValueError(f"legacy {table} schema is missing: {', '.join(sorted(missing))}")


def _contained_path(root: Path, candidate: Path) -> Path:
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError("legacy path points outside legacy root") from error
    return resolved


def _source_fingerprint(root: Path, paths: set[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_object(raw: str, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {label} JSON") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _parse_datetime(raw: str) -> datetime:
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return datetime.fromtimestamp(0, tz=UTC)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _manifest_summary(manifest: ImportManifest) -> dict[str, Any]:
    return {
        "source_fingerprint": manifest.source_fingerprint,
        "publication_ids": [item.source_id for item in manifest.publications],
        "run_ids": [item.source_id for item in manifest.runs],
        "evidence_ids": [item.source_id for item in manifest.evidence],
    }


def _uuid(value: str) -> UUID:
    return UUID(value)
