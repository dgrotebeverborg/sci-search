"""Portable reports for generic evidence investigations."""

from __future__ import annotations

import html
import json
from pathlib import Path

from sci_search.generic_research import GenericInvestigation
from sci_search.models import dataclass_to_dict


def render_generic_json(report: GenericInvestigation) -> str:
    return json.dumps(dataclass_to_dict(report), indent=2, sort_keys=True)


def render_generic_markdown(report: GenericInvestigation, corpus_directory: Path) -> str:
    evidence_by_id = {item.id: item for item in report.evidence}
    lines = [
        "# Sci-Search evidence report",
        "",
        f"**Question:** {report.question}",
        "",
        "## Answer summary",
        "",
        report.answer_summary,
        "",
        "Summary evidence: "
        + ", ".join(
            f"[{evidence_by_id[item].publication_id}](#{item})"
            for item in report.summary_evidence_ids
        ),
        "",
        "## Findings",
        "",
    ]
    for finding in report.findings:
        lines.extend(
            (
                f"### {finding.status.replace('_', ' ').title()}",
                "",
                finding.statement,
                "",
                finding.qualification,
                "",
            )
        )
        lines.append(
            "Evidence: "
            + ", ".join(
                f"[{evidence_by_id[item].publication_id}](#{item})" for item in finding.evidence_ids
            )
        )
        lines.append("")
    lines.extend(("## Evidence and full texts", ""))
    for item in report.evidence:
        lines.extend(
            (
                f'<a id="{item.id}"></a>',
                f"### {item.publication_title}",
                "",
                f"Section `{item.section}`, page {item.page or 'not encoded'}; {item.evidence_type}; {item.extraction_method}.",
                "",
                f"> {item.passage}",
                "",
                f"[Open local full text]({(corpus_directory / item.source_document).as_posix()})",
                "",
            )
        )
    lines.extend(("## Limitations", ""))
    lines.extend(f"- {item}" for item in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def render_generic_html(report: GenericInvestigation, corpus_directory: Path) -> str:
    evidence_by_id = {item.id: item for item in report.evidence}
    citations = " · ".join(
        f"<a href='#{html.escape(item)}'>{html.escape(evidence_by_id[item].publication_id)}</a>"
        for item in report.summary_evidence_ids
    )
    findings = "".join(
        f"<article><small>{html.escape(item.status.replace('_', ' '))}</small><h3>{html.escape(item.statement)}</h3><p>{html.escape(item.qualification)}</p>"
        + " ".join(
            f"<a href='#{html.escape(evidence_id)}'>source</a>" for evidence_id in item.evidence_ids
        )
        + "</article>"
        for item in report.findings
    )
    evidence = "".join(
        f"<details id='{html.escape(item.id)}'><summary>{html.escape(item.publication_title)} — {html.escape(item.section)}</summary>"
        f"<p>{html.escape(item.evidence_type)} · {html.escape(item.study_design)} · score {item.retrieval_score}</p>"
        f"<blockquote>{html.escape(item.passage)}</blockquote><a href='{html.escape((corpus_directory / item.source_document).as_posix())}'>Open local full text</a></details>"
        for item in report.evidence
    )
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in report.limitations)
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>Sci-Search evidence report</title><style>:root{{--yellow:#FFCD00;--black:#000;--red:#C00A35}}*{{box-sizing:border-box}}body{{margin:0;font:16px/1.55 Arial,sans-serif;color:#242424}}header{{height:18px;background:var(--yellow);border-bottom:4px solid var(--black)}}main{{max-width:1000px;margin:auto;padding:2rem 1.25rem 5rem}}h1{{font-size:2.6rem}}.summary{{border-top:7px solid var(--yellow);padding:1.25rem 0;border-bottom:1px solid #ccc}}article,details{{padding:1rem 0;border-bottom:1px solid #ccc}}blockquote{{border-left:5px solid var(--yellow);padding-left:1rem}}a{{color:#174f8a}}.limitations{{border-left:5px solid var(--red)}}</style></head><body><header></header><main><h1>What the corpus shows</h1><p><strong>Question:</strong> {html.escape(report.question)}</p><section class='summary'><h2>Answer summary</h2><p>{html.escape(report.answer_summary)}</p><p>{citations}</p></section><h2>Findings</h2>{findings}<h2>Evidence and full texts</h2>{evidence}<h2>Limitations</h2><ul class='limitations'>{limitations}</ul></main></body></html>"""
