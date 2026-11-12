"""Bounded XLSX inspection and explicit rectangular-sheet extraction; no formula execution."""

import csv
import hashlib
import io
import json
import posixpath
import re
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
SELECTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "sheet_index": {"type": "integer"},
        "header_row": {"type": "integer"},
        "reason": {"type": "string"},
    },
    "required": ["sheet_index", "header_row", "reason"],
}


def _archive(body):
    z = zipfile.ZipFile(io.BytesIO(body))
    entries = z.infolist()
    names = [e.filename for e in entries]
    if len(entries) > 200 or sum(e.file_size for e in entries) > 20_000_000:
        z.close()
        raise ValueError("Workbook package exceeds inspection size limits")
    if (
        len(set(names)) != len(names)
        or any(
            PurePosixPath(n).is_absolute() or ".." in PurePosixPath(n).parts or "\\" in n
            for n in names
        )
        or any(e.flag_bits & 1 for e in entries)
    ):
        z.close()
        raise ValueError("Unsafe or encrypted workbook package")
    return z


def _xml(z, name):
    body = z.read(name)
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ValueError("XML entity declarations are unsupported")
    return ET.fromstring(body)


def _load(body):
    metadata = ""
    entry = ""
    with _archive(body) as outer:
        if "xl/workbook.xml" not in outer.namelist():
            files = [n for n in outer.namelist() if n.lower().endswith(".xlsx")]
            if len(files) != 1:
                raise ValueError("Package requires exactly one XLSX workbook")
            entry = files[0]
            metadata = "\n".join(
                n + "\n" + outer.read(n)[:20000].decode("utf-8", errors="replace")
                for n in outer.namelist()
                if n.lower().endswith((".md", ".txt", ".xml"))
                and outer.getinfo(n).file_size < 100000
            )[:40000]
            body = outer.read(entry)
    with _archive(body) as z:
        strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            strings = [
                "".join(e.itertext()) for e in _xml(z, "xl/sharedStrings.xml").findall("s:si", NS)
            ]
        formats = [(0, "General")]
        if "xl/styles.xml" in z.namelist():
            styles = _xml(z, "xl/styles.xml")
            custom = {
                int(e.attrib["numFmtId"]): e.attrib["formatCode"]
                for e in styles.findall("s:numFmts/s:numFmt", NS)
            }
            bases = styles.findall("s:cellStyleXfs/s:xf", NS)
            formats = []
            for xf in styles.findall("s:cellXfs/s:xf", NS):
                base_index = int(xf.get("xfId", "0"))
                if base_index < 0 or (base_index and base_index >= len(bases)):
                    raise ValueError("Invalid inherited worksheet number format")
                inherited = bases[base_index].get("numFmtId", "0") if bases else "0"
                fmt = int(
                    inherited
                    if xf.get("applyNumberFormat") == "0"
                    else xf.get("numFmtId", inherited)
                )
                formats.append(
                    (
                        fmt,
                        custom.get(
                            fmt,
                            {0: "General", 9: "0%", 10: "0.00%"}.get(
                                fmt, f"Excel built-in format {fmt}"
                            ),
                        ),
                    )
                )
            if not formats:
                formats = [(0, "General")]
        rels = {r.attrib["Id"]: r.attrib for r in _xml(z, "xl/_rels/workbook.xml.rels")}
        sheets = []
        for sheet in _xml(z, "xl/workbook.xml").findall("s:sheets/s:sheet", NS):
            rid = sheet.attrib[
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            ]
            rel = rels[rid]
            if rel.get("TargetMode") == "External":
                raise ValueError("External worksheet relationship is unsupported")
            path = (
                posixpath.normpath(posixpath.join("xl", rel["Target"]))
                if not rel["Target"].startswith("/")
                else rel["Target"].lstrip("/")
            )
            if not path.startswith("xl/"):
                raise ValueError("Invalid worksheet relationship")
            rows = []
            worksheet = _xml(z, path)
            column_styles = [
                (int(c.attrib["min"]), int(c.attrib["max"]), c.attrib["style"])
                for c in worksheet.findall("s:cols/s:col", NS)
                if "style" in c.attrib
            ]
            for row in worksheet.findall("s:sheetData/s:row", NS):
                cells = {}
                for cell in row.findall("s:c", NS):
                    ref = cell.get("r", "")
                    match = re.fullmatch(r"([A-Z]+)([0-9]+)", ref)
                    if not match:
                        raise ValueError("Workbook cell has no valid coordinate")
                    col = 0
                    for char in match[1]:
                        col = col * 26 + ord(char) - 64
                    if col - 1 in cells or int(match[2]) != int(row.attrib["r"]):
                        raise ValueError("Duplicate or inconsistent worksheet cell coordinate")
                    if col > 300:
                        raise ValueError("Worksheet exceeds 300-column inspection limit")
                    value = cell.findtext("s:v", default="", namespaces=NS)
                    if cell.get("t") == "s":
                        string_index = int(value)
                        if not 0 <= string_index < len(strings):
                            raise ValueError("Invalid workbook shared string reference")
                        value = strings[string_index]
                    elif cell.get("t") == "inlineStr":
                        inline = cell.find("s:is", NS)
                        value = "".join(inline.itertext()) if inline is not None else ""
                    elif value and cell.get("t", "n") == "n":
                        defaults = {
                            style for low, high, style in column_styles if low <= col <= high
                        }
                        if len(defaults) > 1:
                            raise ValueError("Ambiguous column number formats")
                        default_style = next(iter(defaults), "0")
                        if row.get("customFormat", "1") != "0":
                            default_style = row.get("s", default_style)
                        style_index = int(cell.get("s", default_style))
                        if not 0 <= style_index < len(formats):
                            raise ValueError("Invalid workbook style reference")
                        fmt, code = formats[style_index]
                        if fmt not in {*range(0, 9), 11, 12, 13, *range(37, 45), 48, 49}:
                            value = {
                                "raw_value": value,
                                "number_format": code,
                                "number_format_id": fmt,
                            }

                    if cell.find("s:f", NS) is not None:
                        # Never silently turn an uncached formula into a missing observation.
                        value = {"formula": True, "cached": value}
                    cells[col - 1] = value
                while cells and cells[max(cells)] == "":
                    del cells[max(cells)]
                if cells:
                    rows.append(
                        {
                            "row": int(row.attrib["r"]),
                            "cells": [cells.get(i, "") for i in range(max(cells) + 1)],
                        }
                    )
                if len(rows) > 50000:
                    raise ValueError("Worksheet exceeds 50000-row inspection limit")
            sheets.append({"name": sheet.attrib["name"], "rows": rows})
        if len(sheets) > 40:
            raise ValueError("Workbook exceeds 40-sheet inspection limit")
    return sheets, metadata, entry


