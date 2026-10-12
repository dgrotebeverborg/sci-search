"""Decode bounded data packages into inspectable tables, preserving source coordinates."""

import csv
import hashlib
import io
import json
import re
import zipfile
from pathlib import PurePosixPath

try:
    from .tabular import read_csv
except ImportError:  # Standalone, retained offline reproduction package.
    from tabular import read_csv


def prepare_table(body, selection=None):
    if selection is not None and selection.get("reader") == "statistical_tsv":
        try:
            from .statistical_tables import prepare_statistics
        except ImportError:
            from statistical_tables import prepare_statistics
        return prepare_statistics(body, selection)
    if body.startswith(b"\x1f\x8b"):
        try:
            from .statistical_tables import decompress
        except ImportError:
            from statistical_tables import decompress
        normalized, preparation = prepare_table(decompress(body), selection)
        preparation["compression"] = "gzip"
        if preparation["format"] == "csv":
            preparation["format"] = "gzip_csv_v1"
        return normalized, preparation
    if selection is not None and selection.get("reader") == "delimited":
        try:
            from .preparation import prepare_delimited
        except ImportError:
            from preparation import prepare_delimited
        return prepare_delimited(body, selection)
    if selection is not None:
        try:
            from .spreadsheets import workbook_table
        except ImportError:
            from spreadsheets import workbook_table
        return workbook_table(body, selection)

    if not body.startswith(b"PK"):
        try:
            if len(read_csv(body)[0]) < 2:
                raise ValueError(
                    "Annual tables require at least two columns; inspect delimiter and header"
                )
            return body, {"format": "csv", "metadata": "", "limitations": []}
        except (ValueError, UnicodeError, csv.Error):
            try:
                from .preparation import prepare_delimited
            except ImportError:
                from preparation import prepare_delimited
            return prepare_delimited(body)
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(entries) > 40 or sum(e.file_size for e in entries) > 10_000_000:
            raise ValueError("Data ZIP exceeds its file-count or expanded-size limit")
        if len(set(names)) != len(names):
            raise ValueError("Data ZIP contains duplicate entry names")
        if any(
            PurePosixPath(n).is_absolute() or ".." in PurePosixPath(n).parts or "\\" in n
            for n in names
        ):
            raise ValueError("Data ZIP contains an unsafe entry path")
        if any(e.flag_bits & 1 for e in entries):
            raise ValueError("Encrypted data ZIPs are unsupported")
        if "xl/workbook.xml" in names:
            raise ValueError(
                "This download is an Excel workbook; the generic CSV reader cannot process it."
            )
        if {"Observations.csv", "MeasureCodes.csv", "Dimensions.csv", "Properties.csv"} <= set(
            names
        ):
            return _cbs(archive)
        csvs = [n for n in names if n.lower().endswith(".csv")]
        if len(csvs) != 1:
            raise ValueError(
                "This ZIP contains multiple tables or no CSV; a documented table structure is required."
            )
        data = archive.read(csvs[0])
        try:
            if len(read_csv(data)[0]) < 2:
                raise ValueError(
                    "Annual tables require at least two columns; inspect delimiter and header"
                )
        except (ValueError, UnicodeError, csv.Error):
            try:
                from .preparation import prepare_delimited
            except ImportError:
                from preparation import prepare_delimited
            return prepare_delimited(body)
        return data, {
            "format": "single_csv_zip_v1",
            "entry": csvs[0],
            "metadata": "\n\n".join(
                name + "\n" + archive.read(name).decode("utf-8-sig", errors="replace")[:12000]
                for name in names
                if name.lower().endswith((".txt", ".md"))
            )[:40000],
            "normalized_sha256": hashlib.sha256(data).hexdigest(),
            "limitations": ["Observations were read from " + csvs[0] + " inside the original ZIP."],
        }


