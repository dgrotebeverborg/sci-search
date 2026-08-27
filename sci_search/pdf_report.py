"""Small dependency-free PDF renderer for portable research reports."""

from __future__ import annotations

import re
import textwrap

_PAGE_WIDTH = 595
_PAGE_HEIGHT = 842
_LEFT = 54
_RIGHT = 54
_TOP = 66
_BOTTOM = 52


def markdown_to_pdf(markdown: str, *, title: str = "Sci-Search literature review") -> bytes:
    """Render the review's deliberately simple Markdown as an extractable PDF."""
    pages: list[list[tuple[str, float, float, float, str]]] = []
    current: list[tuple[str, float, float, float, str]] = []
    y = _PAGE_HEIGHT - _TOP

    def new_page() -> None:
        nonlocal current, y
        if current:
            pages.append(current)
        current = []
        y = _PAGE_HEIGHT - _TOP

    def add_line(text: str, size: float, font: str, *, indent: float = 0, gap: float = 0) -> None:
        nonlocal y
        line_height = size * 1.35
        if y - line_height < _BOTTOM:
            new_page()
        current.append((_pdf_text(text), _LEFT + indent, y, size, font))
        y -= line_height + gap

    for raw in markdown.splitlines():
        stripped = raw.strip()
        if not stripped:
            y -= 5
            continue
        level = len(stripped) - len(stripped.lstrip("#"))
        if level and stripped[level : level + 1] == " ":
            text = _plain(stripped[level + 1 :])
            size = {1: 20, 2: 15, 3: 12}.get(level, 11)
            if y < _BOTTOM + size * 3:
                new_page()
            add_line(text, size, "F2", gap=4)
            continue
        if stripped.startswith("|---"):
            continue
        prefix = ""
        indent = 0
        if stripped.startswith("- "):
            prefix, stripped, indent = "- ", stripped[2:], 10
        elif stripped.startswith("> "):
            prefix, stripped, indent = "| ", stripped[2:], 12
        elif stripped.startswith("|"):
            stripped = "  |  ".join(part.strip() for part in stripped.strip("|").split("|"))
        text = prefix + _plain(stripped)
        width = max(30, int((_PAGE_WIDTH - _LEFT - _RIGHT - indent) / 5.25))
        wrapped = textwrap.wrap(
            text, width=width, break_long_words=False, break_on_hyphens=False
        ) or [""]
        font = "F2" if raw.startswith("**") else "F1"
        for line in wrapped:
            add_line(line, 9.5, font, indent=indent)

    if current or not pages:
        pages.append(current)
    return _assemble_pdf(pages, title)


def _plain(value: str) -> str:
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = re.sub(r"\*([^*]+)\*", r"\1", value)
    return value.replace("—", "-").replace("–", "-").replace("→", "->")


def _pdf_text(value: str) -> str:
    encoded = value.encode("cp1252", errors="replace").decode("latin-1")
    return encoded.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _assemble_pdf(pages: list[list[tuple[str, float, float, float, str]]], title: str) -> bytes:
    objects: list[bytes] = []

    def add(payload: bytes) -> int:
        objects.append(payload)
        return len(objects)

    catalog_id = add(b"")
    pages_id = add(b"")
    regular_id = add(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    bold_id = add(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
    )
    page_ids: list[int] = []
    for page_number, lines in enumerate(pages, 1):
        commands = ["q 1 0.8039 0 rg 0 818 595 24 re f Q"]
        for text, x, y, size, font in lines:
            commands.append(f"BT /{font} {size:g} Tf {x:g} {y:g} Td ({text}) Tj ET")
        footer = _pdf_text(f"Sci-Search | {title[:64]} | page {page_number} of {len(pages)}")
        commands.append(f"BT /F1 7 Tf 54 28 Td ({footer}) Tj ET")
        stream = "\n".join(commands).encode("latin-1")
        content_id = add(
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )
        page_id = add(
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 {regular_id} 0 R /F2 {bold_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>".encode()
        )
        page_ids.append(page_id)
    objects[catalog_id - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode()
    kids = " ".join(f"{item} 0 R" for item in page_ids)
    objects[pages_id - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, payload in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode())
        output.extend(payload)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(output)
