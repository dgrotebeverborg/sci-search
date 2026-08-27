"""Readable reports for a question-first scientific investigation."""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
from urllib.parse import quote

from sci_search.investigation import ResearchInvestigation
from sci_search.models import Condition, MeasurementResult, dataclass_to_dict


def render_json(investigation: ResearchInvestigation) -> str:
    return json.dumps(dataclass_to_dict(investigation), indent=2, sort_keys=True)


def render_markdown(investigation: ResearchInvestigation, *, corpus_directory: Path) -> str:
    evidence_by_id = {item.id: item for item in investigation.evidence}
    lines = [
        "# Sci-Search research report",
        "",
        f"**Question:** {investigation.question}",
        "",
        "## Answer summary",
        "",
        investigation.answer_summary,
        "",
        "## Corpus and full-text coverage",
        "",
        f"- Publications discovered: {investigation.coverage.publications_discovered}",
        f"- Full texts available: {investigation.coverage.full_texts_available}",
        f"- Full texts analyzed: {investigation.coverage.full_texts_analyzed}",
        f"- Contextual results found: {investigation.coverage.results_found}",
        "",
        "## Findings",
        "",
    ]
    for finding in investigation.findings:
        citations = ", ".join(
            f"[{evidence_by_id[item].publication_id}](#{item})" for item in finding.evidence_ids
        )
        lines.extend(
            (f"### {finding.status.value.replace('_', ' ').title()}", "", finding.statement, "")
        )
        if finding.qualification:
            lines.extend((f"Qualification: {finding.qualification}", ""))
        lines.extend((f"Evidence: {citations}", ""))
    lines.extend(("## Contextual results", "", _markdown_result_table(investigation.results), ""))
    lines.extend(("## Pairwise comparability", "", _markdown_comparison_table(investigation), ""))
    lines.extend(("## Evidence and full texts", ""))
    for evidence in investigation.evidence:
        source_path = corpus_directory / evidence.source_document
        lines.extend(
            (
                f'<a id="{evidence.id}"></a>',
                f"### {evidence.publication_title}",
                "",
                f"Source: [{evidence.source_document}]({source_path.as_posix()}), section `{evidence.section}`, page {evidence.page or 'unknown'}.",
                "",
                f"> {evidence.passage}",
                "",
            )
        )
    lines.extend(("## Limitations", ""))
    lines.extend(f"- {item}" for item in investigation.limitations)
    lines.extend(("", "## Continue the investigation", ""))
    lines.extend(f"- {item.label}" for item in investigation.follow_up_questions)
    return "\n".join(lines).rstrip() + "\n"


