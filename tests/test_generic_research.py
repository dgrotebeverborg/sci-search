from __future__ import annotations

import unittest
from pathlib import Path

from sci_search.corpus import load_corpus
from sci_search.generic_research import GenericResearchEngine, _statement_concept_coverage
from sci_search.question_planning import plan_question

ROOT = Path(__file__).resolve().parents[1]


class GenericResearchTests(unittest.TestCase):
    def test_question_plan_detects_ecology_without_changing_core_schema(self) -> None:
        plan = plan_question("How does vegetation structure affect goat foraging behaviour?")
        self.assertEqual(plan.profile_id, "ecology")
        self.assertEqual(plan.intent, "relationship")
        self.assertIn("goat", plan.concepts)
        self.assertIn("foraging behaviour", plan.concepts)

    def test_domain_phrase_alias_does_not_leak_duplicate_token_concepts(self) -> None:
        plan = plan_question("What influences goat foraging behaviour and diet selection?")
        self.assertEqual(plan.concepts, ("goat", "foraging behaviour"))

    def test_generic_investigation_is_extractively_grounded(self) -> None:
        documents = load_corpus(ROOT / "fixtures" / "iron_air_pilot")
        report = GenericResearchEngine(documents).investigate(
            "What measured round-trip efficiency is reported?"
        )
        self.assertEqual(report.mode, "generic_evidence")
        self.assertTrue(report.evidence)
        for finding in report.findings:
            for evidence_id in finding.evidence_ids:
                evidence = next(item for item in report.evidence if item.id == evidence_id)
                self.assertIn(finding.statement, evidence.passage)

    def test_no_relevant_passage_produces_no_invented_answer(self) -> None:
        documents = load_corpus(ROOT / "fixtures" / "iron_air_pilot")
        report = GenericResearchEngine(documents).investigate(
            "How do dolphins communicate with cuttlefish?"
        )
        self.assertFalse(report.evidence)
        self.assertEqual(report.findings[0].status, "insufficient_evidence")

    def test_relationship_answers_prefer_sentences_naming_all_concepts(self) -> None:
        plan = plan_question("How does salinity affect tomato seed germination?")
        direct = "Tomato seed germination was reduced by salinity."
        side_topic = "Tomato seed germination reached 90 percent after treatment."
        self.assertEqual(_statement_concept_coverage(direct, plan), len(plan.concepts))
        self.assertLess(_statement_concept_coverage(side_topic, plan), len(plan.concepts))
