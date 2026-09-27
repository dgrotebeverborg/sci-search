"""Persistent question-to-corpus research runs for online scientific search."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import mimetypes
import os
import re
import threading
import traceback
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sci_search.configuration import require_openalex_key
from sci_search.corpus import load_corpus
from sci_search.coverage import coverage_follow_up_queries, gate_model_analysis
from sci_search.discovery import (
    PublicationCandidate,
    SearchQuery,
    merge_candidates,
    screen_candidates,
)
from sci_search.fulltext_acquisition import AcquisitionOutcome, acquire_full_text
from sci_search.fulltext_screening import screen_acquired_documents
from sci_search.generic_research import GenericResearchEngine
from sci_search.literature_review import (
    build_literature_review,
    render_review_html,
    render_review_json,
    render_review_markdown,
    render_review_pdf,
)
from sci_search.mistral_analysis import MistralAnalyzer, analyze_if_configured
from sci_search.models import dataclass_to_dict
from sci_search.question_planning import ResearchPlan, plan_question
from sci_search.research.stages.acquisition import AcquisitionStage
from sci_search.research.stages.analysis import AnalysisStage
from sci_search.research.stages.base import StageContext
from sci_search.research.stages.discovery import DiscoveryStage
from sci_search.research.stages.planning import PlanningStage
from sci_search.research.stages.reporting import ReportingStage
from sci_search.research_landscape import build_research_landscape
from sci_search.scholarly_providers import (
    CrossrefProvider,
    DiscoveryProvider,
    EuropePmcProvider,
    OpenAlexProvider,
    discover_with_providers,
    expand_citation_network,
)
from sci_search.scientific_memory import ScientificMemory
from sci_search.study_matrix import (
    active_from_screening,
    adjudicate_uncertain_studies,
    apply_adjudication,
    build_study_matrix,
)
from sci_search.synthesis import build_structured_synthesis

Acquirer = Callable[[PublicationCandidate, Path], AcquisitionOutcome]

REVIEW_PROFILES: dict[str, dict[str, int]] = {
    "quick": {
        "initial": 10,
        "maximum": 10,
        "batch": 10,
        "attempts": 25,
        "per_query": 30,
        "selected": 40,
        "seeds": 1,
        "neighbors": 4,
    },
    "research": {
        "initial": 25,
        "maximum": 50,
        "batch": 10,
        "attempts": 100,
        "per_query": 100,
        "selected": 100,
        "seeds": 3,
        "neighbors": 8,
    },
    "deep": {
        "initial": 25,
        "maximum": 100,
        "batch": 15,
        "attempts": 200,
        "per_query": 100,
        "selected": 100,
        "seeds": 5,
        "neighbors": 12,
    },
}


@dataclass(frozen=True, slots=True)
class ResearchLimits:
    per_query: int = 100
    max_selected: int = 100
    max_full_texts: int = 50
    max_acquisition_attempts: int = 100
    citation_seed_count: int = 3
    citation_neighbors_per_seed: int = 8
    citation_depth: int = 1
    review_mode: str = "research"
    initial_full_texts: int = 25
    acquisition_batch_size: int = 10
    saturation_patience: int = 2

    def __post_init__(self) -> None:
        if not 1 <= self.per_query <= 100:
            raise ValueError("per_query must be between 1 and 100")
        if not 1 <= self.max_selected <= 100:
            raise ValueError("max_selected must be between 1 and 100")
        if not 1 <= self.max_full_texts <= 100:
            raise ValueError("max_full_texts must be between 1 and 100")
        if self.max_acquisition_attempts < self.max_full_texts:
            raise ValueError("max_acquisition_attempts cannot be below max_full_texts")
        if self.max_acquisition_attempts > 200:
            raise ValueError("max_acquisition_attempts must not exceed 200")
        if not 0 <= self.citation_seed_count <= 10:
            raise ValueError("citation_seed_count must be between 0 and 10")
        if not 0 <= self.citation_neighbors_per_seed <= 100:
            raise ValueError("citation_neighbors_per_seed must be between 0 and 100")
        if not 0 <= self.citation_depth <= 2:
            raise ValueError("citation_depth must be between 0 and 2")
        if self.review_mode not in {"quick", "research", "deep", "custom"}:
            raise ValueError("review_mode must be quick, research, deep, or custom")
        if not 1 <= self.initial_full_texts <= 100:
            raise ValueError("initial_full_texts must be between 1 and 100")
        if not 1 <= self.acquisition_batch_size <= 50:
            raise ValueError("acquisition_batch_size must be between 1 and 50")
        if not 1 <= self.saturation_patience <= 5:
            raise ValueError("saturation_patience must be between 1 and 5")


@dataclass(frozen=True, slots=True)
class DownloadPayload:
    filename: str
    content_type: str
    body: bytes


class ResearchRunManager:
    def __init__(
        self,
        root: Path,
        *,
        providers: tuple[DiscoveryProvider, ...] | None = None,
        acquirer: Acquirer | None = None,
        openalex_api_key: str | None = None,
        memory: ScientificMemory | None = None,
        analyzer: MistralAnalyzer | None = None,
    ) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.openalex_api_key = openalex_api_key or require_openalex_key()
        email = os.environ.get("CROSSREF_EMAIL") or os.environ.get("UNPAYWALL_EMAIL")
        self.providers = providers or (
            OpenAlexProvider(self.openalex_api_key),
            EuropePmcProvider(),
            CrossrefProvider(email=email),
        )
        self.acquirer = acquirer or (
            lambda candidate, corpus: acquire_full_text(
                candidate,
                corpus,
                openalex_api_key=self.openalex_api_key,
            )
        )
        self.memory = memory
        self.analyzer = analyzer
        self._states: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def run_sync(
        self,
        question: str,
        *,
        limits: ResearchLimits | None = None,
        question_brief: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cleaned = " ".join(question.strip().split())
        if not cleaned:
            raise ValueError("question is required")
        selected_limits = limits or ResearchLimits()
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        self._set_state(
            run_id, self._new_state(run_id, cleaned, selected_limits, question_brief=question_brief)
        )
        self._execute_guarded(run_id, cleaned, selected_limits)
        return self.get(run_id)

    def get(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            state = self._states.get(run_id)
        if state is None:
            path = self.root / run_id / "run.json"
            if not path.is_file():
                raise KeyError(f"unknown research run: {run_id}")
            state = json.loads(path.read_text(encoding="utf-8"))
            with self._lock:
                self._states[run_id] = state
        return json.loads(json.dumps(state))

    def full_text(self, run_id: str, publication_id: str) -> dict[str, object]:
        run_directory = self._run_directory(run_id)
        corpus_directory = run_directory / "corpus"
        documents = load_corpus(corpus_directory)
        document = next((item for item in documents if item.publication.id == publication_id), None)
        if document is None:
            raise KeyError(f"unknown publication in research run: {publication_id}")
        return {
            "publication_id": publication_id,
            "title": document.publication.title,
            "source_document": document.publication.source_document,
            "content": document.text,
            "fixture_status": None,
            "corpus_id": f"research:{run_id}",
        }

    def download_publication(self, run_id: str, publication_id: str) -> DownloadPayload:
        corpus, record, path = self._active_document(run_id, publication_id, for_download=True)
        body = path.read_bytes()
        if len(body) > 50_000_000:
            raise ValueError("publication exceeds the 50 MB download limit")
        suffix = path.suffix.lower() or ".txt"
        filename = _download_name(str(record.get("title") or publication_id), suffix)
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return DownloadPayload(filename, content_type, body)

    def download_publications(
        self, run_id: str, publication_ids: list[str] | None = None, *, allow_empty: bool = False
    ) -> DownloadPayload:
        state = self.get(run_id)
        if state.get("status") == "complete" and not state.get("full_text_screening"):
            self._rebuild_evidence(run_id)
        run_directory = self._run_directory(run_id)
        corpus = run_directory / "corpus"
        manifest_path = corpus / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        records = [item for item in manifest.get("documents", []) if isinstance(item, dict)]
        requested = tuple(dict.fromkeys(str(item) for item in (publication_ids or []) if str(item)))
        if requested:
            known = {str(item.get("id")) for item in records}
            missing = [item for item in requested if item not in known]
            if missing:
                raise KeyError(f"publication is not in the active evidence corpus: {missing[0]}")
            records = [item for item in records if str(item.get("id")) in requested]
        if not records and not allow_empty:
            raise ValueError("no acquired publications are available to download")
        buffer = io.BytesIO()
        bundle_records: list[dict[str, Any]] = []
        total = 0
        used_names: set[str] = set()
        with zipfile.ZipFile(
            buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archive:
            for record in records:
                publication_id = str(record.get("id"))
                _, _, path = self._active_document(run_id, publication_id, for_download=True)
                body = path.read_bytes()
                total += len(body)
                if total > 250_000_000:
                    raise ValueError("selected publications exceed the 250 MB bundle limit")
                name = _download_name(
                    str(record.get("title") or publication_id), path.suffix.lower() or ".txt"
                )
                if name in used_names:
                    name = _download_name(
                        f"{record.get('title')} {publication_id[-8:]}",
                        path.suffix.lower() or ".txt",
                    )
                used_names.add(name)
                archive.writestr(f"publications/{name}", body)
                bundle_records.append(
                    {
                        "publication_id": publication_id,
                        "title": record.get("title"),
                        "doi": record.get("doi"),
                        "year": record.get("year"),
                        "authors": record.get("authors", []),
                        "source_url": record.get("source_url"),
                        "access_status": record.get("access_status"),
                        "license": record.get("license"),
                        "downloaded_filename": f"publications/{name}",
                        "download_source": record.get("download_source"),
                        "analysis_document": record.get("path"),
                    }
                )
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "run_id": run_id,
                        "question": manifest.get("corpus_name"),
                        "created_at": _now(),
                        "publication_count": len(bundle_records),
                        "documents": bundle_records,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
            )
            archive.writestr(
                "README.txt",
                "Sci-Search evidence-corpus export\n\nDocuments retain their original local format. See manifest.json for source, access, licence, and DOI metadata. Inclusion in this archive is not a transfer of copyright or a claim that every document may be redistributed.\n",
            )
        return DownloadPayload(
            f"sci-search-{run_id}-{len(records)}-publications.zip",
            "application/zip",
            buffer.getvalue(),
        )

    def download_literature_review(
        self, run_id: str, output_format: str = "html"
    ) -> DownloadPayload:
        if output_format not in {"html", "markdown", "json", "pdf"}:
            raise ValueError("literature review format must be html, markdown, json, or pdf")
        state = self.get(run_id)
        if state.get("status") != "complete":
            raise ValueError("research run is not complete")
        if not state.get("full_text_screening"):
            self._rebuild_evidence(run_id)
        investigation = json.loads(
            (self._run_directory(run_id) / "investigation.json").read_text(encoding="utf-8")
        )
        report = build_literature_review(investigation)
        if output_format == "json":
            return DownloadPayload(
                f"sci-search-{run_id}-literature-review.json",
                "application/json",
                render_review_json(report).encode(),
            )
        if output_format == "markdown":
            return DownloadPayload(
                f"sci-search-{run_id}-literature-review.md",
                "text/markdown; charset=utf-8",
                render_review_markdown(report).encode(),
            )
        if output_format == "pdf":
            return DownloadPayload(
                f"sci-search-{run_id}-literature-review.pdf",
                "application/pdf",
                render_review_pdf(report),
            )
        return DownloadPayload(
            f"sci-search-{run_id}-literature-review.html",
            "text/html; charset=utf-8",
            render_review_html(report).encode(),
        )

    def download_research_package(self, run_id: str) -> DownloadPayload:
        """Bundle every acquired original artifact with the complete review."""
        state = self.get(run_id)
        if state.get("status") != "complete":
            raise ValueError("research run is not complete")
        if not state.get("full_text_screening"):
            self._rebuild_evidence(run_id)
            state = self.get(run_id)
        publications = self.download_publications(run_id, allow_empty=True)
        run_directory = self._run_directory(run_id)
        investigation = json.loads(
            (run_directory / "investigation.json").read_text(encoding="utf-8")
        )
        report = build_literature_review(investigation)
        landscape = report.get("research_landscape") or build_research_landscape(investigation)
        output = io.BytesIO()
        with (
            zipfile.ZipFile(io.BytesIO(publications.body), "r") as source,
            zipfile.ZipFile(
                output,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
            ) as archive,
        ):
            for entry in source.infolist():
                if entry.filename == "README.txt":
                    continue
                target = (
                    "data/publications-manifest.json"
                    if entry.filename == "manifest.json"
                    else entry.filename
                )
                archive.writestr(target, source.read(entry.filename))
            archive.writestr("literature-review.pdf", render_review_pdf(report))
            archive.writestr("literature-review.html", render_review_html(report).encode("utf-8"))
            archive.writestr("literature-review.md", render_review_markdown(report).encode("utf-8"))
            archive.writestr(
                "data/literature-review.json", render_review_json(report).encode("utf-8")
            )
            archive.writestr(
                "data/research-landscape.json",
                (json.dumps(landscape, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
            )
            archive.writestr(
                "data/full-text-screening.json",
                (
                    json.dumps(state.get("full_text_screening") or [], indent=2, ensure_ascii=False)
                    + "\n"
                ).encode("utf-8"),
            )
            archive.writestr(
                "data/study-matrix.json",
                (
                    json.dumps(state.get("study_matrix") or {}, indent=2, ensure_ascii=False) + "\n"
                ).encode("utf-8"),
            )
            archive.writestr(
                "data/research-run.json",
                (json.dumps(state, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
            )
            archive.writestr(
                "README.txt",
                (
                    b"SCI-SEARCH RESEARCH PACKAGE\n\n"
                    b"Start with literature-review.pdf. It contains the cited synthesis, methods, selection flow, "
                    b"research landscape, limitations, references, and exact evidence passages.\n\n"
                    b"The publications/ directory contains every included full-text artifact in its "
                    b"best retained original format. This may be publisher PDF, JATS/XML, plain text, or an authorized "
                    b"researcher-supplied file. data/publications-manifest.json records the source and format of each file. "
                    b"data/full-text-screening.json retains all post-acquisition inclusion and exclusion decisions.\n\n"
                    b"Landscape counts describe the discovered metadata ledger and can exceed the number of included "
                    b"full texts. This AI-assisted cited evidence review is not labelled a systematic review.\n\n"
                    b"Documents remain subject to their original licences and copyright.\n"
                ),
            )
        return DownloadPayload(
            f"sci-search-{run_id}-complete-research-package.zip",
            "application/zip",
            output.getvalue(),
        )

    def _active_document(
        self, run_id: str, publication_id: str, *, for_download: bool = False
    ) -> tuple[Path, dict[str, Any], Path]:
        corpus = self._run_directory(run_id) / "corpus"
        manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
        record = next(
            (
                item
                for item in manifest.get("documents", [])
                if isinstance(item, dict) and str(item.get("id")) == publication_id
            ),
            None,
        )
        if record is None:
            raise KeyError(f"publication is not in the active evidence corpus: {publication_id}")
        selected_path = record.get("download_path") if for_download else record.get("path")
        path = (corpus / str(selected_path or record.get("path") or "")).resolve()
        try:
            path.relative_to(corpus.resolve())
        except ValueError as exc:
            raise ValueError("publication path falls outside the research corpus") from exc
        if not path.is_file():
            raise FileNotFoundError(str(selected_path or record.get("path") or ""))
        return corpus, record, path

    def investigate(
        self,
        run_id: str,
        question: str,
        *,
        question_brief: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = self.get(run_id)
        if state.get("status") != "complete":
            raise ValueError("research run is not complete")
        original_question = str(state.get("question") or "")
        current_plan = plan_question(question)
        contextualized = question
        if current_plan.profile_id == "generic" or len(current_plan.concepts) < 2:
            contextualized = f"{question} {original_question}"
        corpus_directory = self._run_directory(run_id) / "corpus"
        report = GenericResearchEngine(
            load_corpus(corpus_directory),
            lifecycle_lookup=self.memory.evidence_states if self.memory is not None else None,
        ).investigate(
            contextualized,
            session_id=f"research:{run_id}",
        )
        payload = report.to_dict()
        if self.memory is not None:
            self.memory.apply_lifecycle(payload)
        payload["synthesis"] = build_structured_synthesis(payload)
        raw_adequacy = payload.get("answer_adequacy")
        adequacy = raw_adequacy if isinstance(raw_adequacy, dict) else {}
        answer_ids = {str(item) for item in adequacy.get("answer_evidence_ids", []) if str(item)}
        raw_evidence = payload.get("evidence")
        evidence_records = raw_evidence if isinstance(raw_evidence, list) else []
        answer_evidence = [
            item
            for item in evidence_records
            if isinstance(item, dict) and str(item.get("id")) in answer_ids
        ]
        payload["ai_analysis"] = gate_model_analysis(
            self._analyze(question, answer_evidence, adequacy),
            adequacy,
        )
        payload["question"] = question
        payload["contextualized_question"] = contextualized if contextualized != question else None
        payload["question_history"] = [original_question, question]
        payload["corpus_id"] = f"research:{run_id}"
        payload["question_brief"] = question_brief or state.get("question_brief")
        original_result = state.get("result") if isinstance(state.get("result"), dict) else {}
        payload["research_run"] = original_result.get("research_run")
        if self.memory is not None:
            followup_key = hashlib.sha256(
                f"{run_id}\x1f{question.strip().lower()}".encode()
            ).hexdigest()[:16]
            payload["memory_update"] = self.memory.ingest_run(
                f"{run_id}:followup:{followup_key}",
                question,
                corpus_directory,
                payload,
            )
            payload["memory_stats"] = self.memory.stats()
        payload["research_landscape"] = build_research_landscape(payload)
        payload["literature_review_report"] = build_literature_review(payload)
        return payload

    def review_candidate(
        self, run_id: str, candidate_id: str, decision: str, reason: str = ""
    ) -> dict[str, Any]:
        if decision not in {"include", "background", "exclude", "reset"}:
            raise ValueError("decision must be include, background, exclude, or reset")
        state = self.get(run_id)
        if state.get("status") != "complete":
            raise ValueError("research run is not complete")
        if candidate_id not in {str(item.get("id")) for item in state.get("candidates", [])}:
            raise KeyError(f"unknown candidate in research run: {candidate_id}")
        decisions = dict(state.get("review_decisions") or {})
        if decision == "reset":
            decisions.pop(candidate_id, None)
        else:
            decisions[candidate_id] = {
                "decision": decision,
                "reason": " ".join(reason.split())[:1000],
                "decided_at": _now(),
                "source": "researcher",
            }
        self._update(run_id, review_decisions=decisions)
        _write_json(self._run_directory(run_id) / "review_decisions.json", decisions)
        self._rebuild_evidence(run_id)
        return self.get(run_id)

    def add_authorized_full_text(
        self,
        run_id: str,
        candidate_id: str,
        *,
        filename: str,
        content_base64: str,
        authorization_confirmed: bool,
    ) -> dict[str, Any]:
        if not authorization_confirmed:
            raise ValueError("authorization confirmation is required")
        state = self.get(run_id)
        if state.get("status") != "complete":
            raise ValueError("research run is not complete")
        if candidate_id not in {str(item.get("id")) for item in state.get("candidates", [])}:
            raise KeyError(f"unknown candidate in research run: {candidate_id}")
        try:
            body = base64.b64decode(content_base64, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("document content must be valid base64") from exc
        if not 500 <= len(body) <= 12_000_000:
            raise ValueError("document must be between 500 bytes and 12 MB")
        suffix = Path(filename).suffix.lower()
        if suffix not in {".txt", ".md", ".xml", ".nxml", ".pdf"}:
            raise ValueError("supported document types are txt, md, xml, nxml, and pdf")
        if suffix == ".pdf" and not body.startswith(b"%PDF-"):
            raise ValueError("uploaded PDF has no PDF signature")
        if suffix in {".txt", ".md"}:
            try:
                body.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("uploaded text must be UTF-8") from exc
        corpus = self._run_directory(run_id) / "corpus"
        papers = corpus / "papers"
        papers.mkdir(parents=True, exist_ok=True)
        safe_id = re.sub(r"[^a-zA-Z0-9._-]+", "-", candidate_id).strip("-")
        path = papers / f"researcher-{safe_id}{suffix}"
        path.write_bytes(body)
        # Parse before accepting the document into scientific memory.
        from sci_search.corpus import _document_text

        parsed = _document_text(path)
        if len(parsed.strip()) < 500:
            path.unlink(missing_ok=True)
            raise ValueError("uploaded document contains fewer than 500 parsed text characters")
        outcomes = [
            item
            for item in state.get("acquisitions", [])
            if item.get("publication_id") != candidate_id
        ]
        outcomes.append(
            dataclass_to_dict(
                AcquisitionOutcome(
                    candidate_id,
                    "acquired",
                    "researcher_supplied_authorized",
                    path.relative_to(corpus).as_posix(),
                    _content_type(suffix),
                    len(body),
                    len(parsed),
                    None,
                )
            )
        )
        decisions = dict(state.get("review_decisions") or {})
        decisions[candidate_id] = {
            "decision": "include",
            "reason": "authorized full text supplied by researcher",
            "decided_at": _now(),
            "source": "researcher",
        }
        uploads = list(state.get("authorized_uploads") or [])
        uploads.append(
            {
                "publication_id": candidate_id,
                "filename": Path(filename).name,
                "relative_path": path.relative_to(corpus).as_posix(),
                "byte_count": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "uploaded_at": _now(),
                "authorization_confirmed": True,
            }
        )
        self._update(
            run_id, acquisitions=outcomes, review_decisions=decisions, authorized_uploads=uploads
        )
        _write_json(self._run_directory(run_id) / "review_decisions.json", decisions)
        _write_json(self._run_directory(run_id) / "authorized_uploads.json", uploads)
        self._rebuild_evidence(run_id)
        return self.get(run_id)

    def _rebuild_evidence(self, run_id: str) -> None:
        state = self.get(run_id)
        candidates = {
            _candidate_from_dict(item).id: _candidate_from_dict(item)
            for item in state.get("candidates", [])
        }
        outcomes = tuple(_outcome_from_dict(item) for item in state.get("acquisitions", []))
        decisions = state.get("review_decisions") or {}
        acquired = [
            (candidates[outcome.publication_id], outcome)
            for outcome in outcomes
            if outcome.status == "acquired"
            and outcome.relative_path
            and outcome.publication_id in candidates
        ]
        run_directory = self._run_directory(run_id)
        corpus = run_directory / "corpus"
        active, fulltext_screening = screen_acquired_documents(
            str(state["question"]),
            plan_question(str(state["question"])),
            corpus,
            acquired,
            researcher_decisions=decisions,
        )
        plan = plan_question(str(state["question"]))
        _provisional_matrix = build_study_matrix(
            str(state["question"]),
            plan,
            corpus,
            acquired,
            fulltext_screening,
        )
        previous = state.get("study_matrix") if isinstance(state.get("study_matrix"), dict) else {}
        adjudication = (
            previous.get("adjudication")
            if isinstance(previous.get("adjudication"), dict)
            else {
                "status": "not_run",
                "decisions": [],
            }
        )
        fulltext_screening = apply_adjudication(fulltext_screening, adjudication)
        active = active_from_screening(acquired, fulltext_screening)
        _write_json(run_directory / "full_text_screening.json", fulltext_screening)
        _write_manifest(
            corpus, str(state["question"]), active, fulltext_screening=fulltext_screening
        )
        investigation = GenericResearchEngine(
            load_corpus(corpus),
            lifecycle_lookup=self.memory.evidence_states if self.memory is not None else None,
        ).investigate(str(state["question"]), session_id=f"research:{run_id}")
        payload = investigation.to_dict()
        if self.memory is not None:
            self.memory.apply_lifecycle(payload)
        payload["synthesis"] = build_structured_synthesis(payload)
        payload["ai_analysis"] = gate_model_analysis(
            self._analyze(
                str(state["question"]),
                payload.get("evidence", []),
                payload.get("answer_adequacy", {}),
            ),
            payload.get("answer_adequacy", {}),
        )
        payload["corpus_id"] = f"research:{run_id}"
        payload["question_brief"] = state.get("question_brief")
        previous_result = state.get("result") if isinstance(state.get("result"), dict) else {}
        research_run = dict(previous_result.get("research_run") or {})
        coverage_search = dict(research_run.get("coverage_search") or {})
        coverage_search["final_assessment"] = payload.get("answer_adequacy")
        research_run.update(
            {
                "full_texts_acquired": len(acquired),
                "full_texts_included": len(active),
                "candidates": state.get("candidates", []),
                "acquisitions": [dataclass_to_dict(outcome) for outcome in outcomes],
                "review_decisions": decisions,
                "authorized_uploads": state.get("authorized_uploads", []),
                "active_publication_ids": [candidate.id for candidate, _ in active],
                "full_text_screening": fulltext_screening,
                "coverage_search": coverage_search,
            }
        )
        payload["research_run"] = research_run
        study_matrix = build_study_matrix(
            str(state["question"]),
            plan,
            corpus,
            acquired,
            fulltext_screening,
            evidence=payload.get("evidence", []),
        )
        study_matrix["adjudication"] = adjudication
        payload["study_matrix"] = study_matrix
        research_run["study_matrix_summary"] = study_matrix.get("summary")
        _write_json(run_directory / "study_matrix.json", study_matrix)
        if self.memory is not None:
            payload["memory_update"] = self.memory.ingest_run(
                run_id, str(state["question"]), corpus, payload
            )
            payload["memory_stats"] = self.memory.stats()
        payload["research_landscape"] = build_research_landscape(payload)
        review = build_literature_review(payload)
        _write_json(run_directory / "literature_review.json", review)
        payload["literature_review_report"] = review
        payload["literature_review"] = {
            "available": True,
            "schema_version": review["schema_version"],
            "artifact": "literature_review.json",
        }
        _write_json(run_directory / "investigation.json", payload)
        discovery_path = run_directory / "discovery.json"
        discovery = (
            json.loads(discovery_path.read_text(encoding="utf-8"))
            if discovery_path.is_file()
            else {}
        )
        discovery.update(
            {
                "review_decisions": decisions,
                "authorized_uploads": state.get("authorized_uploads", []),
                "full_text_screening": fulltext_screening,
            }
        )
        _write_json(discovery_path, discovery)
        progress = dict(state.get("progress") or {})
        progress["full_texts_acquired"] = len(acquired)
        progress["full_texts_included"] = len(active)
        self._update(
            run_id,
            result=payload,
            progress=progress,
            full_text_screening=fulltext_screening,
            study_matrix=study_matrix,
        )

    def _execute_guarded(self, run_id: str, question: str, limits: ResearchLimits) -> None:
        try:
            self._execute(run_id, question, limits)
        except Exception as exc:  # the persisted run must survive provider/parser failures
            self._update(
                run_id,
                status="failed",
                stage="failed",
                message="The research run stopped before producing an evidence report.",
                error=_safe_run_error(exc, self.root),
                finished_at=_now(),
            )
            (self._run_directory(run_id) / "failure.txt").write_text(
                traceback.format_exc(), encoding="utf-8"
            )

    def _execute(self, run_id: str, question: str, limits: ResearchLimits) -> None:
        run_directory = self._run_directory(run_id)
        corpus_directory = run_directory / "corpus"
        corpus_directory.mkdir(parents=True, exist_ok=True)
        self._update(
            run_id,
            status="running",
            stage="planning",
            message="Translating the question into inspectable search strategies.",
        )
        planning_checkpoint = PlanningStage().run(_stage_context(run_id, question, inputs={}))
        plan = _research_plan(planning_checkpoint.output["plan"])
        queries = tuple(_search_query(item) for item in planning_checkpoint.output["queries"])
        memory_candidates: tuple[PublicationCandidate, ...] = ()
        memory_assessment = None
        if self.memory is not None:
            memory_assessment = self.memory.assess(plan, limit=limits.max_selected)
            memory_candidates = self.memory.candidates(plan, limit=limits.max_selected)
        self._update(
            run_id,
            plan=dataclass_to_dict(plan),
            queries=dataclass_to_dict(queries),
            memory_assessment=dataclass_to_dict(memory_assessment) if memory_assessment else None,
            progress={
                "queries_planned": len(queries),
                "cached_full_texts": memory_assessment.cached_full_texts
                if memory_assessment
                else 0,
            },
        )

        self._update(
            run_id,
            stage="discovering",
            message="Searching OpenAlex, Europe PMC and Crossref metadata.",
        )

        def discover_stage(
            serialized_queries: list[dict[str, Any]], per_query: int
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            found, log = discover_with_providers(
                tuple(_search_query(item) for item in serialized_queries),
                self.providers,
                per_query=per_query,
            )
            return dataclass_to_dict(found), list(log)

        discovery_checkpoint = DiscoveryStage(discover_stage).run(
            _stage_context(
                run_id,
                question,
                inputs={"queries": dataclass_to_dict(queries), "per_query": limits.per_query},
                prior={"planning": planning_checkpoint.output},
            )
        )
        discovered = tuple(
            _publication_candidate(item) for item in discovery_checkpoint.output["candidates"]
        )
        search_log = tuple(discovery_checkpoint.output["search_log"])
        raw = (*memory_candidates, *discovered)
        if memory_candidates:
            search_log = (
                {
                    "provider": "scientific_memory",
                    "query_id": "query:scientific-memory",
                    "query": question,
                    "purpose": "reuse existing scientific evidence",
                    "result_count": len(memory_candidates),
                    "elapsed_seconds": 0.0,
                    "status": "ok",
                    "error": None,
                },
                *search_log,
            )
        merged = merge_candidates(raw)
        self._update(
            run_id,
            search_log=list(search_log),
            progress={
                "queries_planned": len(queries),
                "records_retrieved": len(raw),
                "unique_candidates": len(merged),
            },
        )

        self._update(
            run_id,
            stage="screening",
            message="Deduplicating, screening, and checking one bounded citation-network hop.",
        )
        initial_screened = screen_candidates(merged, plan, limit=limits.max_selected)
        citation_seeds = tuple(
            item
            for item in initial_screened
            if item.screening_status in {"selected", "unavailable"} and item.openalex_id
        )[: limits.citation_seed_count]
        citation_candidates_list: list[PublicationCandidate] = []
        citation_log_list: list[dict[str, object]] = []
        expanded_seed_ids: set[str] = set()
        frontier = citation_seeds
        for depth in range(1, limits.citation_depth + 1):
            if not frontier or not limits.citation_neighbors_per_seed:
                break
            found, logs = expand_citation_network(
                frontier, self.providers, per_seed=limits.citation_neighbors_per_seed
            )
            expanded_seed_ids.update(item.id for item in frontier)
            citation_candidates_list.extend(found)
            citation_log_list.extend({**item, "depth": depth} for item in logs)
            raw = (*raw, *found)
            merged = merge_candidates(raw)
            interim = screen_candidates(merged, plan, limit=limits.max_selected)
            frontier = tuple(
                item
                for item in interim
                if item.screening_status in {"selected", "unavailable"}
                and item.openalex_id
                and item.id not in expanded_seed_ids
            )[: limits.citation_seed_count]
        citation_candidates = tuple(citation_candidates_list)
        citation_log = tuple(citation_log_list)
        search_log = (*search_log, *citation_log)
        screened = screen_candidates(merged, plan, limit=limits.max_selected)
        selected = [candidate for candidate in screened if candidate.screening_status == "selected"]
        selected = _prioritize_acquisition_candidates(selected, plan)
        rank_with_feedback = getattr(self.memory, "rank_for_acquisition", None)
        if rank_with_feedback is not None:
            selected = list(rank_with_feedback(plan, tuple(selected)))
            selected_by_id = {item.id: item for item in selected}
            screened = tuple(selected_by_id.get(item.id, item) for item in screened)
        candidate_payload = dataclass_to_dict(screened)
        self._update(
            run_id,
            search_log=list(search_log),
            candidates=candidate_payload,
            progress={
                "queries_planned": len(queries),
                "records_retrieved": len(raw),
                "unique_candidates": len(merged),
                "selected_candidates": len(selected),
                "citation_seeds": len(citation_seeds),
                "citation_candidates": len(citation_candidates),
            },
        )

        initial_target = min(limits.initial_full_texts, limits.max_full_texts)
        self._update(
            run_id,
            stage="acquiring",
            message=f"Acquiring the initial {initial_target}-paper evidence set from trusted repositories.",
        )
        outcomes: list[AcquisitionOutcome] = []
        acquired: list[tuple[PublicationCandidate, AcquisitionOutcome]] = []
        attempts = 0
        candidate_queue = list(selected)

        def acquire_until(target: int) -> None:
            nonlocal attempts
            while (
                candidate_queue
                and len(acquired) < target
                and len(acquired) < limits.max_full_texts
                and attempts < limits.max_acquisition_attempts
            ):
                candidate = candidate_queue.pop(0)
                attempts += 1

                def acquire_candidate(serialized: dict[str, Any]) -> dict[str, Any]:
                    current_candidate = _publication_candidate(serialized)
                    reused = (
                        self.memory.reuse_document(current_candidate, corpus_directory)
                        if self.memory is not None
                        else None
                    )
                    if reused:
                        relative_path, byte_count, download_relative_path = reused
                        acquired_outcome = AcquisitionOutcome(
                            current_candidate.id,
                            "acquired",
                            "scientific_memory_cache",
                            relative_path,
                            None,
                            byte_count,
                            0,
                            None,
                            download_relative_path,
                            "scientific_memory_cache",
                        )
                    else:
                        acquired_outcome = self.acquirer(current_candidate, corpus_directory)
                    return dataclass_to_dict(acquired_outcome)

                acquisition_checkpoint = AcquisitionStage(acquire_candidate).run(
                    _stage_context(
                        run_id,
                        question,
                        inputs={"candidate": dataclass_to_dict(candidate)},
                    )
                )
                outcome = AcquisitionOutcome(**acquisition_checkpoint.output)
                outcome = _validated_acquisition_outcome(outcome, corpus_directory)
                outcomes.append(outcome)
                if outcome.status == "acquired" and outcome.relative_path:
                    acquired.append((candidate, outcome))
                self._update(
                    run_id,
                    acquisitions=dataclass_to_dict(tuple(outcomes)),
                    progress={
                        "queries_planned": len(queries),
                        "records_retrieved": len(raw),
                        "unique_candidates": len(merged),
                        "selected_candidates": len(selected),
                        "citation_seeds": len(citation_seeds),
                        "citation_candidates": len(citation_candidates),
                        "acquisition_attempts": attempts,
                        "full_texts_acquired": len(acquired),
                        "full_texts_unreadable": sum(
                            item.status == "unreadable" for item in outcomes
                        ),
                        "full_text_target": limits.max_full_texts,
                        "current_batch_target": target,
                        "review_mode": limits.review_mode,
                    },
                )

        def assess_current() -> tuple[
            list[tuple[PublicationCandidate, AcquisitionOutcome]], list[dict[str, Any]], Any
        ]:
            active, screening = screen_acquired_documents(
                question, plan, corpus_directory, acquired
            )
            _write_json(run_directory / "full_text_screening.json", screening)
            _write_manifest(corpus_directory, question, active, fulltext_screening=screening)
            assessment = GenericResearchEngine(
                load_corpus(corpus_directory),
                lifecycle_lookup=self.memory.evidence_states if self.memory is not None else None,
            ).investigate(question, session_id=f"research:{run_id}")
            return active, screening, assessment

        acquire_until(initial_target)
        active_acquired, fulltext_screening, preliminary = assess_current()
        previous_contributors = preliminary.coverage.publications_with_relevant_evidence
        adaptive_stopping: dict[str, Any] = {
            "schema_version": "adaptive_stopping_v1",
            "review_mode": limits.review_mode,
            "initial_target": initial_target,
            "hard_cap": limits.max_full_texts,
            "batch_size": limits.acquisition_batch_size,
            "saturation_patience": limits.saturation_patience,
            "evaluations": [
                {
                    "stage": "initial",
                    "full_texts_acquired": len(acquired),
                    "full_texts_included": len(active_acquired),
                    "contributing_publications": previous_contributors,
                    "answer_status": preliminary.answer_adequacy.get("status"),
                }
            ],
            "reason": None,
            "explanation": None,
        }
        coverage_queries = coverage_follow_up_queries(
            question,
            preliminary.research_scope,
            preliminary.answer_adequacy,
        )
        coverage_search: dict[str, Any] = {
            "performed": False,
            "initial_assessment": preliminary.answer_adequacy,
            "queries": dataclass_to_dict(coverage_queries),
            "new_records": 0,
            "additional_full_texts": 0,
        }
        all_queries = (*queries, *coverage_queries)
        before_coverage_active = len(active_acquired)
        if preliminary.answer_adequacy.get("can_answer_overall_question"):
            adaptive_stopping["reason"] = "coverage_achieved"
            adaptive_stopping["explanation"] = (
                "Stopped because the initial evidence set covered the complete question."
            )
        elif (
            coverage_queries
            and attempts < limits.max_acquisition_attempts
            and len(acquired) < limits.max_full_texts
        ):
            self._update(
                run_id,
                stage="coverage_search",
                message="The first evidence set did not cover the complete question; searching the missing dimensions.",
            )
            additional, coverage_log = discover_with_providers(
                coverage_queries,
                self.providers,
                per_query=limits.per_query,
            )
            coverage_search["performed"] = True
            coverage_search["new_records"] = len(additional)
            raw = (*raw, *additional)
            search_log = (*search_log, *coverage_log)
            merged = merge_candidates(raw)
            screened = screen_candidates(merged, plan, limit=limits.max_selected)
            candidate_payload = dataclass_to_dict(screened)
            attempted_ids = {outcome.publication_id for outcome in outcomes}
            candidate_queue = [
                candidate
                for candidate in screened
                if candidate.screening_status == "selected" and candidate.id not in attempted_ids
            ]
            candidate_queue = _prioritize_acquisition_candidates(candidate_queue, plan)

        stalled_batches = 0
        while (
            adaptive_stopping["reason"] is None
            and candidate_queue
            and len(acquired) < limits.max_full_texts
            and attempts < limits.max_acquisition_attempts
        ):
            before_acquired = len(acquired)
            target = min(limits.max_full_texts, before_acquired + limits.acquisition_batch_size)
            self._update(
                run_id,
                stage="coverage_search",
                message="Coverage is incomplete; acquiring and evaluating another evidence batch.",
            )
            acquire_until(target)
            active_acquired, fulltext_screening, preliminary = assess_current()
            contributors = preliminary.coverage.publications_with_relevant_evidence
            new_contributors = max(0, contributors - previous_contributors)
            gained = len(acquired) - before_acquired
            adaptive_stopping["evaluations"].append(
                {
                    "stage": "continuation",
                    "full_texts_acquired": len(acquired),
                    "full_texts_included": len(active_acquired),
                    "new_full_texts": gained,
                    "contributing_publications": contributors,
                    "new_contributing_publications": new_contributors,
                    "answer_status": preliminary.answer_adequacy.get("status"),
                }
            )
            if preliminary.answer_adequacy.get("can_answer_overall_question"):
                adaptive_stopping["reason"] = "coverage_achieved"
                adaptive_stopping["explanation"] = (
                    "Stopped because the evidence set now covers the complete question."
                )
            elif gained and new_contributors == 0:
                stalled_batches += 1
                if stalled_batches >= limits.saturation_patience:
                    adaptive_stopping["reason"] = "evidence_saturation"
                    adaptive_stopping["explanation"] = (
                        "Stopped after consecutive batches added no new evidence-contributing publications."
                    )
            else:
                stalled_batches = 0
            previous_contributors = contributors

        if adaptive_stopping["reason"] is None:
            if len(acquired) >= limits.max_full_texts:
                adaptive_stopping["reason"] = "full_text_cap_reached"
                adaptive_stopping["explanation"] = (
                    "Stopped at the selected review mode's full-text safety limit; coverage may remain incomplete."
                )
            elif attempts >= limits.max_acquisition_attempts:
                adaptive_stopping["reason"] = "acquisition_attempt_limit"
                adaptive_stopping["explanation"] = (
                    "Stopped after the acquisition-attempt limit; some candidate full texts were unavailable."
                )
            else:
                adaptive_stopping["reason"] = "candidate_pool_exhausted"
                adaptive_stopping["explanation"] = (
                    "Stopped because no additional screened candidates with acquirable full text remained."
                )
        coverage_search["additional_full_texts"] = max(
            0, len(active_acquired) - before_coverage_active
        )
        coverage_search["adaptive_stopping"] = adaptive_stopping
        self._update(
            run_id,
            queries=dataclass_to_dict(all_queries),
            search_log=list(search_log),
            candidates=candidate_payload,
            acquisitions=dataclass_to_dict(tuple(outcomes)),
            coverage_search=coverage_search,
            adaptive_stopping=adaptive_stopping,
            progress={
                "queries_planned": len(all_queries),
                "records_retrieved": len(raw),
                "unique_candidates": len(merged),
                "selected_candidates": sum(
                    item.screening_status == "selected" for item in screened
                ),
                "citation_seeds": len(citation_seeds),
                "citation_candidates": len(citation_candidates),
                "acquisition_attempts": attempts,
                "full_texts_acquired": len(acquired),
                "full_texts_unreadable": sum(item.status == "unreadable" for item in outcomes),
                "full_text_target": limits.max_full_texts,
                "current_batch_target": len(acquired),
                "review_mode": limits.review_mode,
                "stopping_reason": adaptive_stopping["reason"],
            },
        )
        # Deterministic study cards make the final full-text decision inspectable.
        # Only genuinely uncertain documents are sent to the optional model, and
        # model decisions are accepted only when their quotes validate verbatim.
        provisional_matrix = build_study_matrix(
            question,
            plan,
            corpus_directory,
            acquired,
            fulltext_screening,
        )
        adjudication = adjudicate_uncertain_studies(question, provisional_matrix, self.analyzer)
        fulltext_screening = apply_adjudication(fulltext_screening, adjudication)
        active_acquired = active_from_screening(acquired, fulltext_screening)
        provisional_matrix = build_study_matrix(
            question,
            plan,
            corpus_directory,
            acquired,
            fulltext_screening,
        )
        provisional_matrix["adjudication"] = adjudication
        _write_json(run_directory / "full_text_screening.json", fulltext_screening)
        _write_json(run_directory / "study_matrix.json", provisional_matrix)
        _write_manifest(
            corpus_directory,
            question,
            active_acquired,
            fulltext_screening=fulltext_screening,
        )
        _write_json(
            run_directory / "discovery.json",
            {
                "question": question,
                "plan": dataclass_to_dict(plan),
                "queries": dataclass_to_dict(all_queries),
                "search_log": list(search_log),
                "candidates": candidate_payload,
                "acquisitions": dataclass_to_dict(tuple(outcomes)),
                "coverage_search": coverage_search,
                "adaptive_stopping": adaptive_stopping,
                "full_text_screening": fulltext_screening,
                "study_matrix": provisional_matrix,
            },
        )

        self._update(
            run_id,
            stage="analyzing",
            message="Analyzing acquired full texts and attaching findings to exact source passages.",
        )
        documents = load_corpus(corpus_directory)
        analysis_checkpoint = AnalysisStage(
            lambda context: (
                GenericResearchEngine(
                    documents,
                    lifecycle_lookup=self.memory.evidence_states
                    if self.memory is not None
                    else None,
                )
                .investigate(context.question, session_id=f"research:{context.run_id}")
                .to_dict()
            )
        ).run(
            _stage_context(
                run_id,
                question,
                inputs={
                    "document_ids": [document.publication.id for document in documents],
                    "full_text_screening": fulltext_screening,
                },
            )
        )
        payload = analysis_checkpoint.output
        coverage_search["final_assessment"] = payload.get("answer_adequacy")
        discovery_path = run_directory / "discovery.json"
        discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
        discovery["coverage_search"] = coverage_search
        _write_json(discovery_path, discovery)
        if self.memory is not None:
            self.memory.apply_lifecycle(payload)
        payload["synthesis"] = build_structured_synthesis(payload)
        payload["ai_analysis"] = gate_model_analysis(
            self._analyze(
                question,
                payload.get("evidence", []),
                payload.get("answer_adequacy", {}),
            ),
            payload.get("answer_adequacy", {}),
        )
        payload["pipeline_diagnostics"] = _build_pipeline_diagnostics(
            self.get(run_id),
            payload,
            screened=screened,
            outcomes=outcomes,
            fulltext_screening=fulltext_screening,
        )
        payload["corpus_id"] = f"research:{run_id}"
        payload["question_brief"] = self.get(run_id).get("question_brief")
        payload["research_run"] = {
            "run_id": run_id,
            "queries": dataclass_to_dict(all_queries),
            "search_log": list(search_log),
            "records_retrieved": len(raw),
            "unique_candidates": len(merged),
            "selected_candidates": sum(item.screening_status == "selected" for item in screened),
            "citation_seeds": len(citation_seeds),
            "citation_candidates": len(citation_candidates),
            "full_texts_acquired": len(acquired),
            "full_texts_included": len(active_acquired),
            "active_publication_ids": [candidate.id for candidate, _ in active_acquired],
            "acquisition_attempts": attempts,
            "candidates": candidate_payload,
            "acquisitions": dataclass_to_dict(tuple(outcomes)),
            "full_text_screening": fulltext_screening,
            "candidate_ledger_path": "discovery.json",
            "memory_assessment": dataclass_to_dict(memory_assessment)
            if memory_assessment
            else None,
            "full_texts_reused": sum(
                outcome.source == "scientific_memory_cache" for outcome in outcomes
            ),
            "coverage_search": coverage_search,
            "adaptive_stopping": adaptive_stopping,
            "pipeline_diagnostics": payload["pipeline_diagnostics"],
        }
        study_matrix = build_study_matrix(
            question,
            plan,
            corpus_directory,
            acquired,
            fulltext_screening,
            evidence=payload.get("evidence", []),
        )
        study_matrix["adjudication"] = adjudication
        payload["study_matrix"] = study_matrix
        payload["research_run"]["study_matrix_summary"] = study_matrix.get("summary")
        _write_json(run_directory / "study_matrix.json", study_matrix)
        if self.memory is not None:
            payload["memory_update"] = self.memory.ingest_run(
                run_id, question, corpus_directory, payload
            )
            payload["memory_stats"] = self.memory.stats()
        reporting_checkpoint = ReportingStage().run(
            _stage_context(
                run_id,
                question,
                inputs={"analysis": payload},
                prior={"analysis": analysis_checkpoint.output},
            )
        )
        payload["research_landscape"] = reporting_checkpoint.output["research_landscape"]
        review = reporting_checkpoint.output["literature_review_report"]
        _write_json(run_directory / "literature_review.json", review)
        payload["literature_review_report"] = review
        payload["literature_review"] = reporting_checkpoint.output["literature_review"]
        _write_json(run_directory / "investigation.json", payload)
        final_progress = dict(self.get(run_id).get("progress") or {})
        final_progress["full_texts_included"] = len(active_acquired)
        self._update(
            run_id,
            status="complete",
            stage="complete",
            message="Online discovery, full-text acquisition and evidence analysis are complete.",
            result=payload,
            full_text_screening=fulltext_screening,
            study_matrix=study_matrix,
            progress=final_progress,
            error=None,
            finished_at=_now(),
        )

    def _analyze(
        self,
        question: str,
        evidence: list[dict[str, Any]],
        adequacy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        model = (
            self.analyzer.model
            if self.analyzer is not None
            else os.environ.get("MISTRAL_MODEL", "mistral-small-latest")
        )
        feedback_reader = getattr(self.memory, "feedback_events", None)
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "question": question,
                    "model": model,
                    "analysis_contract": "scientific_analysis_v5_contradiction_groups",
                    "adequacy": adequacy,
                    "feedback": (feedback_reader() if feedback_reader is not None else []),
                    "evidence": [
                        tuple(
                            item.get(field)
                            for field in (
                                "id",
                                "passage",
                                "statement",
                                "document_sha256",
                                "evidence_fingerprint",
                                "schema_version",
                                "validator_version",
                                "validation_status",
                                "review_state",
                            )
                        )
                        for item in evidence
                        if isinstance(item, dict)
                    ],
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        if self.memory is not None:
            cached = self.memory.cached_analysis(fingerprint)
            if cached is not None:
                return cached
        result = analyze_if_configured(question, evidence, self.analyzer, adequacy)
        if self.memory is not None:
            self.memory.cache_analysis(fingerprint, result)
        return result

    def _new_state(
        self,
        run_id: str,
        question: str,
        limits: ResearchLimits,
        *,
        question_brief: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "question": question,
            "question_brief": question_brief,
            "status": "queued",
            "stage": "queued",
            "message": "Research run queued.",
            "created_at": _now(),
            "finished_at": None,
            "limits": dataclass_to_dict(limits),
            "plan": None,
            "queries": [],
            "search_log": [],
            "candidates": [],
            "acquisitions": [],
            "memory_assessment": None,
            "review_decisions": {},
            "study_matrix": None,
            "authorized_uploads": [],
            "progress": {},
            "pipeline_stages": [
                {
                    "stage": "queued",
                    "status": "running",
                    "started_at": _now(),
                    "completed_at": None,
                    "message": "Research run queued.",
                    "progress": {},
                }
            ],
            "result": None,
            "error": None,
        }

    def _run_directory(self, run_id: str) -> Path:
        if not run_id or not all(character.isalnum() or character in "-_" for character in run_id):
            raise ValueError("invalid research run id")
        path = (self.root / run_id).resolve()
        path.relative_to(self.root)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _set_state(self, run_id: str, state: dict[str, Any]) -> None:
        with self._lock:
            self._states[run_id] = state
            self._persist(run_id, state)

    def _update(self, run_id: str, **changes: Any) -> None:
        with self._lock:
            state = dict(self._states[run_id])
            next_stage = changes.get("stage")
            stages = [dict(item) for item in state.get("pipeline_stages") or []]
            if next_stage and next_stage != state.get("stage"):
                now = _now()
                if stages and stages[-1].get("completed_at") is None:
                    stages[-1]["completed_at"] = now
                    stages[-1]["status"] = "failed" if next_stage == "failed" else "complete"
                    stages[-1]["progress"] = dict(state.get("progress") or {})
                stages.append(
                    {
                        "stage": next_stage,
                        "status": "failed"
                        if next_stage == "failed"
                        else "complete"
                        if next_stage == "complete"
                        else "running",
                        "started_at": now,
                        "completed_at": now if next_stage in {"complete", "failed"} else None,
                        "message": changes.get("message") or "",
                        "progress": dict(changes.get("progress") or state.get("progress") or {}),
                    }
                )
                changes["pipeline_stages"] = stages
            elif stages and ("progress" in changes or "message" in changes):
                stages[-1]["progress"] = dict(
                    changes.get("progress") or state.get("progress") or {}
                )
                if changes.get("message"):
                    stages[-1]["message"] = changes["message"]
                changes["pipeline_stages"] = stages
            state.update(changes)
            self._states[run_id] = state
            self._persist(run_id, state)

    def _persist(self, run_id: str, state: dict[str, Any]) -> None:
        path = self._run_directory(run_id) / "run.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        temporary.replace(path)


def _write_manifest(
    corpus_directory: Path,
    question: str,
    acquired: list[tuple[PublicationCandidate, AcquisitionOutcome]],
    *,
    fulltext_screening: list[dict[str, Any]] | None = None,
) -> None:
    screening_by_id = {
        str(item.get("publication_id")): item
        for item in (fulltext_screening or [])
        if isinstance(item, dict)
    }
    documents = []
    for candidate, outcome in acquired:
        evidence_type = _evidence_type(candidate)
        screening = screening_by_id.get(candidate.id, {})
        documents.append(
            {
                "id": candidate.id,
                "title": candidate.title,
                "path": outcome.relative_path,
                "download_path": outcome.download_relative_path or outcome.relative_path,
                "download_source": outcome.download_source or outcome.source,
                "analysis_format": Path(str(outcome.relative_path or "")).suffix.lower(),
                "download_format": Path(
                    str(outcome.download_relative_path or outcome.relative_path or "")
                ).suffix.lower(),
                "doi": candidate.doi,
                "year": candidate.year,
                "authors": list(candidate.authors),
                "document_type": candidate.publication_type,
                "source_url": candidate.source_url,
                "access_status": "researcher_supplied_authorized"
                if outcome.source == "researcher_supplied_authorized"
                else "open_access",
                "license": candidate.license,
                "evidence_type": evidence_type,
                "result_nature": "reported" if evidence_type == "review" else "measured",
                "technology": question,
                "configuration": "automatically discovered full-text publication",
                "system_scale": None,
                "calculation_boundary": "source-reported study scope",
                "fulltext_inclusion": screening.get("decision") or "included",
                "fulltext_screening_method": screening.get("method"),
                "fulltext_screening_reason": screening.get("reason"),
            }
        )
    _write_json(
        corpus_directory / "manifest.json",
        {
            "corpus_name": f"Online research run: {question}",
            "generated_at": _now(),
            "documents": documents,
        },
    )


def _evidence_type(candidate: PublicationCandidate) -> str:
    text = f"{candidate.publication_type} {candidate.title} {candidate.abstract[:500]}".lower()
    if "review" in text or "meta-analysis" in text:
        return "review"
    if any(term in text for term in ("simulation", "modelling", "modeling", "modelled", "modeled")):
        return "simulation"
    if any(term in text for term in ("trial", "experiment", "experimental", "field study")):
        return "field_experiment"
    return "observational_study"


def _build_pipeline_diagnostics(
    state: dict[str, Any],
    payload: dict[str, Any],
    *,
    screened: tuple[PublicationCandidate, ...],
    outcomes: list[AcquisitionOutcome],
    fulltext_screening: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Summarize why a run did or did not produce a defensible answer."""
    search_log = [item for item in state.get("search_log", []) if isinstance(item, dict)]
    provider_failures = [
        {"provider": item.get("provider"), "query": item.get("query"), "error": item.get("error")}
        for item in search_log
        if item.get("status") not in {None, "ok", "skipped"}
    ]
    status_counts = {
        status: sum(item.screening_status == status for item in screened)
        for status in ("selected", "unavailable", "uncertain", "excluded")
    }
    acquisition_failures = [
        {"publication_id": item.publication_id, "status": item.status, "error": item.error}
        for item in outcomes
        if item.status != "acquired"
    ]
    unreadable_count = sum(item.status == "unreadable" for item in outcomes)
    inclusion_counts = {
        status: sum(item.get("decision") == status for item in (fulltext_screening or []))
        for status in ("included", "background", "uncertain", "excluded", "unreadable")
    }
    evidence = [item for item in payload.get("evidence", []) if isinstance(item, dict)]
    contributing = {
        str(item.get("publication_id")) for item in evidence if item.get("publication_id")
    }
    ai = payload.get("ai_analysis") or {}
    adequacy = payload.get("answer_adequacy") or {}
    warnings: list[str] = []
    if provider_failures:
        warnings.append(f"{len(provider_failures)} provider-query attempts failed")
    if status_counts["unavailable"]:
        warnings.append(
            f"{status_counts['unavailable']} screened records lacked an acquirable full text"
        )
    if acquisition_failures:
        warnings.append(f"{len(acquisition_failures)} full-text acquisition attempts failed")
    if unreadable_count:
        warnings.append(
            f"{unreadable_count} acquired artifacts were unreadable for analysis; OCR may be required"
        )
    if inclusion_counts["excluded"] or inclusion_counts["uncertain"]:
        warnings.append(
            f"{inclusion_counts['excluded'] + inclusion_counts['uncertain']} acquired full texts were excluded or held for review"
        )
    if len(contributing) < 3:
        warnings.append(f"only {len(contributing)} publications contributed selected evidence")
    if not adequacy.get("can_answer_overall_question", False):
        warnings.append("the evidence coverage gate withheld the overall answer")
    if ai.get("status") != "complete":
        warnings.append(
            f"generative synthesis was not used: {ai.get('reason') or ai.get('status') or 'unavailable'}"
        )
    stages = [dict(item) for item in state.get("pipeline_stages") or []]
    if stages and stages[-1].get("stage") == "analyzing":
        stages[-1]["status"] = "complete"
        stages[-1]["completed_at"] = _now()
    return {
        "schema_version": "sci_search_pipeline_diagnostics_v1",
        "stages": stages,
        "discovery": {
            "queries": len(state.get("queries") or []),
            "provider_attempts": len(search_log),
            "provider_failures": provider_failures,
            "records_retrieved": (state.get("progress") or {}).get("records_retrieved", 0),
            "unique_candidates": (state.get("progress") or {}).get("unique_candidates", 0),
        },
        "screening": status_counts,
        "acquisition": {
            "attempted": len(outcomes),
            "acquired": sum(item.status == "acquired" for item in outcomes),
            "unreadable": unreadable_count,
            "failures": acquisition_failures,
        },
        "full_text_inclusion": inclusion_counts,
        "analysis": {
            "full_texts_analyzed": (payload.get("coverage") or {}).get("full_texts_analyzed", 0),
            "contributing_publications": len(contributing),
            "selected_passages": len(evidence),
            "answer_adequacy": adequacy.get("status"),
            "missing_requirements": adequacy.get("missing_requirements", []),
            "model_status": ai.get("status"),
            "model": ai.get("model"),
            "rejected_model_records": (ai.get("validation") or {}).get("rejected_model_records", 0),
        },
        "warnings": warnings,
    }


