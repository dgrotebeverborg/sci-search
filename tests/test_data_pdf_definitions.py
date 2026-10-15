"""Primary methodology PDFs must reach the same cited review as HTML definitions."""

import io

import pytest
from pypdf import PdfReader, PdfWriter

from sci_search.data_research import workflow
from sci_search.data_research.connectors import base, eurostat, stage
from sci_search.data_research.inspection import extract_documentation_pdf
from sci_search.pdf_report import markdown_to_pdf
from tests.test_connector_stage import STRATEGY


def methodology_pdf():
    text = "Renewable electricity share uses gross electricity consumption as its denominator."
    reader = PdfReader(io.BytesIO(markdown_to_pdf(text * 3, title="Methodology")))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page).compress_content_streams()
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue(), text


def test_connector_definition_search_extracts_pdf_instead_of_decoding_binary(tmp_path, monkeypatch):
    body, passage = methodology_pdf()
    url = "https://ec.europa.eu/methodology.pdf"
    received = []

    def connector_run(*args, **kwargs):
        candidate = base.DatasetCandidate("eurostat", "x", "Series", "annual", landing_url=url)
        received.extend(kwargs["definition_search"](candidate, {"reason": "Missing denominator"}))
        kwargs["result"].update(analyses=[], assessments=[], covered=[], search={})

    monkeypatch.setattr(stage, "run", connector_run)
    workflow.execute(
        "Describe the series",
        STRATEGY,
        tmp_path,
        connectors={"eurostat": eurostat},
        fetch=lambda _: (body, "application/pdf", url),
        search=lambda question, scope, **kwargs: {
            "candidates": [{"url": url}] if scope.get("documentation_request") else []
        },
        complete=lambda *args: {},
        budget_limits={"model_calls": 0},
    )
    assert len(received) == 1
    assert passage in " ".join(received[0]["text"].split())
    assert "[PAGE 1]" in received[0]["text"]
    assert received[0]["body"] == body


@pytest.mark.parametrize("mode", ["blank", "encrypted", "too_many_pages"])
def test_unreadable_or_excessive_methodology_is_not_published_as_text(tmp_path, mode):
    writer = PdfWriter()
    for _ in range(201 if mode == "too_many_pages" else 1):
        writer.add_blank_page(width=100, height=100)
    if mode == "encrypted":
        writer.encrypt("test-password")
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(ValueError):
        extract_documentation_pdf(output.getvalue(), tmp_path / "extraction")


def test_oversized_pdf_is_rejected_before_execution(tmp_path):
    with pytest.raises(ValueError, match="excessive"):
        extract_documentation_pdf(b"%PDF-" + b" " * 10_000_000, tmp_path / "absent")
    assert not (tmp_path / "absent").exists()