def _cbs(archive):
    def table(name):
        if name not in archive.namelist():
            raise ValueError("CBS package is missing a required code table: " + name)
        return read_csv(archive.read(name), delimiter=";")

    def codes(name, distinct=("Title",)):
        _, rows = table(name)
        if any(not r.get("Identifier") or not r.get("Title") for r in rows):
            raise ValueError("CBS code table lacks identifiers or labels")
        values = {r["Identifier"]: r for r in rows}
        if len(values) != len(rows):
            raise ValueError("CBS code table has duplicate identifiers")
        if len({tuple(r.get(k, "") for k in distinct) for r in rows}) != len(rows):
            raise ValueError("CBS code labels are ambiguous")
        return values

    _, properties = table("Properties.csv")
    _, dims = table("Dimensions.csv")
    # Measures may repeat a title in another unit; the normalized Unit column keeps them apart.
    measures = codes("MeasureCodes.csv", distinct=("Title", "Unit"))
    obs_headers, observations, source_lines = read_csv(
        archive.read("Observations.csv"), with_line_numbers=True, delimiter=";"
    )
    if not {"Measure", "Value", "StringValue", "ValueAttribute"} <= set(obs_headers):
        raise ValueError("Unsupported CBS observation schema")
    time = [d for d in dims if d["Kind"] == "TimeDimension"]
    if len(time) != 1:
        raise ValueError("CBS annual analysis requires exactly one time dimension")
    dimensions = {}
    for dimension in dims:
        identifier = dimension["Identifier"]
        if identifier not in obs_headers:
            raise ValueError("CBS dimension is absent from observations")
        dimensions[identifier] = codes(dimension["CodesUrl"])
    time_key = time[0]["Identifier"]
    entity_keys = [d["Identifier"] for d in dims if d["Identifier"] != time_key]
    header = ["Year", "Measure", *entity_keys, "Value", "Unit", "Value attribute", "Period status"]
    if len(set(header)) != len(header):
        raise ValueError("CBS dimension names collide with normalized columns")
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=header)
    writer.writeheader()
    provenance = {}
    for index, (row, source_line) in enumerate(zip(observations, source_lines, strict=True), 2):
        measure = measures.get(row["Measure"])
        if not measure or not measure.get("Unit"):
            raise ValueError("CBS observation references an unknown measure or unspecified unit")
        period = dimensions[time_key].get(row[time_key])
        if not period or not re.fullmatch(r"(?:18|19|20|21)\d{2}JJ00", row[time_key]):
            raise ValueError(
                "CBS package contains non-annual or unknown periods; no aggregation was performed"
            )
        if period["Title"].strip() != row[time_key][:4]:
            raise ValueError("CBS period label does not match its annual code")
        labels = {}
        for key in entity_keys:
            code = dimensions[key].get(row[key])
            if not code:
                raise ValueError("CBS observation references an unknown dimension code")
            labels[key] = code["Title"]
        if row["StringValue"]:
            raise ValueError("CBS text-valued observations are unsupported")
        flag = row["ValueAttribute"]
        if flag not in {"", "None"} and row["Value"]:
            raise ValueError("CBS flagged numeric observation requires explicit interpretation")
        normalized = {
            "Year": period["Title"].strip(),
            "Measure": measure["Title"],
            **labels,
            "Value": row["Value"],
            "Unit": measure["Unit"],
            "Value attribute": flag,
            "Period status": period.get("Status", ""),
        }
        if any("\n" in v or "\r" in v for v in normalized.values()):
            raise ValueError("CBS labels with embedded newlines are unsupported")
        writer.writerow(normalized)
        provenance[str(index)] = {
            "entry": "Observations.csv",
            "source_row": source_line,
            "measure_code": row["Measure"],
            "unit": measure["Unit"],
            "period_code": row[time_key],
            "status": period.get("Status", ""),
            "value_attribute": flag,
        }
    data = output.getvalue().encode()
    description = properties[0].get("Description", "")
    metadata = json.dumps(
        {
            "dataset": properties,
            "measures": list(measures.values()),
            "dimensions": dims,
            "codes": dimensions,
        },
        ensure_ascii=False,
    )
    return data, {
        "format": "cbs_csv_zip_v1",
        "entry": "Observations.csv",
        "metadata": metadata,
        "license_url": properties[0].get("License", ""),
        "normalized_sha256": hashlib.sha256(data).hexdigest(),
        "row_provenance": provenance,
        "limitations": [
            description.split("\r\n\r\n")[0],
            "CBS dimension codes and annual period codes were resolved using the included code tables. No observations were added or aggregated.",
            "Provisional status and missing-value flags are retained. Source dimension labels describe the published groups; they do not automatically identify different technologies.",
        ],
    }


def attach_provenance(analysis, preparation):
    daily_coverage = {
        (item["entity"], item["year"]): item for item in preparation.get("daily_coverage", [])
    }
    for series in analysis["series"]:
        for row in series["annual"]:
            daily = daily_coverage.get(
                (series["entity"] if analysis["mapping"].get("entity_column") else "", row["year"])
            )
            if daily:
                row["source_status"] = (
                    f"{daily['status']}: {daily['observed_days']}/{daily['expected_days']} valid daily means"
                )
            if row["source_row"] is None:
                continue
            origin = preparation.get("row_provenance", {}).get(str(row["source_row"]))
            if origin and "source_reference" in origin:
                row["source_reference"] = origin["source_reference"]
                if preparation.get("format") == "statistical_tsv_v1":
                    if analysis["mapping"]["unit"] != origin["unit"]:
                        raise ValueError("Selected unit does not match the statistical source unit")
                    row.update(
                        source_status=origin["status"],
                        source_value=origin["source_value"],
                        source_dimensions=origin["dimensions"],
                    )
            elif origin:
                if analysis["mapping"]["unit"] != origin["unit"]:
                    raise ValueError(
                        "Selected unit does not match the CBS observation's documented unit"
                    )
                row.update(
                    source_reference=f"{origin['entry']}:{origin['source_row']}",
                    source_status=origin["status"],
                    source_value_attribute=origin["value_attribute"],
                )
            elif preparation.get("entry"):
                row["source_reference"] = f"{preparation['entry']}:{row['source_row']}"

    if preparation.get("format") == "statistical_tsv_v1":
        for series in analysis["series"]:
            flags = {
                f
                for r in series["annual"]
                for f in r.get("source_status", "").lower().replace(" ", "")
            }
            if flags - {"p", "e"}:
                series["absolute_change"] = None
                series["change_percent"] = None
                series["comparability_note"] = (
                    "Endpoint change withheld because source status flags indicate a break, differing definition or another comparability limitation."
                )
