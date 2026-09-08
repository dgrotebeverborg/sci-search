from __future__ import annotations

import json
import unittest
from pathlib import Path

import pytest

from sci_search.metamorphic_evaluation import evaluate_metamorphic_cases
from sci_search.reliability_audit import _audit_run

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.retained_corpus
class ReliabilityAuditTests(unittest.TestCase):
    def test_counterfactual_and_paraphrase_suite_passes(self) -> None:
        result = evaluate_metamorphic_cases(ROOT / "benchmarks" / "metamorphic_questions.json")
        self.assertEqual(result["case_count"], 20)
        self.assertEqual(
            result["failed"],
            0,
            [(case["id"], case["failures"]) for case in result["cases"] if not case["passed"]],
        )

    def test_historical_el_nino_failure_is_detected_by_current_gates(self) -> None:
        directory = ROOT / "data" / "research_runs" / "20260818T123406Z-a820ed99"
        state = json.loads((directory / "run.json").read_text(encoding="utf-8"))
        investigation = json.loads((directory / "investigation.json").read_text(encoding="utf-8"))
        result = _audit_run(directory, state, investigation)
        self.assertTrue(result.unsafe_historical_answer)
        self.assertEqual(result.stored_exact_provenance, result.stored_evidence)
        self.assertEqual(result.current_adequacy, "insufficient")
        self.assertEqual(result.current_evidence, 0)

    def test_corrected_el_nino_run_withholds_without_losing_source_integrity(self) -> None:
        directory = ROOT / "data" / "research_runs" / "20260818T125111Z-e8f44395"
        state = json.loads((directory / "run.json").read_text(encoding="utf-8"))
        investigation = json.loads((directory / "investigation.json").read_text(encoding="utf-8"))
        result = _audit_run(directory, state, investigation)
        self.assertFalse(result.unsafe_historical_answer)
        self.assertFalse(result.current_answer_supported)
        self.assertEqual(result.stored_exact_provenance, result.stored_evidence)


if __name__ == "__main__":
    unittest.main()
