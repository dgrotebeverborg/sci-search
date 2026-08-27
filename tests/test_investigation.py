from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sci_search.cli import main
from sci_search.investigation import FindingStatus, interpret_question, investigate
from sci_search.pipeline import build_evidence_store
from sci_search.reporting import render_html, render_json, render_markdown

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "fixtures" / "iron_air_pilot"
QUESTION = (
    "What round-trip efficiencies are reported for iron-air batteries, and are they comparable?"
)


class InvestigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store, _ = build_evidence_store(CORPUS)
        cls.investigation = investigate(QUESTION, cls.store)

    def test_interprets_supported_natural_language_question(self) -> None:
        self.assertEqual(interpret_question(QUESTION), "round_trip_efficiency")
        with self.assertRaisesRegex(ValueError, "supports questions"):
            interpret_question("What determines cycle life?")

    def test_summary_leads_with_answer_and_qualifies_comparability(self) -> None:
        summary = self.investigation.answer_summary
        self.assertIn("analyzed 3 full texts", summary)
        self.assertIn("62% to 64%", summary)
        self.assertIn("assumed rather than measured", summary)
        self.assertIn("does not justify", summary)
        self.assertEqual(self.investigation.coverage.results_found, 3)

    def test_findings_link_to_exact_evidence(self) -> None:
        statuses = {item.status for item in self.investigation.findings}
        self.assertEqual(statuses, {FindingStatus.CONSISTENT, FindingStatus.CONTEXT_DEPENDENT})
        evidence_ids = {item.id for item in self.investigation.evidence}
        for finding in self.investigation.findings:
            self.assertTrue(set(finding.evidence_ids) <= evidence_ids)
        for evidence in self.investigation.evidence:
            source = (CORPUS / evidence.source_document).read_text(encoding="utf-8")
            self.assertIn(evidence.passage, source)

    def test_structured_report_preserves_drill_down_information(self) -> None:
        payload = json.loads(render_json(self.investigation))
        self.assertEqual(payload["question"], QUESTION)
        self.assertEqual(len(payload["evidence"]), 3)
        self.assertEqual(len(payload["comparisons"]), 3)
        self.assertTrue(payload["follow_up_questions"])

    def test_readable_reports_include_summary_results_sources_and_follow_ups(self) -> None:
        markdown = render_markdown(self.investigation, corpus_directory=CORPUS)
        html = render_html(self.investigation, corpus_directory=CORPUS)
        for value in (markdown, html):
            self.assertIn("Answer summary", value)
            self.assertIn("Contextual results", value)
            self.assertIn("Evidence and full texts", value)
            self.assertIn("Continue the investigation", value)
            self.assertIn("measured round-trip efficiency was 62 %", value)

    def test_cli_writes_self_contained_html_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.html"
            exit_code = main(
                (
                    "--corpus",
                    str(CORPUS),
                    "investigate",
                    "--question",
                    QUESTION,
                    "--format",
                    "html",
                    "--output",
                    str(output),
                )
            )
            self.assertEqual(exit_code, 0)
            rendered = output.read_text(encoding="utf-8")
            self.assertIn("What the corpus shows", rendered)
            self.assertIn("Open complete local full text", rendered)
