"""Lawful, bounded full-text acquisition from trusted scholarly repositories."""

from __future__ import annotations

import gzip
import ipaddress
import json
import os
import re
import socket
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

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
    source_url: str | None = None


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
    if candidate.is_open_access:
        for landing_url in candidate.oa_landing_urls[:3]:
            try:
                _validate_repository_url(landing_url)
                if fetch_bytes is None:
                    body, content_type, page_url = _fetch_repository_bytes(landing_url)
                else:
                    body, content_type = fetch(landing_url, {})
                    page_url = landing_url
                if not body.startswith(b"%PDF-"):
                    if b"<ds-app" in body and urlsplit(page_url).path.startswith("/handle/"):
                        pdf_url = _dspace_pdf_url(page_url, candidate, fetch_bytes)
                    else:
                        pdf_url = _repository_pdf_url(body, page_url, candidate)
                    if fetch_bytes is None:
                        body, content_type, page_url = _fetch_repository_bytes(
                            pdf_url, trusted_url=page_url
                        )
                    else:
                        body, content_type = fetch(pdf_url, {})
                        page_url = pdf_url
                if not body.startswith(b"%PDF-"):
                    raise ValueError("repository download did not contain a PDF signature")
                path = papers / f"{safe_id}.pdf"
                path.write_bytes(body)
                relative = path.relative_to(corpus_directory).as_posix()
                return AcquisitionOutcome(
                    candidate.id,
                    "acquired",
                    "repository_oa_pdf",
                    relative,
                    content_type,
                    len(body),
                    0,
                    "; ".join(errors) or None,
                    relative,
                    "repository_oa_pdf",
                    page_url,
                )
            except (
                HTTPError,
                URLError,
                TimeoutError,
                OSError,
                ValueError,
                TypeError,
                AttributeError,
            ) as exc:
                errors.append(f"Repository OA PDF: {type(exc).__name__}: {exc}")
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


class _RepositoryHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.metadata: dict[str, list[str]] = {}
        self.links: list[str] = []
        self.anchor: str | None = None
        self.anchor_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "meta":
            name = str(attributes.get("name") or "").lower()
            self.metadata.setdefault(name, []).append(str(attributes.get("content") or ""))
        elif tag == "a":
            link = str(attributes.get("href") or "")
            if urlsplit(link).path.lower().endswith(".pdf"):
                self.anchor = link
                self.anchor_text = []

    def handle_data(self, data: str) -> None:
        if self.anchor:
            self.anchor_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.anchor:
            if not re.search(r"supplement|supporting|related", " ".join(self.anchor_text), re.I):
                self.links.append(self.anchor)
            self.anchor = None
            self.anchor_text = []


def _validate_repository_url(url: str, *, resolve: bool = False) -> None:
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.port not in {None, 80, 443}
    ):
        raise ValueError("unsafe repository URL")
    hostname = parts.hostname.lower()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
        raise ValueError("repository URL targets a private host")
    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        addresses = []
    if resolve:
        addresses.extend(
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(hostname, parts.port or 443)
        )
    if any(not address.is_global for address in addresses):
        raise ValueError("repository URL targets a non-public address")


def _same_repository(left: str, right: str) -> bool:
    return urlsplit(left).hostname == urlsplit(right).hostname


def _repository_pdf_url(body: bytes, page_url: str, candidate: PublicationCandidate) -> str:
    if len(body) > 2_000_000:
        raise ValueError("repository landing page exceeds the 2 MB limit")
    parser = _RepositoryHTML()
    parser.feed(body.decode("utf-8", errors="replace"))
    for doi in parser.metadata.get("citation_doi", []):
        if (
            candidate.doi
            and doi.lower().removeprefix("https://doi.org/").strip() != candidate.doi.lower()
        ):
            raise ValueError("repository citation DOI does not match candidate")

    def normalize(value: str) -> str:
        return re.sub(r"[^\w]+", "", value.casefold())

    for title in parser.metadata.get("citation_title", []):
        if normalize(title) != normalize(candidate.title):
            raise ValueError("repository citation title does not match candidate")
    links = parser.metadata.get("citation_pdf_url") or parser.links
    links = list(dict.fromkeys(urljoin(page_url, link) for link in links if link))
    if len(links) != 1 or re.search(r"supplement|supporting", links[0], re.I):
        raise ValueError("repository page has no unambiguous article PDF")
    pdf_url = links[0]
    _validate_repository_url(pdf_url)
    if not _same_repository(page_url, pdf_url):
        raise ValueError("repository PDF link leaves the trusted repository")
    return pdf_url