def render_html(
    investigation: ResearchInvestigation,
    *,
    corpus_directory: Path,
    output_path: Path | None = None,
) -> str:
    evidence_by_id = {item.id: item for item in investigation.evidence}
    findings = "".join(
        f"<article class='finding {html.escape(item.status.value)}'>"
        f"<span class='status'>{html.escape(item.status.value.replace('_', ' '))}</span>"
        f"<h3>{html.escape(item.statement)}</h3>"
        f"<p>{html.escape(item.qualification or '')}</p>"
        f"<p class='citations'>Evidence: "
        + ", ".join(
            f"<a href='#{html.escape(evidence_id)}'>{html.escape(evidence_by_id[evidence_id].publication_id)}</a>"
            for evidence_id in item.evidence_ids
        )
        + "</p></article>"
        for item in investigation.findings
    )
    evidence_cards = "".join(
        _html_evidence(item, corpus_directory=corpus_directory, output_path=output_path)
        for item in investigation.evidence
    )
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in investigation.limitations)
    follow_ups = "".join(
        f"<li>{html.escape(item.label)}</li>" for item in investigation.follow_up_questions
    )
    coverage = investigation.coverage
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sci-Search research report</title>
<style>
:root {{ color-scheme: light; --ink:#17211b; --muted:#5c6b62; --paper:#f6f4ec; --card:#fffef8; --accent:#176b52; --line:#d8ddd8; }}
* {{ box-sizing:border-box; }} body {{ margin:0; background:var(--paper); color:var(--ink); font:16px/1.55 system-ui,sans-serif; }}
main {{ max-width:1100px; margin:auto; padding:3rem 1.25rem 5rem; }} h1 {{ font-size:clamp(2rem,5vw,4rem); margin:.2rem 0; }} h2 {{ margin-top:3rem; }}
.question {{ color:var(--muted); font-size:1.15rem; }} .summary {{ background:var(--ink); color:white; padding:1.5rem; border-radius:14px; font-size:1.15rem; }}
.coverage {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:.75rem; }} .coverage div,.finding,details {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:1rem; }}
.coverage strong {{ display:block; font-size:1.8rem; }} .coverage span,.status {{ color:var(--muted); }} .status {{ text-transform:uppercase; font-size:.75rem; letter-spacing:.08em; }}
table {{ width:100%; border-collapse:collapse; background:var(--card); font-size:.9rem; }} th,td {{ border:1px solid var(--line); padding:.65rem; text-align:left; vertical-align:top; }} th {{ background:#e9eee9; }}
.table-wrap {{ overflow-x:auto; }} details {{ margin:.75rem 0; }} summary {{ cursor:pointer; font-weight:700; }} blockquote {{ border-left:4px solid var(--accent); margin:1rem 0; padding-left:1rem; }} a {{ color:var(--accent); }} .warning {{ border-left:5px solid #b26a00; padding-left:1rem; }}
</style>
</head>
<body><main>
<p class="status">Scientific evidence report</p>
<h1>What the corpus shows</h1>
<p class="question"><strong>Question:</strong> {html.escape(investigation.question)}</p>
<section class="summary"><strong>Answer summary</strong><p>{html.escape(investigation.answer_summary)}</p></section>
<h2>Corpus and full-text coverage</h2>
<section class="coverage">
<div><strong>{coverage.publications_discovered}</strong><span>publications discovered</span></div>
<div><strong>{coverage.full_texts_available}</strong><span>full texts available</span></div>
<div><strong>{coverage.full_texts_analyzed}</strong><span>full texts analyzed</span></div>
<div><strong>{coverage.results_found}</strong><span>contextual results</span></div>
</section>
<h2>Findings</h2>{findings}
<h2>Contextual results</h2><div class="table-wrap">{_html_result_table(investigation.results)}</div>
<h2>Pairwise comparability</h2><div class="table-wrap">{_html_comparison_table(investigation)}</div>
<h2>Evidence and full texts</h2><p>Expand a source to inspect the exact passage. Open the local document to review its complete text.</p>{evidence_cards}
<h2>Limitations</h2><ul class="warning">{limitations}</ul>
<h2>Continue the investigation</h2><ul>{follow_ups}</ul>
</main></body></html>"""


def _markdown_result_table(results: tuple[MeasurementResult, ...]) -> str:
    lines = [
        "| Publication | Value | Evidence | Nature | Configuration | Scale | Temperature | Current density | Boundary |",
        "|---|---:|---|---|---|---|---|---|---|",
    ]
    for item in results:
        lines.append(
            "| "
            + " | ".join(
                (
                    item.provenance.publication_id,
                    _quantity(item),
                    item.context.evidence_type.value,
                    item.context.result_nature.value,
                    item.context.configuration or "unknown",
                    item.context.system_scale or "unknown",
                    _condition(item, "temperature"),
                    _condition(item, "current_density"),
                    item.context.calculation_boundary or "unknown",
                )
            )
            + " |"
        )
    return "\n".join(lines)


def _markdown_comparison_table(investigation: ResearchInvestigation) -> str:
    lines = ["| Left | Right | Status | Explanation |", "|---|---|---|---|"]
    for item in investigation.comparisons:
        explanation = ", ".join(difference.field for difference in item.differences)
        if item.missing_context:
            explanation += (
                ("; " if explanation else "") + "missing: " + ", ".join(item.missing_context)
            )
        lines.append(
            f"| {item.left_result_id} | {item.right_result_id} | {item.status.value} | {explanation or 'required context matches'} |"
        )
    return "\n".join(lines)


def _html_result_table(results: tuple[MeasurementResult, ...]) -> str:
    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(value))}</td>"
            for value in (
                item.provenance.publication_id,
                _quantity(item),
                item.context.evidence_type.value,
                item.context.result_nature.value,
                item.context.configuration or "unknown",
                item.context.system_scale or "unknown",
                _condition(item, "temperature"),
                _condition(item, "current_density"),
                item.context.calculation_boundary or "unknown",
            )
        )
        + "</tr>"
        for item in results
    )
    headings = (
        "Publication",
        "Value",
        "Evidence",
        "Nature",
        "Configuration",
        "Scale",
        "Temperature",
        "Current density",
        "Boundary",
    )
    return (
        "<table><thead><tr>"
        + "".join(f"<th>{item}</th>" for item in headings)
        + "</tr></thead><tbody>"
        + rows
        + "</tbody></table>"
    )


def _html_comparison_table(investigation: ResearchInvestigation) -> str:
    rows = []
    for item in investigation.comparisons:
        explanation = ", ".join(difference.field for difference in item.differences)
        if item.missing_context:
            explanation += (
                ("; " if explanation else "") + "missing: " + ", ".join(item.missing_context)
            )
        values = (
            item.left_result_id,
            item.right_result_id,
            item.status.value,
            explanation or "required context matches",
        )
        rows.append(
            "<tr>" + "".join(f"<td>{html.escape(value)}</td>" for value in values) + "</tr>"
        )
    return (
        "<table><thead><tr><th>Left</th><th>Right</th><th>Status</th><th>Explanation</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _html_evidence(item: object, *, corpus_directory: Path, output_path: Path | None) -> str:
    source_path = corpus_directory / item.source_document
    if output_path is not None:
        href = os.path.relpath(source_path.resolve(), output_path.resolve().parent)
    else:
        href = source_path.resolve().as_uri()
    location = f"section {item.section}, page {item.page or 'unknown'}"
    source_record = (
        f" <a href='{html.escape(item.source_url, quote=True)}'>Open source record</a>."
        if item.source_url
        else ""
    )
    return (
        f"<details id='{html.escape(item.id)}'><summary>{html.escape(item.publication_title)} — {html.escape(location)}</summary>"
        f"<p>Evidence record: {html.escape(item.extraction_method)}.</p>"
        f"<blockquote>{html.escape(item.passage)}</blockquote>"
        f"<a href='{quote(href, safe='/.:')}'>Open complete local full text</a>.{source_record}</details>"
    )


def _condition(result: MeasurementResult, name: str) -> str:
    condition: Condition | None = result.context.condition(name)
    if condition is None:
        return "unknown"
    return f"{condition.value} {condition.unit or ''}".strip()


def _quantity(result: MeasurementResult) -> str:
    quantity = result.quantity
    if quantity.lower_bound is not None:
        return f"{quantity.lower_bound}–{quantity.upper_bound}{quantity.unit}"
    return f"{quantity.value}{quantity.unit}"
