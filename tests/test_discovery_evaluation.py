from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sci_search.discovery_evaluation import evaluate_discovery


class DiscoveryEvaluationTests(unittest.TestCase):
    def test_reports_recall_and_exclusion_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            discovery = root / "discovery.json"
            gold = root / "gold.json"
            discovery.write_text(
                json.dumps(
                    {
                        "candidates": [
                            {
                                "id": "a",
                                "doi": "10.1/a",
                                "screening_status": "selected",
                                "screening_reason": "relevant",
                            },
                            {
                                "id": "b",
                                "doi": "https://doi.org/10.1/b",
                                "screening_status": "excluded",
                                "screening_reason": "scope",
                            },
                        ],
                        "acquisitions": [{"publication_id": "a", "status": "acquired"}],
                    }
                )
            )
            gold.write_text(
                json.dumps(
                    {
                        "expected_dois": ["10.1/a", "10.1/b", "10.1/c"],
                        "minimum_discovery_recall": 0.6,
                    }
                )
            )
            report = evaluate_discovery(discovery, gold)
            self.assertTrue(report.passed)
            self.assertEqual(report.discovery_recall, 0.6667)
            self.assertEqual(report.missed_dois, ("10.1/c",))
            self.assertEqual(report.excluded_expected[0]["reason"], "scope")


if __name__ == "__main__":
    unittest.main()