class _RepositoryRedirects(HTTPRedirectHandler):
    max_redirections = 3
    max_repeats = 1

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_repository_url(newurl, resolve=True)
        # Handle URLs are persistent repository locators, allowed one outbound
        # resolution. Every subsequent redirect stays on that repository host.
        if (
            not _same_repository(req.full_url, newurl)
            and urlsplit(req.full_url).hostname != "hdl.handle.net"
        ):
            raise ValueError("redirect leaves the trusted repository")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch_repository_bytes(url: str, *, trusted_url: str | None = None) -> tuple[bytes, str, str]:
    _validate_repository_url(url, resolve=True)
    if trusted_url and not _same_repository(url, trusted_url):
        raise ValueError("download leaves the trusted repository")
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/pdf,application/json",
            "User-Agent": "Sci-Search/0.2 (open scientific full-text acquisition)",
        },
    )
    timeout = min(60.0, max(5.0, float(os.environ.get("SCI_SEARCH_FETCH_TIMEOUT_SECONDS", "30"))))
    with build_opener(_RepositoryRedirects()).open(request, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "")
        limit = 50_000_000 if "application/pdf" in content_type.lower() else 2_000_000
        body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError("repository response exceeds the acquisition size limit")
        return body, content_type, response.geturl()


def _dspace_pdf_url(
    page_url: str, candidate: PublicationCandidate, fetch: BytesFetcher | None
) -> str:
    """Resolve a DSpace handle with three bounded, same-host metadata requests."""

    def read_json(url: str) -> dict:
        _validate_repository_url(url)
        if not _same_repository(page_url, url):
            raise ValueError("DSpace metadata leaves the trusted repository")
        if fetch is None:
            body, _, _ = _fetch_repository_bytes(url, trusted_url=page_url)
        else:
            body, _ = fetch(url, {})
        if len(body) > 2_000_000:
            raise ValueError("DSpace metadata exceeds the 2 MB limit")
        result = json.loads(body)
        if not isinstance(result, dict):
            raise ValueError("invalid DSpace metadata")
        return result

    def link(record: dict, name: str) -> str:
        value = record.get("_links", {}).get(name, {}).get("href")
        if not isinstance(value, str):
            raise ValueError(f"DSpace metadata missing {name} link")
        return value

    handle = urlsplit(page_url).path.removeprefix("/handle/")
    item = read_json(urljoin(page_url, "/server/api/pid/find") + "?" + urlencode({"id": handle}))
    metadata = item.get("metadata", {})
    doi_values = [
        str(entry.get("value", "")).lower().removeprefix("https://doi.org/")
        for entry in metadata.get("dc.identifier.doi", [])
    ]
    title_values = [
        re.sub(r"[^\w]+", "", str(entry.get("value", "")).casefold())
        for entry in metadata.get("dc.title", [])
    ]
    title = re.sub(r"[^\w]+", "", candidate.title.casefold())
    if (candidate.doi and candidate.doi.lower() not in doi_values) or title not in title_values:
        raise ValueError("DSpace article identity does not match candidate")
    bundles = read_json(link(item, "bundles")).get("_embedded", {}).get("bundles", [])
    originals = [bundle for bundle in bundles if bundle.get("name") == "ORIGINAL"]
    if len(originals) != 1:
        raise ValueError("DSpace has no unambiguous original bundle")
    streams = read_json(link(originals[0], "bitstreams")).get("_embedded", {}).get("bitstreams", [])
    pdfs = [
        stream
        for stream in streams
        if str(stream.get("name", "")).lower().endswith(".pdf")
        and not re.search(r"supplement|supporting", str(stream.get("name", "")), re.I)
    ]
    if len(pdfs) != 1:
        raise ValueError("DSpace has no unambiguous article PDF")
    pdf_url = link(pdfs[0], "content")
    _validate_repository_url(pdf_url)
    if not _same_repository(page_url, pdf_url):
        raise ValueError("DSpace PDF leaves the trusted repository")
    return pdf_url
