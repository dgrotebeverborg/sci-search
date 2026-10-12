"""Exports for automatically discovered datasets and combined investigations."""

import csv
import io
import json
import zipfile
from html import escape
from pathlib import Path


def export(result, directory, *, bundle=False):
    if result.get("kind") != "discovered":
        from sci_search.data_research.wildfire import export as wildfire_export

        return wildfire_export(result, directory, bundle=bundle)
    if bundle:
        required = set()
        if any(a["kind"] == "tabular" for a in result["analyses"]):
            required.update(
                (
                    "tabular.py",
                    "packages.py",
                    "preparation.py",
                    "statistical_tables.py",
                    "jsonstat.py",
                    "owid_tables.py",
                    "daily.py",
                )
            )
        if any(a["kind"] == "wildfire" for a in result["analyses"]):
            required.add("wildfire.py")
        if any(
            a.get("preparation", {}).get("format") == "xlsx_table_v1" for a in result["analyses"]
        ):
            required.add("spreadsheets.py")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(Path(directory).rglob("*")):
                if (
                    file.is_file()
                    and not file.is_symlink()
                    and file.name not in {"reproduce.py", "README.txt"}
                    and (
                        file.parent != Path(directory)
                        or file.name
                        not in {
                            "tabular.py",
                            "packages.py",
                            "wildfire.py",
                            "spreadsheets.py",
                            "preparation.py",
                            "daily.py",
                            "statistical_tables.py",
                            "jsonstat.py",
                            "owid_tables.py",
                        }
                        or file.name in required
                    )
                ):
                    archive.write(file, str(file.relative_to(directory)))
            archive.writestr("report.html", export(result, directory)[2])
            observations = io.StringIO(newline="")
            writer = csv.writer(observations)
            writer.writerow(
                [
                    "Source",
                    "Series",
                    "Entity",
                    "Year",
                    "Value",
                    "Unit",
                    "Source row",
                    "Reporting status",
                ]
            )
            for analysis in result["analyses"]:
                for series in analysis.get("series", []):
                    for row in series["annual"]:
                        writer.writerow(
                            [
                                analysis["source"]["title"],
                                series["label"],
                                series["entity"],
                                row["year"],
                                row["value"],
                                series["unit"],
                                row.get("source_reference", row.get("source_row", "")),
                                row.get("source_status", ""),
                            ]
                        )
            if any(a.get("series") for a in result["analyses"]):
                archive.writestr("analysed-observations.csv", observations.getvalue())
            for engine in required:
                if not (Path(directory) / engine).exists():
                    archive.writestr(engine, Path(__file__).with_name(engine).read_text())
            archive.writestr(
                "reproduce.py",
                (Path(directory) / "reproduce.py").read_text()
                if (Path(directory) / "reproduce.py").exists()
                else """import json, hashlib
from pathlib import Path
root=Path(__file__).parent
for directory in sorted(root.glob("source-*")):
    saved=directory/"analysis.json"
    decision=directory/"assessment.json"
    if decision.exists() and json.loads(decision.read_text()).get("decision")!="analysed": continue
    if not saved.exists(): continue
    result=json.loads(saved.read_text())
    source=directory/result["source"].get("artifact", "source.csv" if result["kind"]=="tabular" else "source.xlsx")
    assert hashlib.sha256(source.read_bytes()).hexdigest()==result["source"]["sha256"]
    if result["kind"]=="tabular":
        from tabular import analyse_csv
        table=source.read_bytes()
        if result.get("preparation"):
            from packages import prepare_table, attach_provenance
            table, preparation=prepare_table(table, result["preparation"].get("selection"))
            assert table==(directory/"source.csv").read_bytes()
        for component in result.get("components", [result]):
            component_table, component_preparation = table, preparation if result.get("preparation") else {}
            for plan in component.get("transformations", []):
                from preparation import transform_table
                component_table, component_preparation=transform_table(component_table, component_preparation, plan)
            replay=analyse_csv(component_table,component["mapping"],component["scope"])
            if result.get("preparation"): attach_provenance(replay, component_preparation)
            assert len(replay["series"])==len(component["series"])
            for expected, actual in zip(component["series"], replay["series"]):
                assert all(actual.get(k)==v for k,v in expected.items())
    else:
        from wildfire import parse_workbook, analyse
        replay=analyse(parse_workbook(source.read_bytes()),countries=result["requested_countries"],start=result["scope"]["start_year"],end=result["scope"]["end_year"])
        assert replay["annual"]==result["annual"]
    print("Verified",directory.name)
""",
            )
            archive.writestr(
                "README.txt",
                "Data research package\nOpen report.html for the readable report. Each source folder contains original data, executed Python, observations and provenance.\nFor new executable packages: Linux and bubblewrap are required. Install the versions in requirements.txt in a Python environment matching environment.json. Run python reproduce.py offline to check hashes and rerun the retained scripts in isolation. No host-execution fallback is used. Older packages retain their original replay method.\nanalysis.json records scope, discovery, model assessments and limitations. Numeric observations come from executed code reading retained sources. Model-written extraction and model review are not expert validation. Blocked attempts are retained for inspection and are not published numerical results.\n",
            )
        return "data-research-and-calculations.zip", "application/zip", output.getvalue()
    sections = []
    period = result.get("period", {})
    if period:
        sections.append(
            "<h2>Search period and analysed coverage</h2><p>" + escape(period["requested"]) + "</p>"
        )
        for row in period["analysed"]:
            sections.append(
                "<p>"
                + escape(
                    f"{row['source']} — {row['entity']}: {row['first_year']}–{row['last_year']}; missing years: {row['missing_years']}"
                )
                + "</p>"
            )
        sections.append("<p>" + escape(period["qualification"]) + "</p>")
    for analysis in result["analyses"]:
        source = analysis["source"]
        sections.append(f"<h2>{escape(source['title'])}</h2><p>Source: {escape(source['url'])}</p>")
        if analysis.get("execution"):
            sections.append(
                "<p>Executed Python and original files are included in the research package. Source hashes and calculated values were checked before publication.</p>"
            )
        if analysis.get("python_extraction"):
            sections.append(
                "<p>Extraction code was written by the model and executed in isolation. Its semantic review is a model assessment.</p>"
            )
        reviews = [analysis.get("semantic_review")] + [
            c.get("semantic_review") for c in analysis.get("components", [])
        ]
        unique_reviews = list(
            dict.fromkeys(json.dumps(r, ensure_ascii=False, indent=2) for r in reviews if r)
        )
        for review in unique_reviews:
            sections.append(
                "<details><summary>Measurement definitions and source passages</summary><pre>"
                + escape(review)
                + "</pre></details>"
            )
        if analysis.get("limitations"):
            sections.append(
                "<h3>Coverage and limitations</h3><ul>"
                + "".join("<li>" + escape(str(note)) + "</li>" for note in analysis["limitations"])
                + "</ul>"
            )
        if analysis["kind"] == "tabular":
            for series in analysis["series"]:
                if series.get("comparability_note"):
                    sections.append("<p>" + escape(series["comparability_note"]) + "</p>")
                sections.append(
                    f"<h3>{escape(series['entity'])} — {escape(series['label'])} ({escape(series['unit'])})</h3><table><tr><th>Year</th><th>Value</th><th>Source status</th></tr>"
                )
                sections.extend(
                    f"<tr><td>{r['year']}</td><td>{r['value'] if r['value'] is not None else 'Missing'}</td><td>{escape(r.get('source_status', ''))}</td></tr>"
                    for r in series["annual"]
                )
                sections.append("</table>")
        else:
            sections.append("<pre>" + escape(json.dumps(analysis["annual"], indent=2)) + "</pre>")
    report = (
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Data research</title><style>body{font:16px system-ui;max-width:1000px;margin:40px auto;padding:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere}td,th{padding:8px;text-align:left}</style><h1>Data research</h1>'
        + "".join(sections)
        + "<h2>Source decisions and limitations</h2><pre>"
        + escape(
            json.dumps(
                {k: v for k, v in result.items() if k != "analyses"}, indent=2, ensure_ascii=False
            )
        )
        + "</pre></html>"
    )
    return "data-research-report.html", "text/html; charset=utf-8", report.encode()


