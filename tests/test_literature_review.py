from __future__ import annotations

import io
import unittest
from pathlib import Path

import pytest
from pypdf import PdfReader

from sci_search.corpus import load_corpus
from sci_search.generic_research import GenericResearchEngine
from sci_search.literature_review import (
    build_literature_review,
    render_review_html,
    render_review_json,
    render_review_markdown,
    render_review_pdf,
)

ROOT = Path(__file__).resolve().parents[1]


class LiteratureReviewTests(unittest.TestCase):
    @pytest.mark.retained_corpus
    def test_builds_cited_review_and_verifiable_appendix(self) -> None:
        documents = load_corpus(ROOT / "corpora" / "goat_foraging")
        investigation = (
            GenericResearchEngine(documents)
            .investigate("How does forage availability affect goat foraging behaviour?")
            .to_dict()
        )
        candidates = [
            {
                "id": document.publication.id,
                "title": document.publication.title,
                "authors": list(document.publication.authors),
                "year": document.publication.year,
                "doi": document.publication.doi,
                "source_url": document.publication.source_url,
                "publication_type": document.publication.document_type,
                "screening_status": "selected",
                "screening_reason": "covered planned concepts",
            }
            for document in documents
        ]
        investigation["research_run"] = {
            "run_id": "test-review",
            "records_retrieved": 12,
            "unique_candidates": 10,
            "selected_candidates": 10,
            "full_texts_acquired": 10,
            "active_publication_ids": [item["id"] for item in candidates],
            "candidates": candidates,
            "acquisitions": [
                {"publication_id": item["id"], "status": "acquired", "source": "test"}
                for item in candidates
            ],
            "queries": [
                {"text": "goat forage availability behavior", "purpose": "canonical concepts"}
            ],
            "search_log": [{"provider": "test-provider"}],
        }
        investigation["plan"] = {
            "profile_id": "ecology",
            "intent": "relationship",
            "concepts": ["forage availability", "goat foraging behaviour"],
            "expanded_terms": [],
        }
        report = build_literature_review(investigation)
        self.assertEqual(report["systematic_review_status"], "not_a_systematic_review")
        self.assertTrue(report["executive_summary"]["citations"])
        self.assertEqual(report["selection_flow"]["full_texts_acquired"], 10)
        self.assertTrue(report["references"])
        self.assertTrue(report["appendices"]["evidence_records"])
        markdown = render_review_markdown(report)
        self.assertIn("## Selection flow", markdown)
        self.assertIn("## References", markdown)
        self.assertIn("## Contradictions, methods, and comparability", markdown)
        self.assertIn("## Appendix B — Verifiable evidence passages", markdown)
        self.assertIn("## Research landscape", markdown)
        self.assertIn("metadata-only records", markdown)
        self.assertIn("[1]", markdown)
        self.assertIn("<!doctype html>", render_review_html(report))
        self.assertIn('"schema_version": "cited_literature_review_v1"', render_review_json(report))
        pdf = render_review_pdf(report)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)
        self.assertIn("Research landscape", pdf_text)
        self.assertIn("References", pdf_text)

    @pytest.mark.retained_corpus
    def test_incomplete_scope_does_not_promote_topic_matches_to_review_findings(self) -> None:
        investigation = (
            GenericResearchEngine(load_corpus(ROOT / "corpora" / "goat_foraging"))
            .investigate("How does lunar geology affect goat foraging?")
            .to_dict()
        )
        investigation["answer_adequacy"] = {
            "status": "partial",
            "can_answer_overall_question": False,
            "missing_requirements": ["lunar geology"],
        }
        investigation["summary_evidence_ids"] = []
        investigation["ai_analysis"] = {"status": "unavailable", "answer": None, "claims": []}
        report = build_literature_review(investigation)
        self.assertFalse(report["findings"])
        self.assertEqual(report["selection_flow"]["publications_cited_in_report"], 0)


if __name__ == "__main__":
    unittest.main()
