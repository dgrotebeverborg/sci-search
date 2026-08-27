from __future__ import annotations

import unittest
from pathlib import Path

from sci_search.evaluation import evaluate_results
from sci_search.pipeline import build_evidence_store

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "fixtures" / "iron_air_pilot"
GOLD = CORPUS / "gold" / "round_trip_efficiency.json"


class EvaluationTests(unittest.TestCase):
    def test_pilot_extraction_passes_contextual_gold_fixture(self) -> None:
        store, _ = build_evidence_store(CORPUS)
        report = evaluate_results(store.query_results("round_trip_efficiency"), GOLD, CORPUS)
        self.assertTrue(report.passed)
        self.assertEqual(report.expected_count, 3)
        self.assertEqual(report.incorrect_provenance_count, 0)
        self.assertEqual(report.incorrect_context_count, 0)