def markdown_appendix(result):
    """Included by all literature report renderers for combined runs."""

    def cell(value):
        return str(value).replace("|", "/").replace("\n", " ")

    lines = [
        "",
        "## Appendix E — Dataset research",
        "",
        "These calculations and source assessments are separate from the literature synthesis.",
        "",
    ]
    lines.extend("- " + cell(note) for note in result.get("limitations", []))
    for item in result.get("assessments", []):
        lines.append(
            "- "
            + cell(item.get("title"))
            + ": "
            + cell(item.get("decision"))
            + " — "
            + cell(item.get("reason"))
        )
        lines.extend(
            "- Automatic recovery: "
            + cell(step.get("class"))
            + " → "
            + cell(step.get("action"))
            + " · "
            + cell(step.get("outcome"))
            for step in item.get("recovery", [])
        )
    if result.get("connector_gaps"):
        lines.extend(["", "### Connector gaps", ""])
        lines.extend(
            f"- Needs an API connector for {cell(gap['host'])} ({cell(gap['measurement'])})"
            for gap in result["connector_gaps"]
        )
    for analysis in result.get("analyses", []):
        source = analysis["source"]
        if analysis.get("execution"):
            lines.extend(
                [
                    "",
                    "Executed Python: source hashes and numerical output checked before publication.",
                    "Original files, scripts, dependencies and offline replay are included in the research package.",
                ]
            )
        lines.extend(
            [
                "",
                "### " + cell(source["title"]),
                "",
                "Source: " + cell(source["url"]),
                "SHA-256: " + source["sha256"],
                "",
            ]
        )
        connector = source.get("connector")
        if connector:
            lines.extend(
                [
                    f"Queried the {cell(source.get('publisher', connector['name']))} API: dataset {cell(connector['dataset'])}",
                    "Exact request: " + cell(connector["request"].get("url", "")),
                    "",
                ]
            )
        if analysis["kind"] == "tabular":
            for series in analysis["series"]:
                lines.extend(
                    [
                        "",
                        cell(series["entity"])
                        + " — "
                        + cell(series["label"])
                        + " ("
                        + cell(series["unit"])
                        + ")",
                        "| Year | Value |",
                        "|---|---|",
                    ]
                )
                lines.extend(
                    f"| {r['year']} | {r['value'] if r['value'] is not None else 'Missing'} |"
                    for r in series["annual"]
                )
        else:
            lines.extend(
                [
                    "Fixed reporting panel: " + ", ".join(analysis["panel_countries"]),
                    "| Year | Fires | Burned area (km²) |",
                    "|---|---|---|",
                ]
            )
            lines.extend(
                f"| {r['year']} | {r['panel_fires'] if r['panel_fires'] is not None else 'Missing'} | {r['panel_burned_area_km2'] if r['panel_burned_area_km2'] is not None else 'Missing'} |"
                for r in analysis["annual"]
            )
    return "\n".join(lines)
