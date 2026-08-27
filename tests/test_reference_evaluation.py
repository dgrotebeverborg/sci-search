from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sci_search.reference_evaluation import evaluate_reference_case, load_reference_set


class ReferenceEvaluationTests(unittest.TestCase):
    def test_repository_reference_set_is_valid_and_explicitly_silver(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = load_reference_set(root / "benchmarks" / "researcher_five_silver_v1.json")
        self.assertEqual(len(result["cases"]), 5)
        self.assertIn("pending_domain_researcher_validation", result["validation_status"])

    def test_reports_losses_at_each_pipeline_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "run.json").write_text(json.dumps({"run_id": "run-1"}))
            (root / "discovery.json").write_text(
                json.dumps(
                    {
                        "candidates": [
                            {"id": "direct-a", "doi": "10.1/a", "screening_status": "selected"},
                            {"id": "direct-b", "doi": "10.1/b", "screening_status": "selected"},
                            {"id": "noise", "doi": "10.1/noise", "screening_status": "excluded"},
                        ],
                        "acquisitions": [
                            {"publication_id": "direct-a", "status": "acquired"},
                            {"publication_id": "direct-b", "status": "failed"},
                        ],
                    }
                )
            )
            (root / "investigation.json").write_text(
                json.dumps(
                    {
                        "answer_adequacy": {"status": "partial"},
                        "evidence": [
                            {
                                "id": "e1",
                                "publication_id": "direct-a",
                                "source_document": "a.xml",
                                "statement": "A direct result.",
                                "passage": "Context. A direct result.",
                                "passage_start": 0,
                                "passage_end": 25,
                                "extraction_method": "test",
                            }
                        ],
                    }
                )
            )
            case = {
                "id": "case",
                "publications": [
                    {"doi": "10.1/a", "relevance": "direct"},
                    {"doi": "10.1/b", "relevance": "direct"},
                    {"doi": "10.1/c", "relevance": "direct"},
                    {"doi": "10.1/noise", "relevance": "distractor"},
                ],
            }
            report = evaluate_reference_case(root, case)
            self.assertEqual(report.known_reference_discovery_recall, 0.6667)
            self.assertEqual(report.known_reference_acquisition_recall, 0.3333)
            self.assertEqual(report.known_reference_evidence_recall, 0.3333)
            self.assertEqual(report.distractors_excluded_at_screening, 1)
            self.assertEqual(report.provenance_completeness, 1.0)
            self.assertEqual(report.missing_direct_dois, ("10.1/c",))


if __name__ == "__main__":
    unittest.main()
