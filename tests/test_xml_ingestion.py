from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sci_search.xml_ingestion import extract_jats_text


class XmlIngestionTests(unittest.TestCase):
    def test_preserves_abstract_sections_and_paragraphs(self) -> None:
        source = """<?xml version='1.0'?><article><front><abstract><p>Summary of a fully reported scientific experiment and its relevant operating conditions.</p></abstract></front><body><sec><title>Results</title><p>At the recorded laboratory conditions, RTE was <bold>82.9%</bold>.</p></sec></body></article>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper.xml"
            path.write_text(source, encoding="utf-8")
            text = extract_jats_text(path)
        self.assertIn("## Abstract\n\nSummary of a fully reported", text)
        self.assertIn("## Results\n\nAt the recorded laboratory conditions, RTE was 82.9%.", text)
