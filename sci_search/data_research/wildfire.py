"""EFFIS country-reported forest fires. Never mix with satellite fire-event counts."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import statistics
import urllib.request
import zipfile
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree as ET

SOURCE_URL = "https://forest-fire.emergency.copernicus.eu/effis/applications/data-and-services/report_2024.xlsx"
LANDING_URL = "https://forest-fire.emergency.copernicus.eu/applications/data-and-services"
LICENSE_URL = "https://forest-fire.emergency.copernicus.eu/about-effis/data-license"
EU27 = "AUT BEL BGR HRV CYP CZE DNK EST FIN FRA DEU GRC HUN IRL ITA LVA LTU LUX MLT NLD POL PRT ROU SVK SVN ESP SWE".split()
EUROPE = sorted(
    set(
        EU27 + "ALB AND BLR BIH GBR ISL LIE MCO MDA MNE MKD NOR RUS SMR SRB CHE TUR UKR VAT".split()
    )
)
COUNTRY_NAMES = {
    "AUT": "Austria",
    "BEL": "Belgium",
    "BGR": "Bulgaria",
    "HRV": "Croatia",
    "CYP": "Cyprus",
    "CZE": "Czechia",
    "DNK": "Denmark",
    "EST": "Estonia",
    "FIN": "Finland",
    "FRA": "France",
    "DEU": "Germany",
    "GRC": "Greece",
    "HUN": "Hungary",
    "IRL": "Ireland",
    "ITA": "Italy",
    "LVA": "Latvia",
    "LTU": "Lithuania",
    "LUX": "Luxembourg",
    "MLT": "Malta",
    "NLD": "Netherlands",
    "POL": "Poland",
    "PRT": "Portugal",
    "ROU": "Romania",
    "SVK": "Slovakia",
    "SVN": "Slovenia",
    "ESP": "Spain",
    "SWE": "Sweden",
    "ALB": "Albania",
    "AND": "Andorra",
    "BLR": "Belarus",
    "BIH": "Bosnia and Herzegovina",
    "GBR": "United Kingdom",
    "ISL": "Iceland",
    "LIE": "Liechtenstein",
    "MCO": "Monaco",
    "MDA": "Moldova",
    "MNE": "Montenegro",
    "MKD": "North Macedonia",
    "NOR": "Norway",
    "RUS": "Russia",
    "SMR": "San Marino",
    "SRB": "Serbia",
    "CHE": "Switzerland",
    "TUR": "Türkiye",
    "UKR": "Ukraine",
    "VAT": "Vatican City",
}
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def propose(question: str) -> dict | None:
    text = question.casefold()
    if not (
        re.search(r"\b(?:wildfires?|forest fires?)\b", text)
        and re.search(r"\beurop(?:e|ean)?\b|\beu\b", text)
    ):
        return None
    if not re.search(r"number|count|amount|km|area|hectare", text):
        return None
    if re.search(r"last century|previous century|19th century|20th century", text):
        return None
    years = [int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", text)]
    if not years and not re.search(r"century|annual|year|trend|development|since", text):
        return None
    now = datetime.now(UTC).year
    start, end = (
        (min(years), now - 1 if len(years) == 1 and re.search(r"since|from", text) else max(years))
        if years
        else (2001, now - 1)
    )
    if not 1980 <= start <= end <= now:
        return None
    return {
        "adapter": "effis_reported_fires_v1",
        "route": "data",
        "geography": "eu27" if re.search(r"european union|\beu\b", text) else "europe",
        "start_year": start,
        "end_year": end,
    }


def validate_scope(scope: dict) -> dict:
    if scope.get("adapter") != "effis_reported_fires_v1" or scope.get("route") not in {
        "data",
        "literature",
    }:
        raise ValueError("Unsupported data-research route")
    if scope.get("geography") == "countries":
        countries = scope.get("countries")
        if (
            not isinstance(countries, list)
            or not countries
            or len(set(countries)) != len(countries)
            or not set(countries) <= set(EUROPE)
        ):
            raise ValueError("EFFIS country totals cover only the listed European countries")
    elif scope.get("geography") not in {"eu27", "europe"}:
        raise ValueError("Choose EU-27 or the listed broader European country set")
    start, end = scope.get("start_year"), scope.get("end_year")
    if (
        type(start) is not int
        or type(end) is not int
        or not 1980 <= start <= end <= datetime.now(UTC).year
    ):
        raise ValueError("Unsupported wildfire analysis years")
    return dict(scope)


def parse_number(value: str) -> float | None:
    value = re.sub(r"\s+", "", value)
    if value in {"", "-", "–", "—", ":", "NA", "n.a."}:
        return None
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Unrecognized numeric cell: {value!r}") from exc
    if not number.is_finite() or number < 0:
        raise ValueError("Non-finite or negative fire statistics")
    return float(number)


def parse_workbook(body: bytes) -> list[dict]:
    """Strict adapter for the official two-sheet layout, retaining cell coordinates."""
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        if sum(info.file_size for info in archive.infolist()) > 10_000_000:
            raise ValueError("Workbook expands beyond the supported size")
        strings = [
            "".join(node.itertext())
            for node in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("s:si", NS)
        ]
        names = [
            s.attrib["name"]
            for s in ET.fromstring(archive.read("xl/workbook.xml")).findall("s:sheets/s:sheet", NS)
        ]
        if len(names) != 2 or "Burnt area (ha)" not in names[0] or "forest fires" not in names[1]:
            raise ValueError("EFFIS workbook schema changed; review the source before analysis")
        records = {}
        for sheet_number, metric in [(1, "burned_area_ha"), (2, "fires")]:
            root = ET.fromstring(archive.read(f"xl/worksheets/sheet{sheet_number}.xml"))
            headers = {}
            seen = set()
            for row in root.findall(".//s:row", NS):
                cells = {}
                for cell in row.findall("s:c", NS):
                    ref = cell.attrib["r"]
                    value = cell.findtext("s:v", default="", namespaces=NS)
                    if cell.attrib.get("t") == "s":
                        value = strings[int(value)]
                    elif cell.attrib.get("t") == "inlineStr":
                        value = "".join(cell.find("s:is", NS).itertext())
                    if cell.find("s:f", NS) is not None:
                        raise ValueError("Unexpected formula in official data cells")
                    cells[re.sub(r"\d", "", ref)] = (value.strip(), ref)
                year = cells.get("A", ("", ""))[0]
                if year.casefold() == "year":
                    headers = {
                        column: value
                        for column, (value, _) in cells.items()
                        if re.fullmatch("[A-Z]{3}", value)
                    }
                    continue
                if not re.fullmatch(r"(?:19|20)\d{2}", year):
                    continue
                if not headers or int(year) in seen:
                    raise ValueError("Missing country headers or duplicate year")
                seen.add(int(year))
                for column, country in headers.items():
                    raw, ref = cells.get(column, ("", f"{column}{row.attrib['r']}"))
                    number = parse_number(raw)
                    if metric == "fires" and number is not None and not number.is_integer():
                        raise ValueError("Fire count is not an integer")
                    record = records.setdefault(
                        (country, int(year)),
                        {
                            "country": country,
                            "year": int(year),
                            "fires": None,
                            "burned_area_ha": None,
                            "source_cells": {},
                        },
                    )
                    record[metric] = (
                        int(number) if metric == "fires" and number is not None else number
                    )
                    record["source_cells"][metric] = {
                        "sheet": names[sheet_number - 1],
                        "cell": ref,
                        "raw": raw,
                    }
        if not records:
            raise ValueError("No country-year statistics found")
        return sorted(records.values(), key=lambda r: (r["country"], r["year"]))


def analyse(records: list[dict], *, countries: list[str], start: int, end: int) -> dict:
    index = {}
    for row in records:
        key = (row["country"], row["year"])
        if key in index:
            raise ValueError("Duplicate country-year observation")
        for metric in ("fires", "burned_area_ha"):
            value = row.get(metric)
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError("Invalid observation")
        index[key] = row
    years = list(range(start, end + 1))

    def complete(country, year):
        row = index.get((country, year), {})
        return row.get("fires") is not None and row.get("burned_area_ha") is not None

    available = [y for y in years if any(complete(c, y) for c in countries)]
    panel = [c for c in countries if available and all(complete(c, y) for y in available)]
    annual = []
    for year in years:
        present = [c for c in countries if complete(c, year)]

        def total(members, metric, year=year):
            return sum(index[(c, year)][metric] for c in members) if members else None

        def km2(value):
            return round(value / 100, 6) if value is not None else None

        fixed = panel if year in available else []
        area, fires = total(present, "burned_area_ha"), total(present, "fires")
        annual.append(
            {
                "year": year,
                "reporting_countries": len(present),
                "missing_countries": [c for c in countries if c not in present],
                "available_fires": fires,
                "available_burned_area_km2": km2(area),
                "requested_total_fires": fires if len(present) == len(countries) else None,
                "requested_total_burned_area_km2": km2(area)
                if len(present) == len(countries)
                else None,
                "panel_fires": total(fixed, "fires"),
                "panel_burned_area_km2": km2(total(fixed, "burned_area_ha")),
            }
        )
    comparisons = []
    if (
        len(available) >= 10
        and available == list(range(min(available), max(available) + 1))
        and panel
    ):
        present_rows = [r for r in annual if r["year"] in available]
        for metric, unit in [
            ("panel_fires", "reported fires/year"),
            ("panel_burned_area_km2", "km²/year"),
        ]:
            first, last = (
                statistics.mean(r[metric] for r in present_rows[:5]),
                statistics.mean(r[metric] for r in present_rows[-5:]),
            )
            comparisons.append(
                {
                    "metric": metric,
                    "unit": unit,
                    "first_period": [available[0], available[4]],
                    "last_period": [available[-5], available[-1]],
                    "first_mean": first,
                    "last_mean": last,
                    "change_percent": 100 * (last - first) / first if first else None,
                }
            )
    return {
        "annual": annual,
        "requested_countries": countries,
        "panel_countries": panel,
        "available_years": available,
        "missing_years": [y for y in years if y not in available],
        "comparisons": comparisons,
        "country_records": [
            r for r in records if r["country"] in countries and start <= r["year"] <= end
        ],
    }


def run(
    scope: dict, directory: Path, *, fetch=None, execute_script=True, check_cancelled=lambda: None
) -> dict:
    scope = validate_scope(scope)
    if fetch is None:

        def download():
            with urllib.request.urlopen(SOURCE_URL, timeout=45) as response:
                body = response.read(2_000_001)
                if len(body) > 2_000_000:
                    raise ValueError("Source download exceeds size limit")
                return body

        fetch = download

    body = fetch()
    records = parse_workbook(body)
    countries = (
        scope["countries"]
        if scope["geography"] == "countries"
        else EU27
        if scope["geography"] == "eu27"
        else EUROPE
    )
    result = analyse(records, countries=countries, start=scope["start_year"], end=scope["end_year"])
    result.update(
        country_names=COUNTRY_NAMES,
        scope=scope,
        source={
            "title": "EFFIS country totals, 2024 annual report edition",
            "url": SOURCE_URL,
            "landing_url": LANDING_URL,
            "license_url": LICENSE_URL,
            "attribution": "European Union / European Commission Joint Research Centre, EFFIS; processed by Sci-Search",
            "retrieved_at": datetime.now(UTC).isoformat(),
            "sha256": hashlib.sha256(body).hexdigest(),
            "definition": "Nationally reported number of forest fires and burned area; not satellite detections or EFFIS mapped fire-event counts.",
        },
        method={
            "version": "wildfire_fixed_panel_v1",
            "area_conversion": "km² = hectares / 100",
            "panel": "Only countries with both measures present in every available requested year contribute to the fixed panel. Missing requested years stay missing.",
            "comparison": "Mean of first five available consecutive years versus last five; descriptive change, not a significance test.",
        },
        limitations=[
            "Country reporting definitions and practices may differ or change over time. A fixed country panel controls coverage, not measurement consistency.",
            "The fixed panel is a subset and is not an estimate for all requested countries.",
            *(
                [
                    "Broader Europe uses the listed country set, including Cyprus and Türkiye; national totals do not separate transcontinental territories."
                ]
                if scope["geography"] == "europe"
                else []
            ),
            "Missing observations are not zero. Available-country totals change coverage and must not be used as a like-for-like trend.",
            "This workbook edition ends in 2024. Later years are not supplied; the current year is incomplete.",
            "Literature-based explanations and causal attribution have not been performed in this data run.",
        ],
    )
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "source.xlsx").write_bytes(body)
    if execute_script:
        from sci_search.data_research.artifacts import execute_analysis, write_replay

        result = execute_analysis(result, directory, check_cancelled=check_cancelled)
        write_replay(directory)
    (directory / "analysis.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    for name, rows in [
        ("annual", result["annual"]),
        ("country_observations", result["country_records"]),
    ]:
        with (directory / f"{name}.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["year"])
            writer.writeheader()
            writer.writerows(
                {k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in row.items()}
                for row in rows
            )
    return result


def investigation(question: str, brief: dict, result: dict) -> dict:
    years = result["available_years"]
    panel = result["panel_countries"]
    summary = (
        f"The official EFFIS workbook provides a fixed reporting panel of {len(panel)} countries for {min(years)}–{max(years)}. "
        if years and panel
        else "No complete fixed-country panel is available for this request. "
    )
    summary += "These observations do not establish the trend for every requested country or explain its causes. See the separate fire-count and burned-area results below."
    return {
        "question": question,
        "question_brief": brief,
        "data_analysis": result,
        "answer_summary": summary,
        "answer_adequacy": {"status": "partial", "can_answer_overall_question": False},
        "ai_analysis": {"status": "complete", "method": "reproducible_data_analysis", "claims": []},
        "evidence": [],
        "limitations": result["limitations"],
    }


def export(result: dict, directory: Path, *, bundle: bool = False):
    from html import escape

    if bundle:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(directory.rglob("*")):
                if (
                    path.is_file()
                    and not path.is_symlink()
                    and path.name not in {"reproduce.py", "README.txt"}
                ):
                    archive.write(path, str(path.relative_to(directory)))
            archive.writestr("wildfire.py", Path(__file__).read_text())
            archive.writestr(
                "reproduce.py",
                (directory / "reproduce.py").read_text()
                if (directory / "reproduce.py").exists()
                else 'import json\nfrom pathlib import Path\nfrom wildfire import run\ndata=json.loads(Path("analysis.json").read_text())\nrun(data["scope"],Path("reproduced"),fetch=lambda:Path("source.xlsx").read_bytes(),execute_script=False)\n',
            )
            archive.writestr(
                "README.txt",
                "EFFIS country-reported forest-fire statistics\nSource attribution and hash: analysis.json\nMissing values remain blank/null. Area: km2 = hectares / 100.\nRun python reproduce.py with Python 3.11+ to reproduce the calculations from the retained source without network access.\nA fixed reporting panel is not all Europe, and fixed coverage does not guarantee stable reporting practices.\nThis package contains no literature-based causal analysis.\n",
            )
        return "wildfire-data-and-calculations.zip", "application/zip", output.getvalue()
    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{escape(str(r[k])) if r[k] is not None else 'Missing'}</td>"
            for k in ("year", "panel_fires", "panel_burned_area_km2", "reporting_countries")
        )
        + "</tr>"
        for r in result["annual"]
    )
    notes = "".join(f"<li>{escape(note)}</li>" for note in result["limitations"])
    page = f'<!doctype html><html lang="en"><meta charset="utf-8"><title>European wildfire data analysis</title><style>body{{font:16px system-ui;max-width:1000px;margin:40px auto;padding:20px}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:8px;border-bottom:1px solid #ddd}}</style><h1>Reported forest fires and burned area</h1><p>Fixed reporting panel: {escape(", ".join(result["panel_countries"]))}</p><p>Source: <a href="{SOURCE_URL}">EFFIS country totals, 2024 report edition</a></p><p>{escape(result["source"]["definition"])}</p><ul>{notes}</ul><table><thead><tr><th>Year</th><th>Panel fire count</th><th>Panel burned area (km²)</th><th>Countries reporting both measures</th></tr></thead><tbody>{rows}</tbody></table><h2>Provenance and calculations</h2><pre style="white-space:pre-wrap">{escape(json.dumps({k: result[k] for k in ("scope", "source", "method", "comparisons")}, indent=2, ensure_ascii=False))}</pre></html>'
    return "wildfire-data-report.html", "text/html; charset=utf-8", page.encode()