def _is_review(candidate: PublicationCandidate) -> bool:
    return _evidence_type(candidate) == "review"


def _acquisition_priority(candidate: PublicationCandidate, plan: Any) -> tuple[float, float]:
    """Rank full texts without sending every review behind every primary study."""
    review_penalty = (
        0.0 if "review" in plan.evidence_preferences else 0.08 if _is_review(candidate) else 0.0
    )
    explanatory_boost = 0.0
    if (
        str(plan.question).casefold().startswith("why ")
        or "what explains" in str(plan.question).casefold()
    ):
        title = candidate.title.casefold()
        if any(
            term in title
            for term in ("meta-analysis", "meta-regression", "systematic review", "heterogen")
        ):
            explanatory_boost = 0.18
    cache_bonus = 0.04 if candidate.has_local_fulltext else 0.0
    return (
        -(candidate.relevance_score - review_penalty + explanatory_boost + cache_bonus),
        -candidate.cited_by_count,
    )


def _prioritize_acquisition_candidates(
    candidates: list[PublicationCandidate],
    plan: Any,
) -> list[PublicationCandidate]:
    """Reserve a few early acquisition slots for high-ranked syntheses.

    A strict primary-study-first ordering previously pushed even the best
    systematic review below a 25-paper corpus budget. Four bounded synthesis
    slots preserve study-design diversity without allowing reviews to dominate.
    """
    ranked = sorted(candidates, key=lambda candidate: _acquisition_priority(candidate, plan))
    reviews = sorted(
        (candidate for candidate in ranked if _is_review(candidate)),
        key=lambda candidate: (-candidate.relevance_score, -candidate.cited_by_count),
    )[:4]
    if not reviews:
        return ranked
    review_ids = {candidate.id for candidate in reviews}
    result = [candidate for candidate in ranked if candidate.id not in review_ids]
    for position, candidate in zip((3, 8, 13, 18), reviews, strict=False):
        result.insert(min(position, len(result)), candidate)
    return result


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _stage_context(
    run_id: str,
    question: str,
    *,
    inputs: dict[str, Any],
    prior: dict[str, dict[str, Any]] | None = None,
) -> StageContext:
    return StageContext(
        project_id="legacy-local",
        run_id=run_id,
        question=question,
        inputs=inputs,
        prior_checkpoints=prior or {},
    )


