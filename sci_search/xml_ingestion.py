"""Section-preserving ingestion for open-access JATS full text."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path


def extract_jats_text(path: Path) -> str:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"could not parse JATS XML {path}: {exc}") from exc
    return _extract_jats_root(root, path)


def extract_scientific_xml_text(path: Path) -> str:
    """Dispatch JATS and OpenAlex/GROBID TEI through section-aware parsers."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"could not parse scientific XML {path}: {exc}") from exc
    local_name = root.tag.split("}")[-1].lower()
    if local_name == "article":
        return _extract_jats_root(root, path)
    return extract_tei_root(root, source_label=str(path))


def extract_tei_bytes(body: bytes, *, source_label: str = "TEI XML") -> str:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise ValueError(f"could not parse {source_label}: {exc}") from exc
    return extract_tei_root(root, source_label=source_label)


def _extract_jats_root(root: ET.Element, path: Path) -> str:
    chunks: list[str] = []
    abstract = root.find(".//abstract")
    if abstract is not None:
        chunks.extend(("## Abstract", _text(abstract)))
    body = root.find(".//body")
    if body is None:
        raise ValueError(f"JATS document has no body: {path}")
    top_sections = body.findall("./sec")
    if top_sections:
        for section in top_sections:
            _append_section(section, chunks)
    else:
        for paragraph in body.findall(".//p"):
            value = _text(paragraph)
            if value:
                chunks.append(value)
    text = "\n\n".join(item for item in chunks if item.strip()).strip()
    if len(text) < 100:
        raise ValueError(f"JATS document contains too little extractable text: {path}")
    return text + "\n"


def extract_tei_root(root: ET.Element, *, source_label: str) -> str:
    chunks: list[str] = []
    abstract = root.find(".//{*}abstract")
    if abstract is not None:
        abstract_text = _tei_text(abstract)
        if abstract_text:
            chunks.extend(("## Abstract", abstract_text))
    divisions = root.findall(".//{*}text/{*}div")
    if not divisions:
        divisions = root.findall(".//{*}text/{*}body/{*}div")
    if not divisions:
        divisions = root.findall(".//{*}body//{*}div")
    for division in divisions:
        division_type = str(division.get("type") or "").lower()
        heading = _tei_heading(division)
        if division_type in {"references", "acknowledgement", "funding", "annex"}:
            continue
        if heading.lower().startswith(("figure ", "table ")):
            continue
        chunks.append("## " + (heading or "Unknown"))
        for paragraph in division.findall("./{*}p"):
            value = _tei_text(paragraph)
            if value:
                chunks.append(value)
    if not divisions:
        for paragraph in root.findall(".//{*}p"):
            value = _tei_text(paragraph)
            if value:
                chunks.append(value)
    text = "\n\n".join(item for item in chunks if item.strip()).strip()
    if len(text) < 40:
        raise ValueError(f"TEI document contains too little extractable text: {source_label}")
    return text + "\n"


def _tei_heading(division: ET.Element) -> str:
    for tag in ("head", "title"):
        element = division.find(f"./{{*}}{tag}")
        value = _tei_text(element) if element is not None else ""
        if value:
            return value
    return " ".join(str(division.text or "").split())


def _append_section(section: ET.Element, chunks: list[str]) -> None:
    title = section.find("./title")
    chunks.append("## " + (_text(title) if title is not None else "Unknown"))
    for child in section:
        if child.tag == "p":
            value = _text(child)
            if value:
                chunks.append(value)
        elif child.tag == "sec":
            _append_section(child, chunks)


def _text(element: ET.Element) -> str:
    return " ".join("".join(element.itertext()).split())


def _tei_text(element: ET.Element) -> str:
    # Joining XML text nodes with a separator prevents adjacent GROBID <s>
    # elements from becoming "sentence.One" and corrupting passage ranking.
    return " ".join(" ".join(element.itertext()).split())
