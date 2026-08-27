from __future__ import annotations

import unittest
from pathlib import Path

from sci_search.comparison import ComparabilityStatus, compare_pair, comparison_report
from sci_search.pipeline import build_evidence_store

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "fixtures" / "iron_air_pilot"


class ComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        store, _ = build_evidence_store(CORPUS)
        cls.results = store.query_results("round_trip_efficiency")

    def test_same_experimental_context_is_comparable(self) -> None:
        comparison = compare_pair(self.results[0], self.results[1])
        self.assertEqual(comparison.status, ComparabilityStatus.COMPARABLE)
        self.assertEqual(comparison.differences, ())

    def test_measured_cell_and_assumed_system_values_are_not_comparable(self) -> None:
        comparison = compare_pair(self.results[0], self.results[2])
        self.assertEqual(comparison.status, ComparabilityStatus.DIFFERENT_CONTEXT)
        fields = {difference.field for difference in comparison.differences}
        self.assertTrue(
            {
                "evidence_type",
                "result_nature",
                "configuration",
                "system_scale",
                "calculation_boundary",
            }
            <= fields
        )

    def test_report_does_not_collapse_values_into_one_fact(self) -> None:
        report = comparison_report(self.results)
        self.assertEqual(report["publication_count"], 3)
        self.assertEqual(report["summary"]["comparable"], 1)
        self.assertEqual(report["summary"]["different_context"], 2)
        self.assertEqual(len(report["results"]), 3)
