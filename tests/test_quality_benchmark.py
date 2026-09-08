from __future__ import annotations

import unittest
from pathlib import Path

import pytest

from sci_search.corpus import load_corpus
from sci_search.generic_research import GenericResearchEngine
from sci_search.quality_benchmark import evaluate_quality_benchmark
from sci_search.question_planning import plan_question
from sci_search.researcher_benchmark import validate_researcher_benchmark

ROOT = Path(__file__).resolve().parents[1]


class QualityBenchmarkTests(unittest.TestCase):
    def test_locked_researcher_question_benchmark_is_valid_and_plannable(self) -> None:
        result = validate_researcher_benchmark(ROOT / "benchmarks" / "researcher_questions_v1.json")
        self.assertEqual(result["case_count"], 24)
        self.assertEqual(result["failed"], 0, result["failures"])

    @pytest.mark.retained_corpus
    def test_diverse_question_benchmark_passes_with_exact_provenance(self) -> None:
        result = evaluate_quality_benchmark(ROOT / "benchmarks" / "diverse_questions.json")
        self.assertEqual(result["case_count"], 43)
        self.assertEqual(
            result["failed"],
            0,
            [(case["id"], case["failures"]) for case in result["cases"] if not case["passed"]],
        )

    def test_energy_efficiency_rebound_is_not_misclassified_as_battery_research(self) -> None:
        plan = plan_question("Why do estimates of the energy-efficiency rebound effect differ?")
        self.assertEqual(plan.profile_id, "generic")
        self.assertIn("energy-efficiency", plan.concepts)

    def test_unicode_scientific_subject_is_retained(self) -> None:
        plan = plan_question("What is the influence of El Niño on weather patterns in Europe?")
        self.assertEqual(plan.concepts, ("el niño", "weather", "europe"))

    def test_generic_compound_entities_do_not_force_unrelated_domain_profiles(self) -> None:
        climate = plan_question(
            "What influence does El Niño have on European winter temperature and precipitation?"
        )
        self.assertEqual(climate.profile_id, "generic")
        self.assertIn("european winter temperature", climate.entity_phrases)
        health = plan_question(
            "What evidence links long-term exposure to fine particulate matter with cognitive decline?"
        )
        self.assertEqual(health.profile_id, "generic")
        self.assertIn("fine particulate matter", health.entity_phrases)
        plastic = plan_question(
            "How do laboratory and field estimates of plastic degradation rates differ?"
        )
        self.assertEqual(plastic.profile_id, "generic")

    @pytest.mark.retained_corpus
    def test_iron_air_summary_leads_with_values_and_operating_context(self) -> None:
        engine = GenericResearchEngine(load_corpus(ROOT / "corpora" / "iron_air_real"))
        report = engine.investigate(
            "What round-trip efficiencies have been reported for iron-air batteries, "
            "and are these reported efficiencies comparable to one another?"
        )
        self.assertIn("82.9%", report.answer_summary)
        self.assertIn("550 °C", report.answer_summary)
        self.assertIn("0.2 C", report.answer_summary)
        self.assertIn("35 %", report.answer_summary)
        self.assertNotIn("using multi-layered air-;", report.answer_summary)
        self.assertTrue(set(report.summary_evidence_ids) <= {item.id for item in report.evidence})


if __name__ == "__main__":
    unittest.main()
