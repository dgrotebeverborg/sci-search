from __future__ import annotations

import unittest

from sci_search.pdf_ingestion import _normalize_page


class PdfIngestionTests(unittest.TestCase):
    def test_normalizes_whitespace_and_marks_known_headings(self) -> None:
        text = "  2. Results and Discussion  \n\n RTE   was  82.9%.\n"
        self.assertEqual(_normalize_page(text), "## Results And Discussion\n\nRTE was 82.9%.")

    def test_does_not_invent_sections_from_normal_sentences(self) -> None:
        text = "Results were evaluated at 550 C."
        self.assertEqual(_normalize_page(text), text)
