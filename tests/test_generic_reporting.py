from __future__ import annotations

import json
from pathlib import Path

from sci_search.corpus import load_corpus
from sci_search.generic_reporting import (
    render_generic_html,
    render_generic_json,
    render_generic_markdown,
)
from sci_search.generic_research import GenericResearchEngine

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "fixtures" / "iron_air_pilot"


def test_generic_reports_preserve_answer_evidence_and_full_text_links():
    report = GenericResearchEngine(load_corpus(CORPUS)).investigate(
        "What measured round-trip efficiency is reported?"
    )

    payload = json.loads(render_generic_json(report))
    markdown = render_generic_markdown(report, CORPUS)
    html = render_generic_html(report, CORPUS)

    assert payload["question"] == report.question
    assert payload["evidence"]
    assert report.answer_summary in markdown
    assert "## Findings" in markdown
    assert "## Evidence and full texts" in markdown
    assert "Open local full text" in markdown
    assert "What the corpus shows" in html
    assert "Evidence and full texts" in html
    assert "Open local full text" in html
    for item in report.evidence:
        assert item.passage in markdown
        assert item.id in html


def test_generic_html_escapes_untrusted_question_text():
    report = GenericResearchEngine(load_corpus(CORPUS)).investigate(
        "How do <script>alert('x')</script> dolphins communicate with cuttlefish?"
    )

    html = render_generic_html(report, CORPUS)

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
