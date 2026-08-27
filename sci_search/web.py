"""Dependency-free researcher web application."""

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from sci_search.corpus import _document_text, load_corpus
from sci_search.coverage import gate_model_analysis
from sci_search.generic_research import GenericResearchEngine
from sci_search.investigation import investigate
from sci_search.literature_review import build_literature_review
from sci_search.mistral_analysis import analyze_if_configured
from sci_search.models import dataclass_to_dict
from sci_search.pipeline import build_evidence_store
from sci_search.question_interpretation import interpret_question
from sci_search.question_planning import plan_question
from sci_search.research_landscape import build_research_landscape
from sci_search.research_runs import REVIEW_PROFILES, ResearchLimits, ResearchRunManager
from sci_search.store import EvidenceStore
from sci_search.synthesis import build_structured_synthesis
from sci_search.ui import RESEARCHER_UI
from sci_search.validation_workspace import ValidationWorkspace


class ResearchService:
    def __init__(self, corpus_directory: Path, *, store: EvidenceStore | None = None) -> None:
        self.corpus_directory = corpus_directory.resolve()
        self.store, self.pipeline_warnings = (
            (store, ()) if store is not None else build_evidence_store(self.corpus_directory)
        )
        # An energy-specific extractor is retained for the iron-air specialist,
        # but its expected "no RTE" messages are not product warnings for a
        # corpus in another scientific domain.
        if not self.store.query_results("round_trip_efficiency"):
            self.pipeline_warnings = tuple(
                warning
                for warning in self.pipeline_warnings
                if not warning.endswith(":no_round_trip_efficiency_found")
            )
        self.generic_engine = GenericResearchEngine(load_corpus(self.corpus_directory))
        self.sessions: dict[str, list[str]] = {}

    def investigate(
        self,
        question: str,
        *,
        session_id: str | None = None,
        question_brief: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        normalized = " ".join(question.lower().replace("-", " ").split())
        if (
            "round trip efficien" in normalized or "rte" in normalized.split()
        ) and self.store.query_results("round_trip_efficiency"):
            report = investigate(question, self.store)
            payload = dataclass_to_dict(report)
            payload["mode"] = "specialist_comparison"
            payload["session_id"] = session_id or "session:rte"
        else:
            history = self.sessions.get(session_id or "", [])
            current_plan = plan_question(question)
            contextualized = question
            if history and (current_plan.profile_id == "generic" or len(current_plan.concepts) < 2):
                # Preserve topic terms without injecting interface prose that
                # the transparent planner could mistake for scientific concepts.
                contextualized = f"{question} {history[-1]}"
            generic = self.generic_engine.investigate(contextualized, session_id=session_id)
            payload = generic.to_dict()
            payload["synthesis"] = build_structured_synthesis(payload)
            payload["ai_analysis"] = gate_model_analysis(
                analyze_if_configured(
                    question,
                    payload.get("evidence", []),
                    adequacy=payload.get("answer_adequacy", {}),
                ),
                payload.get("answer_adequacy", {}),
            )
            payload["question"] = question
            payload["contextualized_question"] = (
                contextualized if contextualized != question else None
            )
        payload["question_brief"] = question_brief
        if payload.get("mode") == "specialist_comparison" and not payload.get(
            "summary_evidence_ids"
        ):
            payload["summary_evidence_ids"] = [
                str(item.get("id"))
                for item in payload.get("evidence", [])
                if isinstance(item, dict) and item.get("id")
            ][:4]
        payload["research_landscape"] = build_research_landscape(payload)
        payload["literature_review_report"] = build_literature_review(payload)
        active_session = str(payload["session_id"])
        self.sessions.setdefault(active_session, []).append(question)
        payload["question_history"] = list(self.sessions[active_session])
        payload["pipeline_warnings"] = list(self.pipeline_warnings)
        return payload

    def catalog(self) -> list[dict[str, object]]:
        return [
            {
                "id": self.corpus_directory.name,
                "label": self.corpus_directory.name.replace("_", " ").title(),
                "publications": len(self.store.publications),
            }
        ]

    def interpret_question(self, question: str) -> dict[str, Any]:
        return interpret_question(question)

    def full_text(self, publication_id: str) -> dict[str, object]:
        publication = self.store.publications.get(publication_id)
        if publication is None:
            raise KeyError(f"unknown publication: {publication_id}")
        path = (self.corpus_directory / publication.source_document).resolve()
        try:
            path.relative_to(self.corpus_directory)
        except ValueError as exc:
            raise ValueError("source document falls outside the configured corpus") from exc
        if not path.is_file():
            raise FileNotFoundError(publication.source_document)
        return {
            "publication_id": publication.id,
            "title": publication.title,
            "source_document": publication.source_document,
            "content": _document_text(path),
            "fixture_status": publication.fixture_status,
        }


class CorpusCatalogService:
    """Expose multiple independently validated corpora through one local UI."""

    def __init__(
        self,
        corpus_directories: tuple[Path, ...],
        *,
        run_manager: ResearchRunManager | None = None,
        validation_workspace: ValidationWorkspace | None = None,
    ) -> None:
        if not corpus_directories:
            raise ValueError("at least one corpus is required")
        self.services = {path.resolve().name: ResearchService(path) for path in corpus_directories}
        self.default_id = next(iter(self.services))
        self.store = self.services[self.default_id].store
        self.run_manager = run_manager
        project_root = Path(__file__).resolve().parents[1]
        specification = project_root / "benchmarks" / "researcher_validation_v1.json"
        self.validation_workspace = validation_workspace or (
            ValidationWorkspace(
                specification,
                project_root / "data" / "validation_annotations",
                (
                    project_root / "data" / "validation_replays" / "v1",
                    project_root / "data" / "benchmark_runs",
                    project_root / "data" / "research_runs",
                ),
            )
            if specification.is_file()
            else None
        )

    def catalog(self) -> list[dict[str, object]]:
        items = [item for service in self.services.values() for item in service.catalog()]
        if self.run_manager is not None:
            items.append(
                {
                    "id": "online",
                    "label": "Search scientific literature",
                    "publications": None,
                    "dynamic": True,
                }
            )
        return items

    def investigate(
        self,
        question: str,
        *,
        session_id: str | None = None,
        corpus_id: str | None = None,
        question_brief: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        if corpus_id and corpus_id.startswith("research:"):
            if self.run_manager is None:
                raise KeyError("online research is not configured")
            return self.run_manager.investigate(
                corpus_id.removeprefix("research:"),
                question,
                question_brief=question_brief,
            )
        selected_id, service = self._service(corpus_id)
        payload = service.investigate(
            question, session_id=session_id, question_brief=question_brief
        )
        payload["corpus_id"] = selected_id
        return payload

    def full_text(self, publication_id: str, *, corpus_id: str | None = None) -> dict[str, object]:
        if corpus_id and corpus_id.startswith("research:"):
            if self.run_manager is None:
                raise KeyError("online research is not configured")
            return self.run_manager.full_text(corpus_id.removeprefix("research:"), publication_id)
        selected_id, service = self._service(corpus_id)
        payload = service.full_text(publication_id)
        payload["corpus_id"] = selected_id
        return payload

    def _service(self, corpus_id: str | None) -> tuple[str, ResearchService]:
        selected = corpus_id or self.default_id
        if selected not in self.services:
            raise KeyError(f"unknown corpus: {selected}")
        return selected, self.services[selected]

    def start_research(
        self,
        question: str,
        *,
        limits: ResearchLimits | None = None,
        question_brief: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.run_manager is None:
            raise ValueError("online research is not configured; OPENALEX_API_KEY is required")
        return self.run_manager.start(question, limits=limits, question_brief=question_brief)

    def interpret_question(self, question: str) -> dict[str, Any]:
        analyzer = self.run_manager.analyzer if self.run_manager is not None else None
        return interpret_question(question, analyzer=analyzer)

    def research_run(self, run_id: str) -> dict[str, Any]:
        if self.run_manager is None:
            raise ValueError("online research is not configured")
        return self.run_manager.get(run_id)

    def review_candidate(
        self, run_id: str, candidate_id: str, decision: str, reason: str = ""
    ) -> dict[str, Any]:
        if self.run_manager is None:
            raise ValueError("online research is not configured")
        return self.run_manager.review_candidate(run_id, candidate_id, decision, reason)

    def add_authorized_full_text(
        self, run_id: str, candidate_id: str, **payload: Any
    ) -> dict[str, Any]:
        if self.run_manager is None:
            raise ValueError("online research is not configured")
        return self.run_manager.add_authorized_full_text(run_id, candidate_id, **payload)

    def download_publication(self, run_id: str, publication_id: str):
        if self.run_manager is None:
            raise ValueError("online research is not configured")
        return self.run_manager.download_publication(run_id, publication_id)

    def download_publications(self, run_id: str, publication_ids: list[str] | None = None):
        if self.run_manager is None:
            raise ValueError("online research is not configured")
        return self.run_manager.download_publications(run_id, publication_ids)

    def download_literature_review(self, run_id: str, output_format: str):
        if self.run_manager is None:
            raise ValueError("online research is not configured")
        return self.run_manager.download_literature_review(run_id, output_format)

    def download_research_package(self, run_id: str):
        if self.run_manager is None:
            raise ValueError("online research is not configured")
        return self.run_manager.download_research_package(run_id)

    def scientific_memory(self, *, limit: int = 500) -> dict[str, Any]:
        if self.run_manager is None or self.run_manager.memory is None:
            raise ValueError("scientific memory is not configured")
        return self.run_manager.memory.graph_snapshot(limit=limit)

    def review_evidence(
        self,
        evidence_id: str,
        decision: str,
        reason: str = "",
        corrected_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.run_manager is None or self.run_manager.memory is None:
            raise ValueError("scientific memory is not configured")
        return self.run_manager.memory.review_evidence(
            evidence_id,
            decision,
            reason=reason,
            corrected_payload=corrected_payload,
        )

    def validation_overview(self) -> dict[str, Any]:
        if self.validation_workspace is None:
            raise ValueError("validation workspace is not configured")
        return self.validation_workspace.overview()

    def validation_case(self, case_id: str) -> dict[str, Any]:
        if self.validation_workspace is None:
            raise ValueError("validation workspace is not configured")
        return self.validation_workspace.case(case_id)

    def annotate_validation(self, case_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.validation_workspace is None:
            raise ValueError("validation workspace is not configured")
        return self.validation_workspace.annotate(case_id, payload)

    def validation_full_text(self, case_id: str, publication_id: str) -> dict[str, Any]:
        if self.validation_workspace is None:
            raise ValueError("validation workspace is not configured")
        return self.validation_workspace.full_text(case_id, publication_id)

    def validation_export(self) -> bytes:
        if self.validation_workspace is None:
            raise ValueError("validation workspace is not configured")
        guide = Path(__file__).resolve().parents[1] / "docs" / "RESEARCHER_VALIDATION_GUIDE.md"
        return self.validation_workspace.export_package(guide)


def create_handler(service: ResearchService | CorpusCatalogService) -> type[BaseHTTPRequestHandler]:
    class SciSearchHandler(BaseHTTPRequestHandler):
        server_version = "SciSearch/0.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send(HTTPStatus.OK, RESEARCHER_UI.encode("utf-8"), "text/html; charset=utf-8")
                return
            if parsed.path == "/api/health":
                catalog = service.catalog()
                self._json(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "publications": sum(
                            int(item["publications"])
                            for item in catalog
                            if isinstance(item.get("publications"), int)
                        ),
                        "corpora": sum(not bool(item.get("dynamic")) for item in catalog),
                        "online_research": any(bool(item.get("dynamic")) for item in catalog),
                        "ai_analysis": bool(os.environ.get("MISTRAL_API_KEY")),
                        "scientific_memory": service.run_manager.memory.stats()
                        if isinstance(service, CorpusCatalogService)
                        and service.run_manager
                        and service.run_manager.memory
                        else None,
                    },
                )
                return
            if parsed.path == "/api/corpora":
                self._json(HTTPStatus.OK, {"corpora": service.catalog()})
                return
            if parsed.path == "/api/validation":
                if not isinstance(service, CorpusCatalogService):
                    self._json(
                        HTTPStatus.NOT_FOUND, {"error": "validation workspace is not configured"}
                    )
                    return
                case_id = parse_qs(parsed.query).get("case_id", [""])[0].strip()
                try:
                    self._json(
                        HTTPStatus.OK,
                        service.validation_case(case_id)
                        if case_id
                        else service.validation_overview(),
                    )
                except KeyError as exc:
                    self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                except (ValueError, FileNotFoundError) as exc:
                    self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
                return
            if parsed.path == "/api/validation/full-text":
                if not isinstance(service, CorpusCatalogService):
                    self._json(
                        HTTPStatus.NOT_FOUND, {"error": "validation workspace is not configured"}
                    )
                    return
                values = parse_qs(parsed.query)
                try:
                    self._json(
                        HTTPStatus.OK,
                        service.validation_full_text(
                            values.get("case_id", [""])[0].strip(),
                            values.get("publication_id", [""])[0].strip(),
                        ),
                    )
                except KeyError as exc:
                    self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                except (ValueError, FileNotFoundError) as exc:
                    self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
                return
            if parsed.path == "/api/validation/export":
                if not isinstance(service, CorpusCatalogService):
                    self._json(
                        HTTPStatus.NOT_FOUND, {"error": "validation workspace is not configured"}
                    )
                    return
                try:
                    self._download(
                        service.validation_export(),
                        "application/zip",
                        "sci-search-validation-package.zip",
                    )
                except ValueError as exc:
                    self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
                return
            if parsed.path == "/api/scientific-memory":
                if not isinstance(service, CorpusCatalogService):
                    self._json(
                        HTTPStatus.NOT_FOUND, {"error": "scientific memory is not configured"}
                    )
                    return
                raw_limit = parse_qs(parsed.query).get("limit", ["500"])[0]
                try:
                    self._json(HTTPStatus.OK, service.scientific_memory(limit=int(raw_limit)))
                except ValueError as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            if parsed.path == "/api/research-runs":
                if not isinstance(service, CorpusCatalogService):
                    self._json(HTTPStatus.NOT_FOUND, {"error": "online research is not configured"})
                    return
                run_id = parse_qs(parsed.query).get("run_id", [""])[0].strip()
                if not run_id:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "run_id is required"})
                    return
                try:
                    self._json(HTTPStatus.OK, service.research_run(run_id))
                except KeyError as exc:
                    self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                return
            if parsed.path == "/api/full-text":
                publication_id = parse_qs(parsed.query).get("publication_id", [""])[0].strip()
                corpus_id = parse_qs(parsed.query).get("corpus_id", [""])[0].strip() or None
                if not publication_id:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "publication_id is required"})
                    return
                try:
                    self._json(
                        HTTPStatus.OK,
                        service.full_text(publication_id, corpus_id=corpus_id)
                        if isinstance(service, CorpusCatalogService)
                        else service.full_text(publication_id),
                    )
                except KeyError as exc:
                    self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                except (ValueError, FileNotFoundError) as exc:
                    self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
                return
            if parsed.path == "/api/publication-download":
                if not isinstance(service, CorpusCatalogService):
                    self._json(HTTPStatus.NOT_FOUND, {"error": "online research is not configured"})
                    return
                values = parse_qs(parsed.query)
                run_id = values.get("run_id", [""])[0].strip()
                publication_id = values.get("publication_id", [""])[0].strip()
                try:
                    payload = service.download_publication(run_id, publication_id)
                    self._download(payload.body, payload.content_type, payload.filename)
                except KeyError as exc:
                    self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                except (ValueError, FileNotFoundError) as exc:
                    self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
                return
            if parsed.path == "/api/literature-review":
                if not isinstance(service, CorpusCatalogService):
                    self._json(HTTPStatus.NOT_FOUND, {"error": "online research is not configured"})
                    return
                values = parse_qs(parsed.query)
                run_id = values.get("run_id", [""])[0].strip()
                output_format = values.get("format", ["html"])[0].strip().lower()
                try:
                    payload = service.download_literature_review(run_id, output_format)
                    self._download(payload.body, payload.content_type, payload.filename)
                except KeyError as exc:
                    self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                except (ValueError, FileNotFoundError) as exc:
                    self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
                return
            if parsed.path == "/api/research-package":
                if not isinstance(service, CorpusCatalogService):
                    self._json(HTTPStatus.NOT_FOUND, {"error": "online research is not configured"})
                    return
                run_id = parse_qs(parsed.query).get("run_id", [""])[0].strip()
                try:
                    payload = service.download_research_package(run_id)
                    self._download(payload.body, payload.content_type, payload.filename)
                except KeyError as exc:
                    self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                except (ValueError, FileNotFoundError) as exc:
                    self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_POST(self) -> None:
            endpoint = urlparse(self.path).path
            if endpoint not in {
                "/api/investigate",
                "/api/interpret-question",
                "/api/research-runs",
                "/api/research-runs/review",
                "/api/research-runs/upload",
                "/api/publications-download",
                "/api/evidence-review",
                "/api/validation/annotation",
            }:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                maximum = 17_000_000 if endpoint == "/api/research-runs/upload" else 100_000
                if length < 1 or length > maximum:
                    raise ValueError(f"request body must be between 1 and {maximum} bytes")
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(body, dict):
                    raise ValueError("request body must be a JSON object")
                if endpoint == "/api/interpret-question":
                    question = str(body.get("question") or "").strip()
                    if not question:
                        raise ValueError("question is required")
                    self._json(HTTPStatus.OK, service.interpret_question(question))
                    return
                if endpoint == "/api/validation/annotation":
                    if not isinstance(service, CorpusCatalogService):
                        raise ValueError("validation workspace is not configured")
                    case_id = str(body.get("case_id") or "").strip()
                    if not case_id:
                        raise ValueError("case_id is required")
                    annotation = body.get("annotation")
                    if not isinstance(annotation, dict):
                        raise ValueError("annotation must be an object")
                    self._json(HTTPStatus.OK, service.annotate_validation(case_id, annotation))
                    return
                if endpoint == "/api/publications-download":
                    if not isinstance(service, CorpusCatalogService):
                        raise ValueError("online research is not configured")
                    ids = body.get("publication_ids")
                    if ids is not None and (not isinstance(ids, list) or len(ids) > 100):
                        raise ValueError("publication_ids must be a list of at most 100 IDs")
                    payload = service.download_publications(
                        str(body.get("run_id") or "").strip(),
                        [str(item) for item in ids] if ids else None,
                    )
                    self._download(payload.body, payload.content_type, payload.filename)
                    return
                if endpoint == "/api/research-runs/review":
                    if not isinstance(service, CorpusCatalogService):
                        raise ValueError("online research is not configured")
                    self._json(
                        HTTPStatus.OK,
                        service.review_candidate(
                            str(body.get("run_id") or "").strip(),
                            str(body.get("candidate_id") or "").strip(),
                            str(body.get("decision") or "").strip(),
                            str(body.get("reason") or "").strip(),
                        ),
                    )
                    return
                if endpoint == "/api/evidence-review":
                    if not isinstance(service, CorpusCatalogService):
                        raise ValueError("scientific memory is not configured")
                    corrected = body.get("corrected_payload")
                    if corrected is not None and not isinstance(corrected, dict):
                        raise ValueError("corrected_payload must be an object")
                    self._json(
                        HTTPStatus.OK,
                        service.review_evidence(
                            str(body.get("evidence_id") or "").strip(),
                            str(body.get("decision") or "").strip(),
                            str(body.get("reason") or "").strip(),
                            corrected,
                        ),
                    )
                    return
                if endpoint == "/api/research-runs/upload":
                    if not isinstance(service, CorpusCatalogService):
                        raise ValueError("online research is not configured")
                    self._json(
                        HTTPStatus.OK,
                        service.add_authorized_full_text(
                            str(body.get("run_id") or "").strip(),
                            str(body.get("candidate_id") or "").strip(),
                            filename=str(body.get("filename") or "").strip(),
                            content_base64=str(body.get("content_base64") or ""),
                            authorization_confirmed=body.get("authorization_confirmed") is True,
                        ),
                    )
                    return
                question = str(body.get("question") or "").strip()
                session_id = str(body.get("session_id") or "").strip() or None
                corpus_id = str(body.get("corpus_id") or "").strip() or None
                question_brief = body.get("question_brief")
                if question_brief is not None and not isinstance(question_brief, dict):
                    raise ValueError("question_brief must be an object")
                if not question:
                    raise ValueError("question is required")
                if endpoint == "/api/research-runs":
                    if not isinstance(service, CorpusCatalogService):
                        raise ValueError("online research is not configured")
                    review_mode = str(body.get("review_mode") or "research").strip().lower()
                    if review_mode not in REVIEW_PROFILES:
                        raise ValueError("review_mode must be quick, research, or deep")
                    profile = REVIEW_PROFILES[review_mode]
                    full_text_budget = _bounded_integer(
                        body.get("max_full_texts"),
                        default=profile["maximum"],
                        minimum=1,
                        maximum=100,
                    )
                    acquisition_attempts = _bounded_integer(
                        body.get("max_acquisition_attempts"),
                        default=profile["attempts"],
                        minimum=full_text_budget,
                        maximum=200,
                    )
                    limits = ResearchLimits(
                        per_query=_bounded_integer(
                            body.get("per_query"),
                            default=profile["per_query"],
                            minimum=5,
                            maximum=100,
                        ),
                        max_selected=_bounded_integer(
                            body.get("max_selected"),
                            default=profile["selected"],
                            minimum=5,
                            maximum=100,
                        ),
                        max_full_texts=full_text_budget,
                        max_acquisition_attempts=acquisition_attempts,
                        citation_seed_count=_bounded_integer(
                            body.get("citation_seed_count"),
                            default=profile["seeds"],
                            minimum=0,
                            maximum=10,
                        ),
                        citation_neighbors_per_seed=_bounded_integer(
                            body.get("citation_neighbors_per_seed"),
                            default=profile["neighbors"],
                            minimum=0,
                            maximum=100,
                        ),
                        citation_depth=_bounded_integer(
                            body.get("citation_depth"), default=1, minimum=0, maximum=2
                        ),
                        review_mode=review_mode,
                        initial_full_texts=_bounded_integer(
                            body.get("initial_full_texts"),
                            default=profile["initial"],
                            minimum=1,
                            maximum=100,
                        ),
                        acquisition_batch_size=_bounded_integer(
                            body.get("acquisition_batch_size"),
                            default=profile["batch"],
                            minimum=1,
                            maximum=50,
                        ),
                        saturation_patience=_bounded_integer(
                            body.get("saturation_patience"), default=2, minimum=1, maximum=5
                        ),
                    )
                    self._json(
                        HTTPStatus.ACCEPTED,
                        service.start_research(
                            question,
                            limits=limits,
                            question_brief=question_brief,
                        ),
                    )
                    return
                self._json(
                    HTTPStatus.OK,
                    service.investigate(
                        question,
                        session_id=session_id,
                        corpus_id=corpus_id,
                        question_brief=question_brief,
                    )
                    if isinstance(service, CorpusCatalogService)
                    else service.investigate(
                        question,
                        session_id=session_id,
                        question_brief=question_brief,
                    ),
                )
            except KeyError as exc:
                self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
            self._send(
                status, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8"
            )

        def _send(self, status: HTTPStatus, payload: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                # Navigation and cancelled downloads can close the client socket
                # after this stateless response has already been prepared.
                return

        def _download(self, payload: bytes, content_type: str, filename: str) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                return

    return SciSearchHandler


def create_server(
    host: str, port: int, service: ResearchService | CorpusCatalogService
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), create_handler(service))


def run_server(host: str, port: int, service: ResearchService | CorpusCatalogService) -> None:
    server = create_server(host, port, service)
    print(f"Sci-Search researcher UI running at http://{host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _bounded_integer(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    if value is None or value == "":
        return default
    number = int(value)
    if not minimum <= number <= maximum:
        raise ValueError(f"value must be between {minimum} and {maximum}")
    return number
