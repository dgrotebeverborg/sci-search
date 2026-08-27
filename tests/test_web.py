from __future__ import annotations

import json
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

from sci_search.pipeline import build_evidence_store
from sci_search.ui import RESEARCHER_UI
from sci_search.web import CorpusCatalogService, ResearchService, create_handler, create_server

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "fixtures" / "iron_air_pilot"
QUESTION = (
    "What round-trip efficiencies are reported for iron-air batteries, and are they comparable?"
)


class ResearchServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        store, _ = build_evidence_store(CORPUS)
        cls.service = ResearchService(CORPUS, store=store)

    def test_service_returns_question_first_investigation_payload(self) -> None:
        payload = self.service.investigate(QUESTION)
        self.assertEqual(payload["question"], QUESTION)
        self.assertIn("answer_summary", payload)
        self.assertTrue(payload["literature_review_report"]["executive_summary"]["citations"])
        # The specialist result also retains its contextual comparison interface.
        self.assertEqual(payload["coverage"]["full_texts_analyzed"], 3)
        self.assertEqual(
            {item["action"] for item in payload["follow_up_questions"]},
            {
                "filter_measured",
                "show_comparison",
                "show_assumptions",
                "show_missing_context",
                "new_question",
            },
        )

    def test_service_opens_only_known_corpus_full_texts(self) -> None:
        document = self.service.full_text("synthetic-exp-a")
        self.assertEqual(document["publication_id"], "synthetic-exp-a")
        self.assertIn("measured round-trip efficiency", document["content"])
        with self.assertRaises(KeyError):
            self.service.full_text("../../etc/passwd")

    def test_handler_factory_binds_service_without_global_state(self) -> None:
        handler = create_handler(self.service)
        self.assertTrue(handler.__name__.endswith("Handler"))

    def test_generic_follow_up_keeps_question_history_and_context(self) -> None:
        goat_service = ResearchService(ROOT / "corpora" / "goat_foraging")
        first = goat_service.investigate(
            "How does vegetation structure affect goat foraging behaviour?",
            session_id="test:goat",
        )
        follow_up = goat_service.investigate(
            "What limitations are reported?",
            session_id=first["session_id"],
        )
        self.assertEqual(follow_up["question"], "What limitations are reported?")
        self.assertIn("vegetation structure", follow_up["contextualized_question"])
        self.assertEqual(len(follow_up["question_history"]), 2)

    def test_catalog_routes_questions_and_full_texts_to_selected_corpus(self) -> None:
        catalog = CorpusCatalogService((CORPUS, ROOT / "corpora" / "goat_foraging"))
        self.assertEqual(
            {item["id"] for item in catalog.catalog()}, {"iron_air_pilot", "goat_foraging"}
        )
        payload = catalog.investigate(
            "How does vegetation structure affect goat foraging behaviour?",
            corpus_id="goat_foraging",
        )
        self.assertEqual(payload["corpus_id"], "goat_foraging")
        self.assertEqual(payload["mode"], "generic_evidence")
        self.assertTrue(payload["evidence"])
        self.assertEqual(
            payload["literature_review_report"]["review_type"], "AI-assisted cited evidence review"
        )
        self.assertTrue(payload["literature_review_report"]["references"])
        full_text = catalog.full_text(
            payload["evidence"][0]["publication_id"], corpus_id="goat_foraging"
        )
        self.assertEqual(full_text["corpus_id"], "goat_foraging")
        self.assertTrue(full_text["content"])


