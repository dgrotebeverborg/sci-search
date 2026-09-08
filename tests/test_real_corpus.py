from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

import pytest

from sci_search.evaluation import evaluate_results
from sci_search.pipeline import build_evidence_store

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpora" / "iron_air_real"


@pytest.mark.retained_corpus
class RealCorpusVerticalSliceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store, cls.warnings = build_evidence_store(CORPUS)
        cls.results = cls.store.query_results("round_trip_efficiency")

    def test_uses_ten_real_full_texts_and_four_reviewed_results(self) -> None:
        self.assertEqual(len(self.store.publications), 10)
        self.assertEqual(len(self.results), 4)
        self.assertEqual(self.warnings, ())
        self.assertTrue(
            all(
                result.provenance.extraction_method.name == "manual_context_review"
                for result in self.results
            )
        )

    def test_preserves_range_and_distinguishes_cell_measurement_from_system_assumptions(
        self,
    ) -> None:
        form = next(
            result for result in self.results if result.provenance.publication_id == "form-2024-pnw"
        )
        self.assertEqual(
            (form.quantity.lower_bound, form.quantity.upper_bound), (Decimal(40), Decimal(45))
        )
        measured = [
            result for result in self.results if result.context.result_nature.value == "measured"
        ]
        assumed = [
            result for result in self.results if result.context.result_nature.value == "assumed"
        ]
        self.assertEqual(len(measured), 2)
        self.assertEqual(len(assumed), 2)
        self.assertNotEqual(
            measured[0].context.calculation_boundary, assumed[0].context.calculation_boundary
        )

    def test_matches_the_manually_inspectable_gold_set(self) -> None:
        report = evaluate_results(
            self.results, CORPUS / "gold" / "round_trip_efficiency.json", CORPUS
        )
        self.assertTrue(report.passed, report)
