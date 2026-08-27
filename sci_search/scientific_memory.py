"""Persistent cumulative scientific graph and content-addressed document cache."""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sci_search.corpus import load_corpus
from sci_search.discovery import PublicationCandidate
from sci_search.evidence_lifecycle import validate_extractive_evidence
from sci_search.profiles import PROFILES
from sci_search.question_planning import ResearchPlan


@dataclass(frozen=True, slots=True)
class MemoryAssessment:
    matching_publications: int
    cached_full_texts: int
    matched_concepts: tuple[str, ...]
    reusable_publication_ids: tuple[str, ...]


class ScientificMemory:
    """SQLite graph metadata plus immutable content-addressed source files."""

    schema_version = "scientific_memory_v2"

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.documents = self.root / "documents"
        self.documents.mkdir(exist_ok=True)
        self.database = self.root / "memory.sqlite3"
        self._initialize()

    def assess(self, plan: ResearchPlan, *, limit: int = 100) -> MemoryAssessment:
        rows = self._matching_rows(plan, limit=limit)
        matched = tuple(
            concept
            for concept in plan.concepts
            if any(_contains_concept(row["search_text"], concept, plan) for row in rows)
        )
        reusable = tuple(row["publication_id"] for row in rows if row["cache_path"])
        return MemoryAssessment(len(rows), len(reusable), matched, reusable)

    def candidates(
        self, plan: ResearchPlan, *, limit: int = 100
    ) -> tuple[PublicationCandidate, ...]:
        result: list[PublicationCandidate] = []
        for row in self._matching_rows(plan, limit=limit):
            metadata = json.loads(row["metadata_json"])
            abstract = " ".join(
                filter(
                    None,
                    (
                        str(metadata.get("abstract") or ""),
                        _memory_search_excerpt(row["search_text"], plan),
                    ),
                )
            )[:14000]
            result.append(
                PublicationCandidate(
                    id=row["publication_id"],
                    title=str(metadata.get("title") or "Untitled publication"),
                    abstract=abstract,
                    year=metadata.get("year"),
                    doi=metadata.get("doi"),
                    authors=tuple(metadata.get("authors") or ()),
                    author_ids=tuple(metadata.get("author_ids") or ()),
                    publication_type=str(metadata.get("document_type") or "article"),
                    source_url=metadata.get("source_url"),
                    document_fingerprint=str(row["download_cache_path"] or row["cache_path"] or "")
                    or None,
                    institutions=tuple(metadata.get("institutions") or ()),
                    institution_ids=tuple(metadata.get("institution_ids") or ()),
                    affiliations=tuple(metadata.get("affiliations") or ()),
                    openalex_id=metadata.get("openalex_id"),
                    pmcid=metadata.get("pmcid"),
                    cited_by_count=int(metadata.get("cited_by_count") or 0),
                    is_open_access=metadata.get("access_status") == "open_access",
                    license=metadata.get("license"),
                    has_pdf=str(row["download_cache_path"] or row["cache_path"] or "").endswith(
                        ".pdf"
                    ),
                    has_structured_fulltext=bool(row["cache_path"]),
                    has_local_fulltext=bool(row["cache_path"]),
                    providers=("scientific_memory",),
                    matched_query_ids=("query:scientific-memory",),
                    screening_reason="reusable publication from cumulative scientific memory",
                )
            )
        return tuple(result)

    def reuse_document(
        self, candidate: PublicationCandidate, corpus_directory: Path
    ) -> tuple[str, int, str] | None:
        with self._connect() as connection:
            canonical_key = _canonical_key(candidate.doi, candidate.title)
            row = connection.execute(
                "SELECT cache_path,download_cache_path FROM publications WHERE "
                "(publication_id=? OR canonical_key=? OR publication_id=(SELECT publication_id FROM publication_aliases WHERE alias_id=?)) "
                "AND cache_path IS NOT NULL LIMIT 1",
                (candidate.id, canonical_key, candidate.id),
            ).fetchone()
        if row is None:
            return None
        source = (self.root / row["cache_path"]).resolve()
        source.relative_to(self.root)
        if not source.is_file():
            return None
        target_dir = corpus_directory / "papers"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"memory-{source.name}"
        if not target.exists():
            shutil.copyfile(source, target)
        download_target = target
        if row["download_cache_path"]:
            download_source = (self.root / row["download_cache_path"]).resolve()
            download_source.relative_to(self.root)
            if download_source.is_file() and download_source != source:
                download_target = target_dir / f"memory-{download_source.name}"
                if not download_target.exists():
                    shutil.copyfile(download_source, download_target)
        return (
            target.relative_to(corpus_directory).as_posix(),
            target.stat().st_size,
            download_target.relative_to(corpus_directory).as_posix(),
        )

    def ingest_run(
        self, run_id: str, question: str, corpus_directory: Path, investigation: dict[str, Any]
    ) -> dict[str, int]:
        documents = load_corpus(corpus_directory)
        documents_by_publication = {item.publication.id: item for item in documents}
        manifest_path = corpus_directory / "manifest.json"
        manifest_payload = (
            json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
        )
        manifest_records = {
            str(item.get("id")): item
            for item in manifest_payload.get("documents", [])
            if isinstance(item, dict) and item.get("id")
        }
        added_publications = 0
        added_passages = 0
        added_claims = 0
        with self._connect() as connection:
            resolved_publication_ids: dict[str, str] = {}
            connection.execute(
                "INSERT INTO runs(run_id, question, created_at, properties_json) VALUES(?,?,?,?) "
                "ON CONFLICT(run_id) DO UPDATE SET properties_json=excluded.properties_json",
                (
                    run_id,
                    question,
                    _now(),
                    json.dumps(
                        {
                            "mode": investigation.get("mode"),
                            "corpus_id": investigation.get("corpus_id"),
                        }
                    ),
                ),
            )
            self._node(connection, f"run:{run_id}", "ResearchRun", run_id, {"question": question})
            run_details = (
                investigation.get("research_run")
                if isinstance(investigation.get("research_run"), dict)
                else {}
            )
            for candidate in (
                run_details.get("candidates", []) if isinstance(run_details, dict) else []
            ):
                if not isinstance(candidate, dict) or not candidate.get("id"):
                    continue
                requested_publication_id = str(candidate["id"])
                metadata = {
                    "title": candidate.get("title"),
                    "abstract": candidate.get("abstract"),
                    "doi": candidate.get("doi"),
                    "year": candidate.get("year"),
                    "authors": candidate.get("authors", []),
                    "author_ids": candidate.get("author_ids", []),
                    "institutions": candidate.get("institutions", []),
                    "institution_ids": candidate.get("institution_ids", []),
                    "affiliations": candidate.get("affiliations", []),
                    "document_type": candidate.get("publication_type"),
                    "source_url": candidate.get("source_url"),
                    "openalex_id": candidate.get("openalex_id"),
                    "pmcid": candidate.get("pmcid"),
                    "cited_by_count": candidate.get("cited_by_count"),
                    "license": candidate.get("license"),
                    "access_status": "open_access"
                    if candidate.get("is_open_access")
                    else "metadata_only",
                }
                canonical_key = _canonical_key(
                    metadata.get("doi"), str(metadata.get("title") or requested_publication_id)
                )
                publication_id = self._storage_publication_id(
                    connection,
                    requested_publication_id,
                    canonical_key,
                )
                resolved_publication_ids[requested_publication_id] = publication_id
                search_text = (
                    f"{metadata.get('title') or ''} {metadata.get('abstract') or ''}".lower()
                )
                existing = connection.execute(
                    "SELECT metadata_json,search_text FROM publications WHERE publication_id=?",
                    (publication_id,),
                ).fetchone()
                if existing is not None:
                    metadata = _merge_metadata(json.loads(existing["metadata_json"]), metadata)
                    search_text = _merge_search_text(str(existing["search_text"]), search_text)
                connection.execute(
                    "INSERT INTO publications(publication_id,canonical_key,metadata_json,search_text,content_sha256,cache_path,updated_at) "
                    "VALUES(?,?,?,?,NULL,NULL,?) ON CONFLICT(publication_id) DO UPDATE SET metadata_json=excluded.metadata_json, "
                    "search_text=excluded.search_text, updated_at=excluded.updated_at",
                    (
                        publication_id,
                        canonical_key,
                        json.dumps(metadata, ensure_ascii=False),
                        search_text,
                        _now(),
                    ),
                )
                self._node(
                    connection,
                    f"publication:{publication_id}",
                    "Publication",
                    canonical_key,
                    metadata,
                )
                self._edge(
                    connection,
                    f"run:{run_id}",
                    "DISCOVERED",
                    f"publication:{publication_id}",
                    {
                        "screening_status": candidate.get("screening_status"),
                        "relevance_score": candidate.get("relevance_score"),
                        "screening_reason": candidate.get("screening_reason"),
                    },
                )
                for relation in candidate.get("citation_relations", []):
                    kind, _, seed = str(relation).partition(":")
                    if not seed:
                        continue
                    seed = resolved_publication_ids.get(seed) or self._known_publication_id(
                        connection, seed
                    )
                    if kind == "cites":
                        self._edge(
                            connection,
                            f"publication:{publication_id}",
                            "CITES",
                            f"publication:{seed}",
                            {"discovered_in_run": run_id},
                        )
                    elif kind == "referenced_by":
                        self._edge(
                            connection,
                            f"publication:{seed}",
                            "CITES",
                            f"publication:{publication_id}",
                            {"discovered_in_run": run_id},
                        )
            for publication_id, decision in (
                (run_details.get("review_decisions") or {}).items()
                if isinstance(run_details, dict)
                else []
            ):
                publication_id = resolved_publication_ids.get(
                    publication_id
                ) or self._known_publication_id(connection, publication_id)
                self._edge(
                    connection,
                    f"run:{run_id}",
                    "RESEARCHER_DECISION",
                    f"publication:{publication_id}",
                    decision if isinstance(decision, dict) else {},
                )
            for document in documents:
                publication = document.publication
                source = (corpus_directory / publication.source_document).resolve()
                source.relative_to(corpus_directory.resolve())
                digest = hashlib.sha256(source.read_bytes()).hexdigest()
                suffix = source.suffix.lower() or ".txt"
                cached = self.documents / f"{digest}{suffix}"
                if not cached.exists():
                    shutil.copyfile(source, cached)
                record = manifest_records.get(publication.id, {})
                download_value = str(record.get("download_path") or publication.source_document)
                download_source = (corpus_directory / download_value).resolve()
                download_source.relative_to(corpus_directory.resolve())
                download_cached = cached
                if download_source.is_file() and download_source != source:
                    download_digest = hashlib.sha256(download_source.read_bytes()).hexdigest()
                    download_cached = (
                        self.documents
                        / f"{download_digest}{download_source.suffix.lower() or '.bin'}"
                    )
                    if not download_cached.exists():
                        shutil.copyfile(download_source, download_cached)
                metadata = {
                    "title": publication.title,
                    "doi": publication.doi,
                    "year": publication.year,
                    "authors": list(publication.authors),
                    "document_type": publication.document_type,
                    "source_url": publication.source_url,
                    "license": publication.license,
                    "access_status": publication.access_status,
                }
                canonical_key = _canonical_key(publication.doi, publication.title)
                storage_publication_id = self._storage_publication_id(
                    connection,
                    publication.id,
                    canonical_key,
                )
                resolved_publication_ids[publication.id] = storage_publication_id
                # Full-text reuse must not depend on a finding occurring near the
                # beginning of a paper. Keep a generous bounded search projection;
                # exact passages remain separately stored with provenance.
                search_text = " ".join((publication.title, document.text[:250000])).lower()
                before = connection.execute(
                    "SELECT 1 FROM publications WHERE publication_id=?", (storage_publication_id,)
                ).fetchone()
                if before is not None:
                    existing = connection.execute(
                        "SELECT metadata_json,search_text FROM publications WHERE publication_id=?",
                        (storage_publication_id,),
                    ).fetchone()
                    metadata = _merge_metadata(json.loads(existing["metadata_json"]), metadata)
                    search_text = _merge_search_text(str(existing["search_text"]), search_text)
                connection.execute(
                    "INSERT INTO publications(publication_id, canonical_key, metadata_json, search_text, content_sha256, cache_path, download_cache_path, updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(publication_id) DO UPDATE SET metadata_json=excluded.metadata_json, "
                    "search_text=excluded.search_text, content_sha256=excluded.content_sha256, cache_path=excluded.cache_path, "
                    "download_cache_path=excluded.download_cache_path, updated_at=excluded.updated_at",
                    (
                        storage_publication_id,
                        canonical_key,
                        json.dumps(metadata),
                        search_text,
                        digest,
                        cached.relative_to(self.root).as_posix(),
                        download_cached.relative_to(self.root).as_posix(),
                        _now(),
                    ),
                )
                added_publications += before is None
                connection.execute(
                    "INSERT OR REPLACE INTO run_publications(run_id, publication_id, role, properties_json) VALUES(?,?,?,?)",
                    (run_id, storage_publication_id, "evidence_source", "{}"),
                )
                self._node(
                    connection,
                    f"publication:{storage_publication_id}",
                    "Publication",
                    canonical_key,
                    metadata,
                )
                self._edge(
                    connection,
                    f"run:{run_id}",
                    "USES_EVIDENCE_FROM",
                    f"publication:{storage_publication_id}",
                    {},
                )
                for passage in document.passages():
                    passage_id = _id(
                        "passage", storage_publication_id, str(passage.start), passage.text
                    )
                    existed = connection.execute(
                        "SELECT 1 FROM passages WHERE passage_id=?", (passage_id,)
                    ).fetchone()
                    connection.execute(
                        "INSERT OR IGNORE INTO passages(passage_id, publication_id, section, page, start_offset, end_offset, text) VALUES(?,?,?,?,?,?,?)",
                        (
                            passage_id,
                            storage_publication_id,
                            passage.section,
                            passage.page,
                            passage.start,
                            passage.end,
                            passage.text,
                        ),
                    )
                    added_passages += existed is None
                    self._node(
                        connection,
                        passage_id,
                        "Passage",
                        passage_id,
                        {
                            "publication_id": storage_publication_id,
                            "section": passage.section,
                            "page": passage.page,
                            "start": passage.start,
                            "end": passage.end,
                            "text": passage.text,
                        },
                    )
                    self._edge(
                        connection,
                        f"publication:{storage_publication_id}",
                        "CONTAINS_PASSAGE",
                        passage_id,
                        {},
                    )
            for evidence in investigation.get("evidence", []):
                if not isinstance(evidence, dict):
                    continue
                evidence_id = str(evidence.get("id") or "")
                if not evidence_id:
                    continue
                if not evidence.get("validation_status"):
                    source_document = documents_by_publication.get(
                        str(evidence.get("publication_id") or "")
                    )
                    required = (
                        source_document is not None
                        and evidence.get("statement")
                        and evidence.get("passage")
                        and isinstance(evidence.get("passage_start"), int)
                        and isinstance(evidence.get("passage_end"), int)
                    )
                    if required:
                        validation = validate_extractive_evidence(
                            publication_id=str(evidence.get("publication_id")),
                            source_document=str(
                                evidence.get("source_document")
                                or source_document.publication.source_document
                            ),
                            document_text=source_document.text,
                            passage=str(evidence.get("passage")),
                            statement=str(evidence.get("statement")),
                            passage_start=int(evidence.get("passage_start")),
                            passage_end=int(evidence.get("passage_end")),
                            numerical_mentions=tuple(
                                str(item) for item in evidence.get("numerical_mentions", [])
                            ),
                            page=evidence.get("page")
                            if isinstance(evidence.get("page"), int)
                            else None,
                            extraction_method=str(
                                evidence.get("extraction_method") or "legacy_extractive_evidence"
                            ),
                        )
                        evidence = {
                            **evidence,
                            "validation_status": validation.status,
                            "review_state": validation.review_state,
                            "evidence_fingerprint": validation.evidence_fingerprint,
                            "document_sha256": validation.document_sha256,
                            "schema_version": validation.schema_version,
                            "validator_version": validation.validator_version,
                            "validation_checks": [
                                {
                                    "name": check.name,
                                    "passed": check.passed,
                                    "detail": check.detail,
                                    "severity": check.severity,
                                }
                                for check in validation.checks
                            ],
                        }
                reported_publication_id = str(evidence.get("publication_id") or "")
                storage_publication_id = resolved_publication_ids.get(
                    reported_publication_id
                ) or self._known_publication_id(
                    connection,
                    reported_publication_id,
                )
                if storage_publication_id != reported_publication_id:
                    evidence = {
                        **evidence,
                        "publication_id": storage_publication_id,
                        "reported_publication_id": reported_publication_id,
                    }
                lifecycle = self._upsert_evidence(connection, evidence)
                evidence = {**evidence, **lifecycle}
                self._node(
                    connection,
                    evidence_id,
                    "Evidence",
                    str(evidence.get("evidence_fingerprint") or evidence_id),
                    evidence,
                )
                publication_id = str(evidence.get("publication_id") or "")
                if publication_id:
                    self._edge(
                        connection,
                        f"publication:{publication_id}",
                        "PROVIDES_EVIDENCE",
                        evidence_id,
                        {},
                    )
                passage_row = connection.execute(
                    "SELECT passage_id FROM passages WHERE publication_id=? AND start_offset=? AND end_offset=?",
                    (publication_id, evidence.get("passage_start"), evidence.get("passage_end")),
                ).fetchone()
                if passage_row is not None:
                    self._edge(
                        connection,
                        evidence_id,
                        "GROUNDED_IN",
                        str(passage_row["passage_id"]),
                        {
                            "offsets_validated": lifecycle["validation_status"]
                            == "silver_source_verified",
                        },
                    )
                validation_id = f"validation:{evidence_id}:{lifecycle['validator_version']}"
                self._node(
                    connection,
                    validation_id,
                    "EvidenceValidation",
                    validation_id,
                    {
                        "status": lifecycle["validation_status"],
                        "review_state": lifecycle["review_state"],
                        "checks": lifecycle["validation_checks"],
                        "validator_version": lifecycle["validator_version"],
                        "schema_version": lifecycle["schema_version"],
                    },
                )
                self._edge(connection, evidence_id, "VALIDATED_BY", validation_id, {})
            ai = (
                investigation.get("ai_analysis")
                if isinstance(investigation.get("ai_analysis"), dict)
                else {}
            )
            for claim in ai.get("claims", []) if isinstance(ai, dict) else []:
                if not isinstance(claim, dict):
                    continue
                claim_id = str(claim.get("id") or _id("claim", str(claim)))
                self._node(connection, claim_id, "ScientificClaim", claim_id, claim)
                added_claims += 1
                for evidence_id in claim.get("evidence_ids", []):
                    self._edge(
                        connection, claim_id, "SUPPORTED_BY", str(evidence_id), {"validated": True}
                    )
                self._edge(connection, f"run:{run_id}", "PRODUCED_CLAIM", claim_id, {})
            for entity in ai.get("entities", []) if isinstance(ai, dict) else []:
                if not isinstance(entity, dict) or not entity.get("id"):
                    continue
                entity_id = str(entity["id"])
                self._node(
                    connection,
                    entity_id,
                    "ScientificEntity",
                    f"{entity.get('kind')}:{str(entity.get('normalized_label') or entity.get('label')).lower()}",
                    entity,
                )
                self._edge(
                    connection,
                    entity_id,
                    "GROUNDED_IN",
                    str(entity.get("evidence_id")),
                    {"quote_validated": True},
                )
                self._edge(connection, f"run:{run_id}", "EXTRACTED_ENTITY", entity_id, {})
            for measurement in ai.get("measurements", []) if isinstance(ai, dict) else []:
                if not isinstance(measurement, dict) or not measurement.get("id"):
                    continue
                measurement_id = str(measurement["id"])
                metric = str(measurement.get("metric") or "unknown")
                metric_id = "metric:" + hashlib.sha256(metric.lower().encode()).hexdigest()[:20]
                self._node(
                    connection, measurement_id, "MeasurementResult", measurement_id, measurement
                )
                self._node(connection, metric_id, "Metric", metric.lower(), {"name": metric})
                self._edge(connection, measurement_id, "MEASURES", metric_id, {})
                self._edge(
                    connection,
                    measurement_id,
                    "GROUNDED_IN",
                    str(measurement.get("evidence_id")),
                    {"quote_validated": True},
                )
                self._edge(connection, f"run:{run_id}", "EXTRACTED_MEASUREMENT", measurement_id, {})
            connection.commit()
        return {
            "publications_added": added_publications,
            "passages_added": added_passages,
            "claims_added": added_claims,
        }

    def stats(self) -> dict[str, int]:
        with self._connect() as connection:
            return {
                table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in (
                    "publications",
                    "passages",
                    "nodes",
                    "edges",
                    "runs",
                    "analyses",
                    "evidence_records",
                    "evidence_validation_checks",
                    "evidence_revisions",
                    "publication_aliases",
                )
            }

    def apply_lifecycle(self, investigation: dict[str, Any]) -> dict[str, Any]:
        """Overlay durable review state on newly generated evidence records."""
        evidence = investigation.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            return investigation
        ids = [
            str(item.get("id")) for item in evidence if isinstance(item, dict) and item.get("id")
        ]
        placeholders = ",".join("?" for _ in ids)
        if not placeholders:
            return investigation
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT evidence_id,validation_status,review_state,schema_version,validator_version "
                f"FROM evidence_records WHERE evidence_id IN ({placeholders})",
                ids,
            ).fetchall()
        lifecycle = {str(row["evidence_id"]): dict(row) for row in rows}
        for item in evidence:
            if isinstance(item, dict) and str(item.get("id")) in lifecycle:
                item.update(lifecycle[str(item["id"])])
        return investigation

    def evidence_states(self, evidence_ids: tuple[str, ...]) -> dict[str, dict[str, str]]:
        if not evidence_ids:
            return {}
        placeholders = ",".join("?" for _ in evidence_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT evidence_id,validation_status,review_state,schema_version,validator_version "
                f"FROM evidence_records WHERE evidence_id IN ({placeholders})",
                evidence_ids,
            ).fetchall()
        return {str(row["evidence_id"]): dict(row) for row in rows}

    def review_evidence(
        self,
        evidence_id: str,
        decision: str,
        *,
        reason: str = "",
        corrected_payload: dict[str, Any] | None = None,
        reviewer: str = "researcher",
    ) -> dict[str, Any]:
        """Append a review revision without erasing the automatic extraction."""
        states = {
            "accept": "researcher_verified",
            "needs_review": "needs_review",
            "reject": "rejected",
            "reset": "unreviewed",
        }
        if decision not in states:
            raise ValueError("decision must be accept, needs_review, reject, or reset")
        if corrected_payload is not None and not isinstance(corrected_payload, dict):
            raise ValueError("corrected_payload must be an object")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM evidence_records WHERE evidence_id=?",
                (evidence_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown evidence record: {evidence_id}")
            previous_payload = json.loads(row["payload_json"])
            current_payload = dict(previous_payload)
            if corrected_payload:
                allowed = {"statement", "evidence_type", "result_nature", "study_design"}
                unknown = set(corrected_payload) - allowed
                if unknown:
                    raise ValueError(
                        "corrected_payload contains unsupported fields: "
                        + ", ".join(sorted(unknown))
                    )
                current_payload.update(
                    {key: value for key, value in corrected_payload.items() if value is not None}
                )
            review_state = states[decision]
            current_payload["review_state"] = review_state
            revision_id = _id("revision", evidence_id, _now(), decision, reviewer)
            connection.execute(
                "INSERT INTO evidence_revisions(revision_id,evidence_id,decision,reviewer,reason,previous_payload_json,new_payload_json,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    revision_id,
                    evidence_id,
                    decision,
                    reviewer[:200],
                    reason.strip()[:2000],
                    json.dumps(previous_payload, ensure_ascii=False),
                    json.dumps(current_payload, ensure_ascii=False),
                    _now(),
                ),
            )
            connection.execute(
                "UPDATE evidence_records SET review_state=?,payload_json=?,updated_at=? WHERE evidence_id=?",
                (
                    review_state,
                    json.dumps(current_payload, ensure_ascii=False),
                    _now(),
                    evidence_id,
                ),
            )
            self._node(
                connection,
                revision_id,
                "EvidenceRevision",
                revision_id,
                {
                    "decision": decision,
                    "reviewer": reviewer[:200],
                    "reason": reason.strip()[:2000],
                    "corrected_fields": sorted(corrected_payload or {}),
                },
            )
            self._edge(connection, revision_id, "REVISES", evidence_id, {})
            self._node(
                connection,
                evidence_id,
                "Evidence",
                str(row["evidence_fingerprint"]),
                current_payload,
            )
            connection.commit()
        return self.evidence_record(evidence_id)

    def evidence_record(self, evidence_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM evidence_records WHERE evidence_id=?", (evidence_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown evidence record: {evidence_id}")
            checks = connection.execute(
                "SELECT check_name,passed,severity,detail FROM evidence_validation_checks "
                "WHERE evidence_id=? ORDER BY check_name",
                (evidence_id,),
            ).fetchall()
            revisions = connection.execute(
                "SELECT revision_id,decision,reviewer,reason,created_at FROM evidence_revisions "
                "WHERE evidence_id=? ORDER BY created_at",
                (evidence_id,),
            ).fetchall()
        payload = json.loads(row["payload_json"])
        payload.update(
            {
                "validation_status": row["validation_status"],
                "review_state": row["review_state"],
                "schema_version": row["schema_version"],
                "validator_version": row["validator_version"],
                "evidence_fingerprint": row["evidence_fingerprint"],
                "document_sha256": row["document_sha256"],
                "validation_checks": [
                    {
                        "name": item["check_name"],
                        "passed": bool(item["passed"]),
                        "severity": item["severity"],
                        "detail": item["detail"],
                    }
                    for item in checks
                ],
                "revisions": [dict(item) for item in revisions],
            }
        )
        return payload

    def graph_snapshot(self, *, limit: int = 500) -> dict[str, Any]:
        """Return a bounded, read-only projection for inspection and export."""
        bounded = max(1, min(int(limit), 5_000))
        with self._connect() as connection:
            node_rows = connection.execute(
                "SELECT node_id,node_type,canonical_key,properties_json FROM nodes "
                "ORDER BY updated_at DESC,node_id LIMIT ?",
                (bounded,),
            ).fetchall()
            edge_rows = connection.execute(
                "SELECT e.edge_id,e.source_id,e.relation_type,e.target_id,e.properties_json FROM edges e "
                "JOIN (SELECT node_id FROM nodes ORDER BY updated_at DESC,node_id LIMIT ?) selected "
                "ON e.source_id=selected.node_id OR e.target_id=selected.node_id "
                "ORDER BY e.edge_id LIMIT ?",
                (bounded, bounded),
            ).fetchall()
        return {
            "schema_version": self.schema_version,
            "bounded": True,
            "limit": bounded,
            "stats": self.stats(),
            "nodes": [
                {
                    "id": row["node_id"],
                    "type": row["node_type"],
                    "canonical_key": row["canonical_key"],
                    "properties": json.loads(row["properties_json"]),
                }
                for row in node_rows
            ],
            "edges": [
                {
                    "id": row["edge_id"],
                    "source": row["source_id"],
                    "relation": row["relation_type"],
                    "target": row["target_id"],
                    "properties": json.loads(row["properties_json"]),
                }
                for row in edge_rows
            ],
        }

    def cached_analysis(self, cache_key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM analyses WHERE cache_key=?", (cache_key,)
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload_json"])
        payload["cache_hit"] = True
        return payload

    def cache_analysis(self, cache_key: str, payload: dict[str, Any]) -> None:
        if payload.get("status") != "complete":
            return
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO analyses(cache_key,payload_json,created_at) VALUES(?,?,?)",
                (cache_key, json.dumps(payload, ensure_ascii=False), _now()),
            )
            connection.commit()

    def bootstrap_runs(self, research_runs_root: Path) -> dict[str, int]:
        imported = 0
        skipped = 0
        failed = 0
        existing: set[str]
        with self._connect() as connection:
            existing = {str(row[0]) for row in connection.execute("SELECT run_id FROM runs")}
        if not research_runs_root.is_dir():
            return {"imported": 0, "skipped": 0, "failed": 0}
        for run_directory in sorted(research_runs_root.iterdir()):
            if not run_directory.is_dir():
                continue
            investigation_path = run_directory / "investigation.json"
            corpus = run_directory / "corpus"
            if not investigation_path.is_file() or not (corpus / "manifest.json").is_file():
                skipped += 1
                continue
            try:
                payload = json.loads(investigation_path.read_text(encoding="utf-8"))
                evidence_ids = tuple(
                    str(item.get("id"))
                    for item in payload.get("evidence", [])
                    if isinstance(item, dict) and item.get("id")
                )
                if run_directory.name in existing and not self._missing_evidence_records(
                    evidence_ids
                ):
                    skipped += 1
                    continue
                question = str(payload.get("question") or "").strip()
                if not question:
                    raise ValueError("run has no completed investigation corpus")
                self.ingest_run(run_directory.name, question, corpus, payload)
                imported += 1
            except (OSError, ValueError, KeyError, json.JSONDecodeError, sqlite3.Error):
                failed += 1
        return {"imported": imported, "skipped": skipped, "failed": failed}

    def bootstrap_corpus(self, corpus: Path, *, corpus_id: str | None = None) -> dict[str, int]:
        """Make an existing curated corpus reusable by future online research runs."""
        resolved = corpus.resolve()
        identifier = corpus_id or resolved.name
        payload = {
            "mode": "curated_corpus_bootstrap",
            "corpus_id": identifier,
            "research_run": {"candidates": []},
            "evidence": [],
        }
        return self.ingest_run(
            "curated:" + hashlib.sha256(str(resolved).encode()).hexdigest()[:20],
            f"Curated scientific corpus: {identifier}",
            resolved,
            payload,
        )

    def _missing_evidence_records(self, evidence_ids: tuple[str, ...]) -> bool:
        if not evidence_ids:
            return False
        placeholders = ",".join("?" for _ in evidence_ids)
        with self._connect() as connection:
            present = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM evidence_records WHERE evidence_id IN ({placeholders})",
                    evidence_ids,
                ).fetchone()[0]
            )
        return present < len(set(evidence_ids))

    def _matching_rows(self, plan: ResearchPlan, *, limit: int) -> list[sqlite3.Row]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT publication_id, metadata_json, search_text, cache_path, download_cache_path FROM publications ORDER BY updated_at DESC"
            ).fetchall()
        scored = []
        minimum = (
            len(plan.concepts) if len(plan.concepts) <= 2 else math.ceil(len(plan.concepts) * 0.5)
        )
        for row in rows:
            coverage = sum(
                _contains_concept(row["search_text"], concept, plan) for concept in plan.concepts
            )
            if coverage >= minimum:
                scored.append((coverage, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [row for _, row in scored[:limit]]

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS publications(
                    publication_id TEXT PRIMARY KEY, canonical_key TEXT UNIQUE NOT NULL, metadata_json TEXT NOT NULL,
                    search_text TEXT NOT NULL, content_sha256 TEXT, cache_path TEXT, download_cache_path TEXT, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS publication_aliases(
                    alias_id TEXT PRIMARY KEY, publication_id TEXT NOT NULL REFERENCES publications(publication_id),
                    canonical_key TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS passages(
                    passage_id TEXT PRIMARY KEY, publication_id TEXT NOT NULL REFERENCES publications(publication_id),
                    section TEXT NOT NULL, page INTEGER, start_offset INTEGER, end_offset INTEGER, text TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, question TEXT NOT NULL, created_at TEXT NOT NULL, properties_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS run_publications(
                    run_id TEXT NOT NULL REFERENCES runs(run_id), publication_id TEXT NOT NULL REFERENCES publications(publication_id),
                    role TEXT NOT NULL, properties_json TEXT NOT NULL, PRIMARY KEY(run_id,publication_id,role));
                CREATE TABLE IF NOT EXISTS nodes(node_id TEXT PRIMARY KEY, node_type TEXT NOT NULL, canonical_key TEXT, properties_json TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS edges(edge_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, relation_type TEXT NOT NULL, target_id TEXT NOT NULL, properties_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS analyses(cache_key TEXT PRIMARY KEY, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS evidence_records(
                    evidence_id TEXT PRIMARY KEY, publication_id TEXT NOT NULL, evidence_fingerprint TEXT NOT NULL,
                    document_sha256 TEXT NOT NULL, validation_status TEXT NOT NULL, review_state TEXT NOT NULL,
                    schema_version TEXT NOT NULL, validator_version TEXT NOT NULL, extraction_method TEXT NOT NULL,
                    payload_json TEXT NOT NULL, first_seen_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS evidence_validation_checks(
                    evidence_id TEXT NOT NULL REFERENCES evidence_records(evidence_id), check_name TEXT NOT NULL,
                    validator_version TEXT NOT NULL, passed INTEGER NOT NULL, severity TEXT NOT NULL, detail TEXT NOT NULL,
                    checked_at TEXT NOT NULL, PRIMARY KEY(evidence_id,check_name,validator_version));
                CREATE TABLE IF NOT EXISTS evidence_revisions(
                    revision_id TEXT PRIMARY KEY, evidence_id TEXT NOT NULL REFERENCES evidence_records(evidence_id),
                    decision TEXT NOT NULL, reviewer TEXT NOT NULL, reason TEXT NOT NULL,
                    previous_payload_json TEXT NOT NULL, new_payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(node_type);
                CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
                CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
                CREATE INDEX IF NOT EXISTS idx_evidence_publication ON evidence_records(publication_id);
                CREATE INDEX IF NOT EXISTS idx_evidence_status ON evidence_records(validation_status,review_state);
                CREATE INDEX IF NOT EXISTS idx_publication_alias_target ON publication_aliases(publication_id);
            """)
            columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(publications)")}
            if "download_cache_path" not in columns:
                connection.execute("ALTER TABLE publications ADD COLUMN download_cache_path TEXT")

    @staticmethod
    def _storage_publication_id(
        connection: sqlite3.Connection,
        requested_id: str,
        canonical_key: str,
    ) -> str:
        """Return the one stored publication for an identifier/canonical work pair."""
        direct = connection.execute(
            "SELECT publication_id FROM publications WHERE publication_id=?",
            (requested_id,),
        ).fetchone()
        if direct is not None:
            return str(direct["publication_id"])
        alias = connection.execute(
            "SELECT publication_id FROM publication_aliases WHERE alias_id=?",
            (requested_id,),
        ).fetchone()
        if alias is not None:
            return str(alias["publication_id"])
        canonical = connection.execute(
            "SELECT publication_id FROM publications WHERE canonical_key=?",
            (canonical_key,),
        ).fetchone()
        if canonical is None:
            return requested_id
        storage_id = str(canonical["publication_id"])
        connection.execute(
            "INSERT OR REPLACE INTO publication_aliases(alias_id,publication_id,canonical_key,created_at) VALUES(?,?,?,?)",
            (requested_id, storage_id, canonical_key, _now()),
        )
        return storage_id

    @staticmethod
    def _known_publication_id(connection: sqlite3.Connection, requested_id: str) -> str:
        alias = connection.execute(
            "SELECT publication_id FROM publication_aliases WHERE alias_id=?",
            (requested_id,),
        ).fetchone()
        return str(alias["publication_id"]) if alias is not None else requested_id

    def _upsert_evidence(
        self, connection: sqlite3.Connection, evidence: dict[str, Any]
    ) -> dict[str, Any]:
        evidence_id = str(evidence["id"])
        validation_status = str(evidence.get("validation_status") or "unvalidated")
        schema_version = str(evidence.get("schema_version") or "generic_evidence_v1")
        validator_version = str(evidence.get("validator_version") or "none")
        fingerprint = str(
            evidence.get("evidence_fingerprint") or _id("fingerprint", evidence_id, schema_version)
        )
        document_sha = str(evidence.get("document_sha256") or "unknown")
        existing = connection.execute(
            "SELECT review_state,evidence_fingerprint,payload_json FROM evidence_records WHERE evidence_id=?",
            (evidence_id,),
        ).fetchone()
        same_version = existing is not None and str(existing["evidence_fingerprint"]) == fingerprint
        review_state = (
            str(existing["review_state"])
            if same_version
            else (
                "needs_review"
                if existing is not None
                else str(evidence.get("review_state") or "unreviewed")
            )
        )
        checks = (
            evidence.get("validation_checks")
            if isinstance(evidence.get("validation_checks"), list)
            else []
        )
        payload = {**evidence, "review_state": review_state}
        if same_version and review_state != "unreviewed":
            reviewed_payload = json.loads(existing["payload_json"])
            for field in ("statement", "evidence_type", "result_nature", "study_design"):
                if field in reviewed_payload:
                    payload[field] = reviewed_payload[field]
        now = _now()
        connection.execute(
            "INSERT INTO evidence_records(evidence_id,publication_id,evidence_fingerprint,document_sha256,validation_status,review_state,"
            "schema_version,validator_version,extraction_method,payload_json,first_seen_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(evidence_id) DO UPDATE SET publication_id=excluded.publication_id,evidence_fingerprint=excluded.evidence_fingerprint,"
            "document_sha256=excluded.document_sha256,validation_status=excluded.validation_status,schema_version=excluded.schema_version,"
            "validator_version=excluded.validator_version,extraction_method=excluded.extraction_method,payload_json=excluded.payload_json,updated_at=excluded.updated_at",
            (
                evidence_id,
                str(evidence.get("publication_id") or "unknown"),
                fingerprint,
                document_sha,
                validation_status,
                review_state,
                schema_version,
                validator_version,
                str(evidence.get("extraction_method") or "unknown"),
                json.dumps(payload, ensure_ascii=False),
                now,
                now,
            ),
        )
        for check in checks:
            if not isinstance(check, dict) or not check.get("name"):
                continue
            connection.execute(
                "INSERT OR REPLACE INTO evidence_validation_checks(evidence_id,check_name,validator_version,passed,severity,detail,checked_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    evidence_id,
                    str(check["name"]),
                    validator_version,
                    int(bool(check.get("passed"))),
                    str(check.get("severity") or "error"),
                    str(check.get("detail") or ""),
                    now,
                ),
            )
        return {
            "validation_status": validation_status,
            "review_state": review_state,
            "schema_version": schema_version,
            "validator_version": validator_version,
            "evidence_fingerprint": fingerprint,
            "document_sha256": document_sha,
            "validation_checks": checks,
        }

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _node(
        connection: sqlite3.Connection,
        node_id: str,
        node_type: str,
        canonical_key: str,
        properties: dict[str, Any],
    ) -> None:
        connection.execute(
            "INSERT INTO nodes(node_id,node_type,canonical_key,properties_json,updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(node_id) DO UPDATE SET properties_json=excluded.properties_json, updated_at=excluded.updated_at",
            (node_id, node_type, canonical_key, json.dumps(properties, ensure_ascii=False), _now()),
        )

    @staticmethod
    def _edge(
        connection: sqlite3.Connection,
        source: str,
        relation: str,
        target: str,
        properties: dict[str, Any],
    ) -> None:
        edge_id = _id("edge", source, relation, target)
        connection.execute(
            "INSERT OR REPLACE INTO edges(edge_id,source_id,relation_type,target_id,properties_json) VALUES(?,?,?,?,?)",
            (edge_id, source, relation, target, json.dumps(properties, ensure_ascii=False)),
        )


def _contains(text: str, term: str) -> bool:
    expected = re.findall(r"[a-z0-9]+", term.lower())
    available = re.findall(r"[a-z0-9]+", text.lower())
    return bool(expected) and all(
        any(_inflection_match(token, value) for value in available) for token in expected
    )


def _contains_concept(text: str, concept: str, plan: ResearchPlan) -> bool:
    return any(_contains(text, alias) for alias in PROFILES[plan.profile_id].expand(concept))


def _memory_search_excerpt(text: str, plan: ResearchPlan, *, radius: int = 1200) -> str:
    """Expose compact concept-bearing windows to the normal screening pipeline."""
    windows = [text[:1200]]
    for concept in plan.concepts:
        for alias in PROFILES[plan.profile_id].expand(concept):
            tokens = re.findall(r"[a-z0-9]+", alias.casefold())
            if not tokens:
                continue
            match = re.search(
                r"(?<![a-z0-9])" + r"[^a-z0-9]+".join(map(re.escape, tokens)) + r"(?![a-z0-9])",
                text.casefold(),
            )
            if match:
                windows.append(text[max(0, match.start() - radius) : match.end() + radius])
                break
    return " … ".join(dict.fromkeys(windows))[:10000]


def _inflection_match(left: str, right: str) -> bool:
    if left == right:
        return True
    variants = {left, right}
    normalized = set()
    for value in variants:
        if value.endswith("ies") and len(value) > 4:
            normalized.add(value[:-3] + "y")
        elif value.endswith("s") and len(value) > 4:
            normalized.add(value[:-1])
        else:
            normalized.add(value)
    return len(normalized) == 1


def _canonical_key(doi: str | None, title: str) -> str:
    return (
        "doi:" + doi.lower()
        if doi
        else "title:" + re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    )


def _merge_metadata(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge provider aliases without replacing useful metadata with blanks."""
    merged = dict(existing)
    for key, value in incoming.items():
        if value not in (None, "", [], ()):
            if (
                key == "access_status"
                and merged.get(key) == "open_access"
                and value == "metadata_only"
            ):
                continue
            merged[key] = value
    return merged


def _merge_search_text(existing: str, incoming: str, *, limit: int = 250_000) -> str:
    existing = existing.strip()
    incoming = incoming.strip()
    if not incoming or incoming in existing:
        return existing[:limit]
    if not existing:
        return incoming[:limit]
    return f"{existing} {incoming}"[:limit]


def _id(prefix: str, *parts: str) -> str:
    return prefix + ":" + hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:24]


def _now() -> str:
    return datetime.now(UTC).isoformat()
