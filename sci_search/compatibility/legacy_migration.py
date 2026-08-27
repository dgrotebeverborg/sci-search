"""Durable, resumable execution and parity validation for legacy imports."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import func, select

from sci_search.infrastructure.repositories import SqlResearchRepository
from sci_search.infrastructure.tables import (
    AuditEventRow,
    DocumentRow,
    EvidenceRow,
    LegacyImportRow,
    PublicationRow,
    ResearchRunRow,
)

if TYPE_CHECKING:
    from sci_search.application.blobs import BlobStore
    from sci_search.compatibility.legacy_import import (
        ImportManifest,
        ImportResult,
        LegacyImportTarget,
    )


def apply_resumable_import(
    manifest: ImportManifest,
    target: LegacyImportTarget,
    blob_store: BlobStore,
    *,
    apply: bool,
    batch_size: int,
    maximum_batches: int | None,
) -> ImportResult:
    from sci_search.compatibility.legacy_import import ImportResult

    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if maximum_batches is not None and maximum_batches < 1:
        raise ValueError("maximum_batches must be positive")
    if not apply:
        return ImportResult(True, manifest.source_fingerprint, 0, 0, 0, 0)
    _create_ledger(manifest, target)
    status, counts = _status_and_counts(manifest, target)
    if status == "completed":
        return ImportResult(False, manifest.source_fingerprint, 0, 0, 0, 0, True)

    batch_count = 0
    phases: tuple[tuple[str, tuple[Any, ...]], ...] = (
        ("publications", manifest.publications),
        ("runs", manifest.runs),
        ("evidence", manifest.evidence),
    )
    for phase, items in phases:
        while (start := _checkpoint(manifest, target, phase)) < len(items):
            stop = min(start + batch_size, len(items))
            if phase == "publications":
                _publications(manifest, target, blob_store, start, stop)
            elif phase == "runs":
                _runs(manifest, target, start, stop)
            else:
                _evidence(manifest, target, start, stop)
            batch_count += 1
            if maximum_batches is not None and batch_count >= maximum_batches:
                _, counts = _status_and_counts(manifest, target)
                return ImportResult(
                    False,
                    manifest.source_fingerprint,
                    counts["publications"],
                    counts["runs"],
                    counts["evidence"],
                    counts["blobs"],
                    completed=False,
                    next_phase=phase,
                )
    counts = _complete(manifest, target)
    return ImportResult(
        False,
        manifest.source_fingerprint,
        counts["publications"],
        counts["runs"],
        counts["evidence"],
        counts["blobs"],
    )


def _create_ledger(manifest: ImportManifest, target: LegacyImportTarget) -> None:
    with target.database.transaction() as session:
        existing = session.scalar(
            select(LegacyImportRow.id).where(
                LegacyImportRow.project_id == _uuid(target.project_id),
                LegacyImportRow.source_fingerprint == manifest.source_fingerprint,
            )
        )
        if existing is not None:
            return
        prior_mappings: dict[str, dict[str, str]] = {
            "publications": {},
            "runs": {},
            "evidence": {},
        }
        prior_rows = session.scalars(
            select(LegacyImportRow).where(
                LegacyImportRow.project_id == _uuid(target.project_id),
                LegacyImportRow.status == "completed",
            )
        )
        allowed = {
            "publications": {item.source_id for item in manifest.publications},
            "runs": {item.source_id for item in manifest.runs},
            "evidence": {item.source_id for item in manifest.evidence},
        }
        for prior in prior_rows:
            raw = prior.manifest_json.get("mappings", {})
            for kind in prior_mappings:
                prior_mappings[kind].update(
                    {
                        source_id: target_id
                        for source_id, target_id in raw.get(kind, {}).items()
                        if source_id in allowed[kind]
                    }
                )
        now = datetime.now(UTC)
        session.add(
            LegacyImportRow(
                id=uuid4(),
                project_id=_uuid(target.project_id),
                source_fingerprint=manifest.source_fingerprint,
                source_root=str(manifest.root),
                manifest_json={
                    "source_fingerprint": manifest.source_fingerprint,
                    "publication_ids": [item.source_id for item in manifest.publications],
                    "run_ids": [item.source_id for item in manifest.runs],
                    "evidence_ids": [item.source_id for item in manifest.evidence],
                    "conflict_policy": "preserve_source_variants",
                    "mappings": prior_mappings,
                },
                counts_json={"publications": 0, "runs": 0, "evidence": 0, "blobs": 0},
                status="in_progress",
                checkpoint_json={"publications": 0, "runs": 0, "evidence": 0},
                applied_at=now,
                updated_at=now,
                completed_at=None,
            )
        )


def _locked_ledger(
    manifest: ImportManifest, target: LegacyImportTarget, session: Any
) -> LegacyImportRow:
    row = session.scalar(
        select(LegacyImportRow)
        .where(
            LegacyImportRow.project_id == _uuid(target.project_id),
            LegacyImportRow.source_fingerprint == manifest.source_fingerprint,
        )
        .with_for_update()
    )
    if row is None:
        raise RuntimeError("legacy import ledger disappeared")
    return row


def _status_and_counts(
    manifest: ImportManifest, target: LegacyImportTarget
) -> tuple[str, dict[str, int]]:
    with target.database.transaction() as session:
        row = _locked_ledger(manifest, target, session)
        return row.status, {key: int(value) for key, value in row.counts_json.items()}


def _checkpoint(manifest: ImportManifest, target: LegacyImportTarget, phase: str) -> int:
    with target.database.transaction() as session:
        return int(_locked_ledger(manifest, target, session).checkpoint_json.get(phase, 0))


def _publications(
    manifest: ImportManifest,
    target: LegacyImportTarget,
    blob_store: BlobStore,
    start: int,
    stop: int,
) -> None:
    selected = manifest.publications[start:stop]
    blobs: dict[str, Any] = {}
    for publication in selected:
        with publication.document_path.open("rb") as source:
            blobs[publication.source_id] = blob_store.put(
                source,
                max(publication.size, 1),
                content_type=publication.content_type,
                expected_sha256=publication.sha256,
            )
    with target.database.transaction() as session:
        ledger = _locked_ledger(manifest, target, session)
        if int(ledger.checkpoint_json.get("publications", 0)) != start:
            return
        research = SqlResearchRepository(session)
        before = int(session.scalar(select(func.count()).select_from(DocumentRow)) or 0)
        summary, mappings = _mapping_copies(ledger)
        mapped = dict(mappings["publications"])
        for publication in selected:
            mapped[publication.source_id] = research.grant_document(
                target.project_id,
                canonical_publication_key=publication.canonical_key,
                title=publication.title,
                blob=blobs[publication.source_id],
                metadata=publication.metadata,
            )
            _preserve_metadata_variant(session, manifest, publication)
        session.flush()
        added = int(session.scalar(select(func.count()).select_from(DocumentRow)) or 0) - before
        mappings["publications"] = mapped
        _advance(ledger, summary, mappings, "publications", stop, added_blobs=added)


def _preserve_metadata_variant(session: Any, manifest: ImportManifest, publication: Any) -> None:
    row = session.scalar(
        select(PublicationRow).where(PublicationRow.canonical_key == publication.canonical_key)
    )
    if row is None or (
        row.title == publication.title and row.metadata_json == publication.metadata
    ):
        return
    metadata = dict(row.metadata_json)
    variants = list(metadata.get("legacy_source_variants", []))
    variant = {
        "source_fingerprint": manifest.source_fingerprint,
        "source_id": publication.source_id,
        "title": publication.title,
        "metadata": publication.metadata,
    }
    if variant not in variants:
        variants.append(variant)
    metadata["legacy_source_variants"] = variants
    row.metadata_json = metadata


def _runs(manifest: ImportManifest, target: LegacyImportTarget, start: int, stop: int) -> None:
    with target.database.transaction() as session:
        ledger = _locked_ledger(manifest, target, session)
        if int(ledger.checkpoint_json.get("runs", 0)) != start:
            return
        research = SqlResearchRepository(session)
        summary, mappings = _mapping_copies(ledger)
        document_ids = mappings["publications"]
        mapped = dict(mappings["runs"])
        for run in manifest.runs[start:stop]:
            if run.source_id in mapped:
                continue
            run_id = research.create_run(
                target.project_id,
                created_by_user_id=target.actor_user_id,
                question=run.question,
                configuration={
                    "legacy_source_id": run.source_id,
                    "legacy_source_fingerprint": manifest.source_fingerprint,
                },
                created_at=run.created_at,
                status=run.status,
            )
            mapped[run.source_id] = run_id
            for source_id in run.publication_ids:
                if source_id in document_ids:
                    research.link_run_document(
                        target.project_id,
                        run_id,
                        document_ids[source_id],
                        relation="legacy_included",
                    )
        mappings["runs"] = mapped
        _advance(ledger, summary, mappings, "runs", stop)


def _evidence(manifest: ImportManifest, target: LegacyImportTarget, start: int, stop: int) -> None:
    with target.database.transaction() as session:
        ledger = _locked_ledger(manifest, target, session)
        if int(ledger.checkpoint_json.get("evidence", 0)) != start:
            return
        research = SqlResearchRepository(session)
        summary, mappings = _mapping_copies(ledger)
        document_ids = mappings["publications"]
        mapped = dict(mappings["evidence"])
        for item in manifest.evidence[start:stop]:
            if item.source_id in mapped:
                continue
            mapped[item.source_id] = research.add_evidence(
                target.project_id,
                document_id=document_ids[item.publication_id],
                statement=item.statement,
                source_passage=item.source_passage,
                section=item.section,
                page=item.page,
                extraction_method=item.extraction_method,
                created_at=item.created_at,
                context={
                    **item.context,
                    "legacy_source_id": item.source_id,
                    "legacy_source_fingerprint": manifest.source_fingerprint,
                },
            )
        mappings["evidence"] = mapped
        _advance(ledger, summary, mappings, "evidence", stop)


def _mapping_copies(row: LegacyImportRow) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    summary = dict(row.manifest_json)
    raw = summary.get("mappings", {})
    mappings = {
        "publications": dict(raw.get("publications", {})),
        "runs": dict(raw.get("runs", {})),
        "evidence": dict(raw.get("evidence", {})),
    }
    return summary, mappings


def _advance(
    ledger: LegacyImportRow,
    summary: dict[str, Any],
    mappings: dict[str, dict[str, str]],
    phase: str,
    stop: int,
    *,
    added_blobs: int = 0,
) -> None:
    summary["mappings"] = mappings
    ledger.manifest_json = summary
    checkpoint = dict(ledger.checkpoint_json)
    checkpoint[phase] = stop
    ledger.checkpoint_json = checkpoint
    counts = dict(ledger.counts_json)
    counts[phase] = stop
    counts["blobs"] = int(counts.get("blobs", 0)) + added_blobs
    ledger.counts_json = counts
    ledger.updated_at = datetime.now(UTC)


def _complete(manifest: ImportManifest, target: LegacyImportTarget) -> dict[str, int]:
    with target.database.transaction() as session:
        ledger = _locked_ledger(manifest, target, session)
        now = datetime.now(UTC)
        ledger.status = "completed"
        ledger.updated_at = now
        ledger.completed_at = now
        counts = {key: int(value) for key, value in ledger.counts_json.items()}
        session.add(
            AuditEventRow(
                id=uuid4(),
                occurred_at=now,
                actor_user_id=_uuid(target.actor_user_id),
                project_id=_uuid(target.project_id),
                action="legacy_import.applied",
                entity_type="legacy_import",
                entity_id=manifest.source_fingerprint,
                payload=counts,
            )
        )
        return counts


def compare_import_parity(manifest: ImportManifest, target: LegacyImportTarget) -> dict[str, Any]:
    """Fail closed when a mapped source record or exact provenance differs."""
    losses: list[dict[str, str]] = []
    with target.database.transaction() as session:
        ledger = session.scalar(
            select(LegacyImportRow).where(
                LegacyImportRow.project_id == _uuid(target.project_id),
                LegacyImportRow.source_fingerprint == manifest.source_fingerprint,
            )
        )
        if ledger is None:
            return {"passed": False, "unexplained_losses": [{"kind": "missing_ledger"}]}
        _, mappings = _mapping_copies(ledger)
        blob_matches = 0
        for publication in manifest.publications:
            mapped = mappings["publications"].get(publication.source_id)
            row = session.get(DocumentRow, _uuid(mapped)) if mapped else None
            if row is None:
                losses.append({"kind": "publication", "source_id": publication.source_id})
            elif row.sha256 != publication.sha256:
                losses.append({"kind": "blob_hash", "source_id": publication.source_id})
            else:
                blob_matches += 1
        for run in manifest.runs:
            mapped = mappings["runs"].get(run.source_id)
            row = session.get(ResearchRunRow, _uuid(mapped)) if mapped else None
            if row is None or row.question != run.question:
                losses.append({"kind": "run", "source_id": run.source_id})
        for evidence in manifest.evidence:
            mapped = mappings["evidence"].get(evidence.source_id)
            row = session.get(EvidenceRow, _uuid(mapped)) if mapped else None
            if row is None or (
                row.statement,
                row.source_passage,
                row.section,
                row.page,
            ) != (evidence.statement, evidence.source_passage, evidence.section, evidence.page):
                losses.append({"kind": "evidence", "source_id": evidence.source_id})
        status = ledger.status
    return {
        "schema_version": 1,
        "source_fingerprint": manifest.source_fingerprint,
        "passed": status == "completed" and not losses,
        "counts": {
            name: {"source": len(source), "mapped": len(mappings[name])}
            for name, source in (
                ("publications", manifest.publications),
                ("runs", manifest.runs),
                ("evidence", manifest.evidence),
            )
        }
        | {"reviews": {"source": 0, "mapped": 0}, "artifacts": {"source": 0, "mapped": 0}},
        "blob_hashes": {"source": len(manifest.publications), "matched": blob_matches},
        "documented_transformations": [
            "legacy identifiers map to UUIDs recorded in the import ledger",
            "the supported legacy schema contains no review-revision or artifact history",
            "metadata disagreement is retained in legacy_source_variants",
        ],
        "unexplained_losses": losses,
    }


def _uuid(value: str) -> UUID:
    return UUID(value)
