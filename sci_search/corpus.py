"""Local, inspectable full-text corpus loading."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sci_search.models import EvidenceType, Publication, ResultNature
from sci_search.pdf_ingestion import extract_pdf_text
from sci_search.xml_ingestion import extract_scientific_xml_text


@dataclass(frozen=True, slots=True)
class SourcePassage:
    text: str
    section: str
    page: int | None
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class CorpusDocument:
    publication: Publication
    text: str
    evidence_type: EvidenceType
    result_nature: ResultNature
    technology: str
    configuration: str | None
    system_scale: str | None
    calculation_boundary: str | None
    assumptions: tuple[str, ...]
    chemistry: str | None = None
    reviewed_results: tuple[dict[str, Any], ...] | None = None

    def passages(self) -> tuple[SourcePassage, ...]:
        return tuple(_passages(self.text))


def load_corpus(directory: Path) -> tuple[CorpusDocument, ...]:
    manifest_path = directory / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = data.get("documents")
    if not isinstance(records, list):
        raise ValueError("corpus manifest documents must be a list")
    documents: list[CorpusDocument] = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("corpus document entries must be objects")
        relative_path = _text(record, "path")
        source_path = directory / relative_path
        if not source_path.is_file():
            raise ValueError(f"source document does not exist: {relative_path}")
        publication = Publication(
            id=_text(record, "id"),
            title=_text(record, "title"),
            source_document=relative_path,
            doi=_optional_text(record.get("doi")),
            year=record.get("year") if isinstance(record.get("year"), int) else None,
            fixture_status=_optional_text(record.get("fixture_status")),
            authors=tuple(
                str(item).strip() for item in record.get("authors", []) if str(item).strip()
            ),
            document_type=_optional_text(record.get("document_type")) or "article",
            source_url=_optional_text(record.get("source_url")),
            access_url=_optional_text(record.get("access_url")),
            license=_optional_text(record.get("license")),
            access_status=_optional_text(record.get("access_status")),
        )
        documents.append(
            CorpusDocument(
                publication=publication,
                text=_document_text(source_path),
                evidence_type=EvidenceType(_text(record, "evidence_type")),
                result_nature=ResultNature(_text(record, "result_nature")),
                technology=_text(record, "technology"),
                configuration=_optional_text(record.get("configuration")),
                system_scale=_optional_text(record.get("system_scale")),
                calculation_boundary=_optional_text(record.get("calculation_boundary")),
                assumptions=tuple(
                    str(item).strip() for item in record.get("assumptions", []) if str(item).strip()
                ),
                chemistry=_optional_text(record.get("chemistry")),
                reviewed_results=_reviewed_results(directory, record),
            )
        )
    return tuple(documents)


def _passages(text: str) -> list[SourcePassage]:
    page: int | None = None
    section = "unknown"
    passages: list[SourcePassage] = []
    offset = 0
    paragraph_start: int | None = None
    paragraph_end: int | None = None

    def flush() -> None:
        nonlocal paragraph_start, paragraph_end
        if paragraph_start is not None and paragraph_end is not None:
            raw = text[paragraph_start:paragraph_end]
            leading = len(raw) - len(raw.lstrip())
            trailing = len(raw.rstrip())
            value = raw.strip()
            if value:
                passages.append(
                    SourcePassage(
                        value, section, page, paragraph_start + leading, paragraph_start + trailing
                    )
                )
        paragraph_start = None
        paragraph_end = None

    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        page_match = re.fullmatch(r"\[PAGE\s+(\d+)\]", stripped, re.IGNORECASE)
        section_match = re.fullmatch(r"##\s+(.+)", stripped)
        if page_match:
            flush()
            page = int(page_match.group(1))
        elif section_match:
            flush()
            section = section_match.group(1).strip().lower().replace(" ", "_")
        elif not stripped:
            flush()
        else:
            if paragraph_start is None:
                paragraph_start = offset
            paragraph_end = offset + len(line)
        offset += len(line)
    flush()
    return passages


def _text(record: dict[str, Any], key: str) -> str:
    value = str(record.get(key) or "").strip()
    if not value:
        raise ValueError(f"corpus field {key} is required")
    return value


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _document_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_text(path)
    if suffix in {".xml", ".nxml"}:
        return extract_scientific_xml_text(path)
    return path.read_text(encoding="utf-8")


def summarize_document_parse_error(exc: Exception, path: Path) -> str:
    """Return an audit-safe parse failure without exposing a local filesystem path."""
    message = " ".join(str(exc).split())
    for value in (str(path), str(path.resolve())):
        message = message.replace(value, "the acquired document")
    if path.suffix.lower() == ".pdf" and "too little extractable text" in message.casefold():
        message = "PDF contains too little extractable text; OCR may be required"
    elif not message:
        message = "the acquired document could not be parsed"
    return f"{type(exc).__name__}: {message[:400]}"


def _reviewed_results(directory: Path, record: dict[str, Any]) -> tuple[dict[str, Any], ...] | None:
    annotation_path = _optional_text(record.get("reviewed_results_path"))
    if annotation_path is None:
        return None
    payload = json.loads((directory / annotation_path).read_text(encoding="utf-8"))
    results = payload.get("results")
    if not isinstance(results, list) or not all(isinstance(item, dict) for item in results):
        raise ValueError(f"reviewed results must be a list of objects: {annotation_path}")
    return tuple(results)