def _research_plan(payload: object) -> ResearchPlan:
    if not isinstance(payload, dict):
        raise ValueError("planning stage returned an invalid plan")
    return ResearchPlan(
        question=str(payload["question"]),
        profile_id=str(payload["profile_id"]),
        intent=str(payload["intent"]),
        concepts=tuple(str(item) for item in payload["concepts"]),
        entity_phrases=tuple(str(item) for item in payload["entity_phrases"]),
        expanded_terms=tuple(str(item) for item in payload["expanded_terms"]),
        evidence_preferences=tuple(str(item) for item in payload["evidence_preferences"]),
        comparison_dimensions=tuple(str(item) for item in payload["comparison_dimensions"]),
    )


def _search_query(payload: object) -> SearchQuery:
    if not isinstance(payload, dict):
        raise ValueError("discovery stage received an invalid query")
    return SearchQuery(str(payload["id"]), str(payload["text"]), str(payload["purpose"]))


def _publication_candidate(payload: object) -> PublicationCandidate:
    if not isinstance(payload, dict):
        raise ValueError("discovery stage returned an invalid candidate")

    def optional_text(key: str) -> str | None:
        value = payload.get(key)
        return str(value) if value is not None else None

    def texts(key: str) -> tuple[str, ...]:
        value = payload.get(key, [])
        return tuple(str(item) for item in value) if isinstance(value, (list, tuple)) else ()

    year_value = payload.get("year")
    return PublicationCandidate(
        id=str(payload["id"]),
        title=str(payload["title"]),
        abstract=str(payload.get("abstract") or ""),
        year=int(year_value) if year_value is not None else None,
        doi=optional_text("doi"),
        authors=texts("authors"),
        publication_type=str(payload.get("publication_type") or "article"),
        source_url=optional_text("source_url"),
        full_text_url=optional_text("full_text_url"),
        document_fingerprint=optional_text("document_fingerprint"),
        author_ids=texts("author_ids"),
        institutions=texts("institutions"),
        institution_ids=texts("institution_ids"),
        affiliations=texts("affiliations"),
        openalex_id=optional_text("openalex_id"),
        pmcid=optional_text("pmcid"),
        cited_by_count=int(payload.get("cited_by_count") or 0),
        is_open_access=bool(payload.get("is_open_access", False)),
        license=optional_text("license"),
        has_pdf=bool(payload.get("has_pdf", False)),
        has_structured_fulltext=bool(payload.get("has_structured_fulltext", False)),
        has_local_fulltext=bool(payload.get("has_local_fulltext", False)),
        is_retracted=bool(payload.get("is_retracted", False)),
        providers=texts("providers"),
        matched_query_ids=texts("matched_query_ids"),
        citation_relations=texts("citation_relations"),
        relevance_score=float(payload.get("relevance_score") or 0.0),
        concept_coverage=float(payload.get("concept_coverage") or 0.0),
        screening_status=str(payload.get("screening_status") or "candidate"),
        screening_reason=str(payload.get("screening_reason") or "not screened"),
    )