class ResearcherUiTests(unittest.TestCase):
    def test_ui_exposes_progressive_research_workflow(self) -> None:
        self.assertNotIn("Evidence corpus", RESEARCHER_UI)
        for text in (
            "Start with a research question",
            "Answer summary",
            "Contextual results",
            "Can these be compared?",
            "Evidence and full texts",
            "Go deeper",
            "/api/investigate",
            "/api/full-text",
            "/api/corpora",
            "/api/research-runs",
            "/api/publication-download",
            "/api/publications-download",
            "/api/literature-review",
            "/api/research-package",
            'id="corpus"',
            "Search scientific literature",
            "Download selected",
            "Download all",
            "Research details",
            'id="live-options"',
            'id="review-mode"',
            "Research review · adaptive 25–50",
            "Quick scan · up to 10",
            "Deep review · adaptive 25–100",
            "coverage check",
            "unreadable artifact",
            "OCR may be required",
            "Download cited review",
            "Download research package",
            "Review PDF only",
            "retained original format",
            "AI-assisted · source verified",
            "/api/evidence-review",
            "/api/interpret-question",
            "Check my understanding",
            "Interpret question",
            "Literature review",
            "Explore the research landscape",
            "Organizations by publications on this subject",
            "Title-term signals",
            "automatic source-grounding check",
            "Landscape counts include discovered records without full text",
            "Full-text gap:",
            "papers with topic matches",
            "Review completed · overall answer withheld",
            "Verify",
            "Pipeline diagnostics",
            "renderPipelineDiagnostics",
            "question-specific, passage-grounded study card",
            'data-review="background"',
            "Validate quality",
            "/api/validation",
            "/api/validation/annotation",
            "/api/validation/full-text",
            "/api/validation/export",
            "Turn silver evidence into a researcher-checked benchmark",
            "Blind review",
            "Add a paper Sci-Search missed",
        ):
            self.assertIn(text, RESEARCHER_UI)
        self.assertIn("run?.run_id&&included>0", RESEARCHER_UI)
        self.assertNotIn("run?.status==='complete'", RESEARCHER_UI)

    def test_ui_uses_uu_primary_colour_hierarchy(self) -> None:
        self.assertIn("--yellow:#FFCD00", RESEARCHER_UI)
        self.assertIn("--black:#000", RESEARCHER_UI)
        self.assertIn("--white:#fff", RESEARCHER_UI)

    def test_validation_http_workflow_exposes_case_annotation_source_and_export(self) -> None:
        class StubValidation:
            def overview(self):
                return {"cases": [{"id": "case-1"}], "aggregate_scorecard": {}}

            def case(self, case_id):
                return {"case": {"id": case_id}, "publications": []}

            def annotate(self, case_id, payload):
                return {"case": {"id": case_id}, "saved": payload}

            def full_text(self, case_id, publication_id):
                return {"case_id": case_id, "publication_id": publication_id, "content": "source"}

            def export_package(self, guide_path=None):
                return b"PK\x03\x04validation"

        service = CorpusCatalogService((CORPUS,), validation_workspace=StubValidation())
        try:
            server = create_server("127.0.0.1", 0, service)
        except PermissionError:
            self.skipTest("local socket creation is restricted in this test sandbox")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            connection.request("GET", "/api/validation?case_id=case-1")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["case"]["id"], "case-1")
            body = json.dumps(
                {"case_id": "case-1", "annotation": {"kind": "case", "status": "in_progress"}}
            )
            connection.request(
                "POST", "/api/validation/annotation", body, {"Content-Type": "application/json"}
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["saved"]["status"], "in_progress")
            connection.request(
                "GET", "/api/validation/full-text?case_id=case-1&publication_id=paper-1"
            )
            response = connection.getresponse()
            self.assertEqual(json.loads(response.read())["content"], "source")
            connection.request("GET", "/api/validation/export")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Content-Type"), "application/zip")
            self.assertTrue(response.read().startswith(b"PK"))
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.assertIn("--red:#C00A35", RESEARCHER_UI)

    def test_ui_escapes_api_content_before_using_html_templates(self) -> None:
        self.assertIn("const esc=", RESEARCHER_UI)
        self.assertIn("esc(e.passage)", RESEARCHER_UI)
        self.assertIn("encodeURIComponent(publication)", RESEARCHER_UI)
