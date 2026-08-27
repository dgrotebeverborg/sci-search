"""Lawful, bounded full-text acquisition from trusted scholarly repositories."""

from __future__ import annotations

import gzip
import os
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sci_search.discovery import PublicationCandidate
from sci_search.xml_ingestion import extract_tei_bytes

BytesFetcher = Callable[[str, dict[str, str]], tuple[bytes, str]]


@dataclass(frozen=True, slots=True)
class AcquisitionOutcome:
    publication_id: str
    status: str
    source: str | None
    relative_path: str | None
    content_type: str | None
    byte_count: int
    text_char_count: int
    error: str | None = None
    download_relative_path: str | None = None
    download_source: str | None = None


def acquire_full_text(
    candidate: PublicationCandidate,
    corpus_directory: Path,
    *,
    openalex_api_key: str,
    fetch_bytes: BytesFetcher | None = None,
) -> AcquisitionOutcome:
    fetch = fetch_bytes or _fetch_bytes
    papers = corpus_directory / "papers"
    papers.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    safe_id = re.sub(r"[^a-zA-Z0-9._-]+", "-", candidate.id).strip("-")
    if candidate.pmcid:
        url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{candidate.pmcid}/fullTextXML"
        try:
            body, content_type = fetch(url, {})
            body, content_type = _decode_transfer(body, content_type)
            _validate_jats(body)
            path = papers / f"{safe_id}.xml"
            path.write_bytes(body)
            relative = path.relative_to(corpus_directory).as_posix()
            return AcquisitionOutcome(
                candidate.id,
                "acquired",
                "europe_pmc",
                relative,
                content_type,
                len(body),
                _xml_text_length(body),
                "; ".join(errors) or None,
                relative,
                "europe_pmc",
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, ET.ParseError) as exc:
            errors.append(f"Europe PMC: {type(exc).__name__}: {exc}")
    if candidate.is_open_access and candidate.full_text_url:
        try:
            body, content_type = fetch(candidate.full_text_url, {})
            body, content_type = _decode_transfer(body, content_type)
            if not body.startswith(b"%PDF-"):
                raise ValueError("download did not contain a PDF signature")
            path = papers / f"{safe_id}.pdf"
            path.write_bytes(body)
            relative = path.relative_to(corpus_directory).as_posix()
            return AcquisitionOutcome(
                candidate.id,
                "acquired",
                "publisher_oa_pdf",
                relative,
                content_type,
                len(body),
                0,
                "; ".join(errors) or None,
                relative,
                "publisher_oa_pdf",
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            errors.append(f"Publisher OA PDF: {type(exc).__name__}: {exc}")
    openalex_work_id = _openalex_work_id(candidate.openalex_id)
    if openalex_work_id and candidate.is_open_access and candidate.has_structured_fulltext:
        url = f"https://content.openalex.org/works/{openalex_work_id}.grobid-xml"
        try:
            body, content_type = fetch(url, {"api_key": openalex_api_key})
            body, content_type = _decode_transfer(body, content_type)
            text = tei_xml_to_text(body)
            if len(text) < 1000:
                raise ValueError("structured full text contains fewer than 1000 text characters")
            path = papers / f"{safe_id}.xml"
            path.write_bytes(body)
            relative = path.relative_to(corpus_directory).as_posix()
            download_relative = relative
            download_source = "openalex_grobid"
            if candidate.has_pdf:
                pdf_url = f"https://content.openalex.org/works/{openalex_work_id}.pdf"
                try:
                    pdf_body, _ = fetch(pdf_url, {"api_key": openalex_api_key})
                    pdf_body, _ = _decode_transfer(pdf_body, "application/pdf")
                    if not pdf_body.startswith(b"%PDF-"):
                        raise ValueError("download did not contain a PDF signature")
                    pdf_path = papers / f"{safe_id}.pdf"
                    pdf_path.write_bytes(pdf_body)
                    download_relative = pdf_path.relative_to(corpus_directory).as_posix()
                    download_source = "openalex_pdf"
                except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
                    errors.append(f"OpenAlex PDF: {type(exc).__name__}: {exc}")
            return AcquisitionOutcome(
                candidate.id,
                "acquired",
                "openalex_grobid",
                relative,
                content_type,
                len(body),
                len(text),
                "; ".join(errors) or None,
                download_relative,
                download_source,
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, ET.ParseError) as exc:
            errors.append(f"OpenAlex XML: {type(exc).__name__}: {exc}")
    if openalex_work_id and candidate.is_open_access and candidate.has_pdf:
        url = f"https://content.openalex.org/works/{openalex_work_id}.pdf"
        try:
            body, content_type = fetch(url, {"api_key": openalex_api_key})
            body, content_type = _decode_transfer(body, content_type)
            if not body.startswith(b"%PDF-"):
                raise ValueError("download did not contain a PDF signature")
            path = papers / f"{safe_id}.pdf"
            path.write_bytes(body)
            relative = path.relative_to(corpus_directory).as_posix()
            return AcquisitionOutcome(
                candidate.id,
                "acquired",
                "openalex_pdf",
                relative,
                content_type,
                len(body),
                0,
                "; ".join(errors) or None,
                relative,
                "openalex_pdf",
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            errors.append(f"OpenAlex PDF: {type(exc).__name__}: {exc}")
    return AcquisitionOutcome(
        candidate.id,
        "failed",
        None,
        None,
        None,
        0,
        0,
        "; ".join(errors) or "no trusted open full-text location was available",
    )


def tei_xml_to_text(body: bytes) -> str:
    return extract_tei_bytes(body, source_label="OpenAlex GROBID XML")


def _fetch_bytes(base_url: str, params: dict[str, str]) -> tuple[bytes, str]:
    url = base_url + ("?" + urlencode(params) if params else "")
    request = Request(
        url,
        headers={
            "Accept": "application/xml,text/xml,application/pdf",
            "User-Agent": "Sci-Search/0.2 (open scientific full-text acquisition)",
        },
    )
    # A single unresponsive publisher must not stall an entire multi-paper
    # review for several minutes. Values remain configurable for constrained
    # networks, but are bounded so accidental settings cannot remove the cap.
    timeout = min(60.0, max(5.0, float(os.environ.get("SCI_SEARCH_FETCH_TIMEOUT_SECONDS", "30"))))
    attempts = min(3, max(1, int(os.environ.get("SCI_SEARCH_FETCH_ATTEMPTS", "2"))))
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=timeout) as response:
                content_type = response.headers.get("Content-Type", "")
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > 50_000_000:
                    raise ValueError("full text exceeds the 50 MB acquisition limit")
                body = response.read(50_000_001)
            if len(body) > 50_000_000:
                raise ValueError("full text exceeds the 50 MB acquisition limit")
            return _decode_transfer(body, content_type)
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                raise
        except (URLError, TimeoutError):
            if attempt == attempts - 1:
                raise
        time.sleep(2**attempt)
    raise RuntimeError("full-text request exhausted retries")


def _validate_jats(body: bytes) -> None:
    root = ET.fromstring(body)
    if root.find(".//body") is None and root.find(".//{*}body") is None:
        raise ValueError("Europe PMC response has no article body")
    if _xml_text_length(body) < 1000:
        raise ValueError("Europe PMC full text contains fewer than 1000 text characters")


def _xml_text_length(body: bytes) -> int:
    root = ET.fromstring(body)
    return len(" ".join("".join(root.itertext()).split()))


def _element_text(element: ET.Element | None) -> str:
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def _openalex_work_id(value: str | None) -> str | None:
    match = re.search(r"W\d+", str(value or ""), re.IGNORECASE)
    return match.group(0).upper() if match else None


def _decode_transfer(body: bytes, content_type: str) -> tuple[bytes, str]:
    if body.startswith(b"\x1f\x8b") or "gzip" in content_type.lower():
        return gzip.decompress(body), "application/xml"
    return body, content_type