def inspect_workbook(body):
    sheets, metadata, entry = _load(body)
    return {
        "entry": entry,
        "metadata": metadata,
        "sheets": [
            {
                "index": i,
                "name": sheet["name"],
                "row_count": len(sheet["rows"]),
                "sample_rows": sheet["rows"][:12],
                "text_values": list(
                    dict.fromkeys(
                        str(v)
                        for r in sheet["rows"]
                        for v in r["cells"]
                        if isinstance(v, str) and v and not re.fullmatch(r"[-+\d.,% ]+", v)
                    )
                )[:150],
            }
            for i, sheet in enumerate(sheets)
        ],
    }


def workbook_table(body, selection):
    sheets, metadata, entry = _load(body)
    index, header = selection["sheet_index"], selection["header_row"]
    if (
        type(index) is not int
        or type(header) is not int
        or not 0 <= index < len(sheets)
        or header < 1
    ):
        raise ValueError("Invalid worksheet or header selection")
    sheet = sheets[index]
    row = next((r for r in sheet["rows"] if r["row"] == header), None)
    if row is None:
        raise ValueError("Selected header row does not exist")
    headers = row["cells"]
    if any(not isinstance(h, str) or not h.strip() for h in headers) or len(set(headers)) != len(
        headers
    ):
        raise ValueError("Selected sheet requires unique, non-empty column headers")
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    provenance = {}
    physical_line = 2 + sum(len(re.findall(r"\r\n|\r|\n", h)) for h in headers)
    for r in sheet["rows"]:
        if r["row"] <= header:
            continue
        values = r["cells"]
        if len(values) > len(headers):
            raise ValueError("Worksheet data extends beyond the selected header")
        if any(isinstance(v, dict) and v.get("formula") for v in values):
            raise ValueError("Selected worksheet contains formulas; request published values")
        if any(isinstance(v, dict) for v in values):
            raise ValueError(
                "Selected worksheet contains a number format requiring explicit conversion (percentage, date or custom scaling)"
            )
        writer.writerow(values + [""] * (len(headers) - len(values)))
        provenance[str(physical_line)] = {
            "source_reference": (entry + ":" if entry else "") + sheet["name"] + "!" + str(r["row"])
        }
        physical_line += 1 + sum(len(re.findall(r"\r\n|\r|\n", v)) for v in values)
    data = output.getvalue().encode()
    return data, {
        "format": "xlsx_table_v1",
        "selection": selection,
        "entry": entry,
        "metadata": metadata + "\n" + json.dumps(sheet["rows"][:12], ensure_ascii=False),
        "row_provenance": provenance,
        "normalized_sha256": hashlib.sha256(data).hexdigest(),
        "limitations": [
            "Worksheet selected explicitly; no formulas were evaluated and no series were aggregated.",
            "Excel date serials and cross-tabulated tables require a separate documented conversion.",
        ],
    }


def inspect_if_workbook(body):
    if not body.startswith(b"PK"):
        return None
    with _archive(body) as z:
        if "xl/workbook.xml" not in z.namelist() and not any(
            n.lower().endswith(".xlsx") for n in z.namelist()
        ):
            return None
    return inspect_workbook(body)