def _validated_acquisition_outcome(
    outcome: AcquisitionOutcome, corpus_directory: Path
) -> AcquisitionOutcome:
    """Ensure an acquired artifact is actually parseable before it consumes the evidence budget."""
    if outcome.status != "acquired" or not outcome.relative_path:
        return outcome
    path = (corpus_directory / outcome.relative_path).resolve()
    path.relative_to(corpus_directory.resolve())
    try:
        from sci_search.corpus import _document_text

        text = _document_text(path)
    except Exception as exc:  # parser libraries expose several format-specific exception classes
        from sci_search.corpus import summarize_document_parse_error

        return replace(
            outcome,
            status="unreadable",
            text_char_count=0,
            error=summarize_document_parse_error(exc, path),
        )
    return replace(outcome, text_char_count=len(text))


def _safe_run_error(exc: Exception, run_root: Path) -> str:
    message = " ".join(str(exc).split())
    for value in (str(run_root), str(run_root.parent), str(Path.cwd())):
        message = message.replace(value, "[local workspace]")
    return f"{type(exc).__name__}: {message[:500]}"


def _candidate_from_dict(payload: dict[str, Any]) -> PublicationCandidate:
    values: dict[str, Any] = {}
    for name, field in PublicationCandidate.__dataclass_fields__.items():
        value = payload[name] if name in payload else field.default
        if name in {
            "authors",
            "author_ids",
            "institutions",
            "institution_ids",
            "affiliations",
            "providers",
            "matched_query_ids",
            "citation_relations",
        }:
            value = tuple(value or ())
        values[name] = value
    return PublicationCandidate(**values)


def _outcome_from_dict(payload: dict[str, Any]) -> AcquisitionOutcome:
    return AcquisitionOutcome(
        **{
            name: payload[name] if name in payload else field.default
            for name, field in AcquisitionOutcome.__dataclass_fields__.items()
        }
    )


def _content_type(suffix: str) -> str:
    return {
        ".pdf": "application/pdf",
        ".xml": "application/xml",
        ".nxml": "application/xml",
        ".md": "text/markdown",
        ".txt": "text/plain",
    }[suffix]


def _download_name(title: str, suffix: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", title).strip("-._")[:120] or "publication"
    clean_suffix = suffix if re.fullmatch(r"\.[a-zA-Z0-9]{1,8}", suffix) else ".bin"
    return stem + clean_suffix.lower()


def _now() -> str:
    return datetime.now(UTC).isoformat()
