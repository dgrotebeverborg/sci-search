from __future__ import annotations

import unittest
from pathlib import Path

from sci_search.corpus import load_corpus
from sci_search.generic_evaluation import evaluate_generic
from sci_search.generic_research import GenericResearchEngine

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpora" / "goat_foraging"


class GoatForagingEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.documents = load_corpus(CORPUS)
        cls.engine = GenericResearchEngine(cls.documents)

    def test_has_ten_real_open_access_full_texts(self) -> None:
        self.assertEqual(len(self.documents), 10)
        self.assertTrue(
            all(document.publication.fixture_status is None for document in self.documents)
        )

    def test_cross_domain_gold_questions_pass(self) -> None:
        report = evaluate_generic(self.engine, CORPUS / "gold" / "generic_questions.json")
        self.assertTrue(report.passed, report)
        self.assertEqual(report.matched_evidence_count, report.expected_evidence_count)

    def test_researcher_summaries_surface_question_specific_results(self) -> None:
        seasonal = self.engine.investigate("Does season change goat foraging behaviour?")
        self.assertIn("48%", seasonal.answer_summary)
        self.assertGreaterEqual(len(set(seasonal.summary_evidence_ids)), 2)
        preference = self.engine.investigate("Do goats prefer leaves or grass?")
        self.assertIn("prefer leaves to grass", preference.answer_summary)
