"""Page-preserving local PDF ingestion.

PDFs remain the source documents.  The generated text is an in-memory analysis
view with explicit page and conservative section markers so every extracted
passage can be traced back to the original file.
"""

from __future__ import annotations

import re
from pathlib import Path

_KNOWN_HEADINGS = re.compile(
    r"^(?:\d+(?:\.\d+)*\.?\s+)?(abstract|introduction|background|materials(?: and methods)?|"
    r"methods?|experimental(?: procedure)?|model(?: description)?|results(?: and discussion)?|"
    r"discussion|conclusions?|limitations?|acknowledg(?:e)?ments?|references)\s*$",
    re.IGNORECASE,
)


def extract_pdf_text(path: Path) -> str:
    """Return page-aware text extracted with pypdf.

    A hard failure is preferable to silently treating a broken or scanned PDF
    as an empty scientific source.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError("PDF ingestion requires the 'pypdf' package") from exc

    try:
        reader = PdfReader(path)
    except Exception as exc:  # pypdf exposes several parser-specific errors
        raise ValueError(f"could not read PDF {path}: {exc}") from exc
    pages: list[str] = []
    extracted_characters = 0
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            # Reading-order extraction keeps two-column scientific prose in
            # coherent paragraphs. Layout mode visually aligns columns but can
            # interleave their lines and concatenate words, corrupting claims.
            raw = page.extract_text() or ""
        except KeyError:
            # Some valid PDFs represent blank pages without a /Contents entry.
            raw = ""
        normalized = _normalize_page(raw)
        extracted_characters += len(normalized)
        pages.append(f"[PAGE {page_number}]\n{normalized}".rstrip())
    if extracted_characters < 100:
        raise ValueError(f"PDF contains too little extractable text (OCR may be required): {path}")
    return "\n\n".join(pages) + "\n"


def _normalize_page(text: str) -> str:
    lines: list[str] = []
    for raw_line in text.replace("\u00ad", "").splitlines():
        line = " ".join(raw_line.split())
        if not line:
            if lines and lines[-1]:
                lines.append("")
            continue
        heading = _KNOWN_HEADINGS.fullmatch(line)
        if heading:
            lines.extend(("", f"## {heading.group(1).title()}", ""))
        else:
            lines.append(line)
    return "\n".join(lines).strip()
