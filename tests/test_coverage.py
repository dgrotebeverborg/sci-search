from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from sci_search.corpus import CorpusDocument
from sci_search.coverage import (
    assess_answer_adequacy,
    coverage_follow_up_queries,
    decompose_question,
    evidence_context,
    gate_model_analysis,
)
from sci_search.discovery import PublicationCandidate, SearchQuery
from sci_search.fulltext_acquisition import AcquisitionOutcome
from sci_search.generic_research import GenericResearchEngine
from sci_search.models import EvidenceType, Publication, ResultNature
from sci_search.question_interpretation import interpret_question
from sci_search.question_planning import plan_question
from sci_search.research_runs import ResearchLimits, ResearchRunManager

QUESTION = "What are the trends and changes in the number or extent of wildfires in Europe during the 21st century?"


def document(identifier: str, title: str, text: str) -> CorpusDocument:
    return CorpusDocument(
        publication=Publication(identifier, title, f"papers/{identifier}.txt", year=2024),
        text=f"## Results\n\n{text}\n",
        evidence_type=EvidenceType.OBSERVATIONAL_STUDY,
        result_nature=ResultNature.MEASURED,
        technology="wildfire monitoring",
        configuration=None,
        system_scale="European",
        calculation_boundary=None,
        assumptions=(),
    )


NARROW = document(
    "narrow",
    "European wildfires during the 2003 event",
    "Wildfire emissions in Europe during the single extreme event in 2003 were estimated with an atmospheric model.",
)
TREND_DOCUMENTS = (
    document(
        "area",
        "Long-term European wildfire burned-area trends",
        "A long-term time series of wildfire burned area in Europe from 2001 to 2020 showed a decreasing trend in the annual extent.",
    ),
    document(
        "frequency",
        "Changes in European wildfire frequency",
        "Annual wildfire frequency in Europe increased between 2003 and 2022, although the direction varied among Mediterranean regions.",
    ),
    document(
        "regional",
        "Regional European wildfire trends",
        "Multi-decadal European wildfire records from 2001 to 2021 showed mixed trends in fire count and burned area across regions.",
    ),
)


class CoverageAssessmentTests(unittest.TestCase):
    def test_explanation_can_refer_to_subjects_in_its_own_passage(self) -> None:
        question = "Why do studies report different effects of biochar application on crop yield?"
        for explanation in (
            "The differences were explained by soil pH and rainfall.",
            "However, these differences were explained by soil pH and rainfall.",
            "Differences were explained by soil pH and rainfall.",
        ):
            for context, expected in (
                ("Biochar and crop yield. ", True),
                ("Tomato germination. ", False),
            ):
                with self.subTest(context=context, explanation=explanation):
                    text = (
                        "Biochar application increased crop yield by 15 percent "
                        "compared with untreated plots.\n\n" + context + explanation
                    )
                    papers = tuple(
                        document(f"paper-{i}", "Biochar application and crop yield", text)
                        for i in range(2)
                    )
                    report = GenericResearchEngine(papers).investigate(question)
                    self.assertEqual(
                        report.answer_adequacy["can_answer_overall_question"], expected
                    )
                    if expected:
                        self.assertNotIn(
                            "direct evidence explaining differences between studies",
                            report.answer_adequacy["missing_requirements"],
                        )

    def test_task_evidence_outside_requested_scope_cannot_unlock_overall_answer(self) -> None:
        for requirement, statement in (
            ("requires_method_evidence", "A sensor records wildfire extent."),
            ("requires_method_limitations", "However, sampling has a bias."),
            ("requires_explanatory_evidence", "Extent varies because rainfall differs."),
            ("requires_explanatory_evidence", "These differences were explained by rainfall."),
            (
                "requires_diagnostic_metrics",
                "Sensitivity was 95% against the clinical ECG reference standard.",
            ),
            ("requires_exact_global_count", "The global population count is 100 individuals."),
        ):
            scope = {
                "task": "comparison",
                "dimensions": [
                    {"id": "subject:primary", "kind": "subject", "required": True},
                    {
                        "id": "geography:europe",
                        "kind": "geography",
                        "required": True,
                        "statement_required": True,
                    },
                    {"id": "outcome:extent", "kind": "outcome", "required": True},
                ],
                "requirements": {"minimum_independent_publications": 1, requirement: True},
            }
            dimensions = ["subject:primary", "geography:europe", "outcome:extent"]
            topical = {
                "id": "topical",
                "publication_id": "local-study",
                "statement": "European wildfire extent was reported.",
                "scope_dimension_ids": dimensions,
                "statement_dimension_ids": dimensions,
            }
            donor = {
                "id": "task-evidence",
                "publication_id": "other-study",
                "statement": statement,
                "numerical_mentions": ["95%", "100"],
                "scope_dimension_ids": dimensions,
                "statement_dimension_ids": dimensions,
            }
            for field, missing in (
                ("scope_dimension_ids", "subject:primary"),
                ("statement_dimension_ids", "geography:europe"),
                ("statement_dimension_ids", "outcome:extent"),
            ):
                with self.subTest(requirement=requirement, field=field, missing=missing):
                    outside_scope = {**donor, field: [d for d in dimensions if d != missing]}
                    report = assess_answer_adequacy([topical, outside_scope], scope)
                    self.assertFalse(report["can_answer_overall_question"])
                    self.assertEqual(report["status"], "partial")
                    self.assertNotIn("task-evidence", report["answer_evidence_ids"])
                    task_checks = [
                        check
                        for check in report["checks"]
                        if check["kind"] == "task" or check["id"] == "coverage:exact_global_count"
                    ]
                    self.assertEqual(len(task_checks), 1)
                    self.assertFalse(task_checks[0]["passed"])
            with self.subTest(requirement=requirement, scope="matching"):
                report = assess_answer_adequacy([topical, donor], scope)
                self.assertTrue(report["can_answer_overall_question"])
                self.assertIn("task-evidence", report["answer_evidence_ids"])

    def test_exact_global_population_question_requires_a_current_numeric_census(self) -> None:
        report = GenericResearchEngine(
            (
                document(
                    "genomics",
                    "Genomics of wild goats",
                    "A global genomic study used 194 samples from wild goat populations to examine adaptation in 2025.",
                ),
            )
        ).investigate("What is the exact global population of wild goats in 2025?")
        self.assertFalse(report.answer_adequacy["can_answer_overall_question"])
        self.assertIn(
            "verifiable exact global census for the requested year",
            report.answer_adequacy["missing_requirements"],
        )
        self.assertFalse(report.summary_evidence_ids)

    def test_broad_european_precipitation_trend_rejects_off_region_and_narrow_regions(self) -> None:
        papers = (
            document(
                "south-africa",
                "Fire weather",
                "Since 2000, precipitation increased in western South Africa.",
            ),
            document(
                "arctic",
                "Arctic projections",
                "During the 21st century, Arctic precipitation is projected to increase.",
            ),
            document(
                "south-europe",
                "Southern Europe rainfall",
                "During the 21st century, precipitation increased in Southern Europe.",
            ),
        )
        report = GenericResearchEngine(papers).investigate(
            "Has European precipitation increased during the 21st century?"
        )
        self.assertFalse(report.answer_adequacy["can_answer_overall_question"])
        self.assertIn(
            "continent-wide or explicitly heterogeneous regional synthesis",
            report.answer_adequacy["missing_requirements"],
        )
        self.assertFalse(report.summary_evidence_ids)

    def test_method_comparison_requires_method_and_limitation_statements(self) -> None:
        topical = document(
            "competition",
            "Goat habitat competition",
            "Free-ranging goats reduced forage availability for wild ungulates in their preferred habitat.",
        )
        report = GenericResearchEngine((topical,)).investigate(
            "What methods are used to measure diet selection in free-ranging goats, and how do their limitations differ?"
        )
        self.assertFalse(report.answer_adequacy["can_answer_overall_question"])
        self.assertIn(
            "direct evidence about measurement methods",
            report.answer_adequacy["missing_requirements"],
        )
        self.assertIn(
            "source-reported method limitations", report.answer_adequacy["missing_requirements"]
        )

    def test_why_question_requires_direct_explanatory_evidence(self) -> None:
        positive = document(
            "yield",
            "Biochar and crop yield",
            "Biochar application increased crop yield by 15 percent compared with untreated plots.",
        )
        report = GenericResearchEngine((positive,)).investigate(
            "Why do studies report different effects of biochar application on crop yield?"
        )
        self.assertFalse(report.answer_adequacy["can_answer_overall_question"])
        self.assertIn(
            "direct evidence explaining differences between studies",
            report.answer_adequacy["missing_requirements"],
        )

    def test_pdf_line_wrapping_does_not_hide_a_compound_scientific_subject(self) -> None:
        question = "What has been the change in precipitation over the Greenland Ice Sheet during the 21st century?"
        plan = plan_question(question)
        scope = decompose_question(question, plan)
        context = evidence_context(
            "The Greenland\nice sheet faces a wetter future, and precipitation increases during the 21st cen-\ntury.",
            scope,
        )
        self.assertIn("subject:primary", context["scope_dimension_ids"])
        self.assertIn("outcome:precipitation", context["scope_dimension_ids"])

    def test_plural_iron_air_efficiency_question_is_planned_as_an_energy_comparison(self) -> None:
        question = "What round-trip efficiencies have been reported for iron-air batteries, and are these reported efficiencies comparable to one another?"
        plan = plan_question(question)
        self.assertEqual(plan.profile_id, "energy")
        self.assertEqual(plan.intent, "comparison")
        self.assertEqual(plan.concepts, ("round-trip efficiency", "iron-air battery"))
        scope = decompose_question(question, plan)
        self.assertEqual(scope["requirements"]["minimum_independent_publications"], 2)
        self.assertIn("outcome:efficiency", {item["id"] for item in scope["dimensions"]})
        queries = coverage_follow_up_queries(
            question,
            scope,
            {
                "status": "partial",
                "missing_requirements": ["independent contributing publications"],
            },
        )
        self.assertTrue(any('"round-trip efficiency"' in item.text for item in queries))
        self.assertFalse(
            any("independent contributing publications" in item.text for item in queries)
        )

    def test_planner_separates_task_and_time_words_from_scientific_concepts(self) -> None:
        plan = plan_question(QUESTION)
        self.assertEqual(plan.intent, "temporal_trend")
        self.assertEqual(plan.concepts, ("number", "extent", "wildfires", "europe"))
        scope = decompose_question(QUESTION, plan)
        self.assertEqual(scope["task"], "temporal_trend")
        self.assertIn("subquestion:direction", {item["id"] for item in scope["subquestions"]})

    def test_single_extreme_episode_cannot_answer_a_multidecadal_trend_question(self) -> None:
        report = GenericResearchEngine((NARROW,)).investigate(QUESTION)
        self.assertFalse(report.answer_adequacy["can_answer_overall_question"])
        self.assertIn("multi-period trend evidence", report.answer_adequacy["missing_requirements"])
        self.assertIn("withheld an overall conclusion", report.answer_summary)
        self.assertEqual(report.summary_evidence_ids, ())

    def test_multiple_longitudinal_sources_pass_the_trend_adequacy_gate(self) -> None:
        report = GenericResearchEngine(TREND_DOCUMENTS).investigate(QUESTION)
        self.assertTrue(report.answer_adequacy["can_answer_overall_question"])
        self.assertEqual(report.answer_adequacy["trend_publications"], 3)
        self.assertTrue(report.summary_evidence_ids)
        self.assertTrue(all(item.trend_evidence for item in report.evidence))

    def test_coverage_gaps_generate_bounded_targeted_queries_and_gate_model_answer(self) -> None:
        report = GenericResearchEngine((NARROW,)).investigate(QUESTION)
        queries = coverage_follow_up_queries(
            QUESTION, report.research_scope, report.answer_adequacy
        )
        self.assertLessEqual(len(queries), 4)
        self.assertTrue(any("time series" in item.text for item in queries))
        gated = gate_model_analysis(
            {"status": "complete", "answer": {"text": "Too broad"}}, report.answer_adequacy
        )
        self.assertEqual(gated["status"], "coverage_limited")
        self.assertIsNone(gated["answer"])


class CoverageSearchLoopTests(unittest.TestCase):
    def test_online_run_searches_missing_dimensions_then_reassesses(self) -> None:
        text_by_id = {item.publication.id: item.text for item in (NARROW, *TREND_DOCUMENTS)}

        class Provider:
            name = "coverage-fixture"

            def search(self, query: SearchQuery, *, limit: int) -> tuple[PublicationCandidate, ...]:
                ids = (
                    ("area", "frequency", "regional")
                    if query.id.startswith("query:coverage:")
                    else ("narrow",)
                )
                return tuple(
                    PublicationCandidate(
                        id=value,
                        title=next(
                            item.publication.title
                            for item in (NARROW, *TREND_DOCUMENTS)
                            if item.publication.id == value
                        ),
                        abstract="European wildfire number extent trend evidence",
                        year=2024,
                        doi=f"10.1234/{value}",
                        authors=("Researcher",),
                        publication_type="article",
                        source_url=f"https://example.org/{value}",
                        has_local_fulltext=True,
                        providers=(self.name,),
                        matched_query_ids=(query.id,),
                    )
                    for value in ids
                )

        def acquire(candidate: PublicationCandidate, corpus: Path) -> AcquisitionOutcome:
            papers = corpus / "papers"
            papers.mkdir(parents=True, exist_ok=True)
            target = papers / f"{candidate.id}.txt"
            target.write_text(text_by_id[candidate.id], encoding="utf-8")
            return AcquisitionOutcome(
                candidate.id,
                "acquired",
                "fixture",
                f"papers/{candidate.id}.txt",
                "text/plain",
                target.stat().st_size,
                len(text_by_id[candidate.id]),
            )

        with tempfile.TemporaryDirectory() as temporary:
            manager = ResearchRunManager(
                Path(temporary),
                providers=(Provider(),),
                acquirer=acquire,
                openalex_api_key="fixture",
            )
            brief = interpret_question(QUESTION)
            brief["data_research"]["route"] = "literature"
            state = manager.run_sync(
                QUESTION,
                question_brief=brief,
                limits=ResearchLimits(
                    per_query=5,
                    max_selected=10,
                    max_full_texts=4,
                    max_acquisition_attempts=8,
                    citation_seed_count=0,
                    citation_neighbors_per_seed=0,
                    citation_depth=0,
                ),
            )
        self.assertEqual(state["status"], "complete")
        run = state["result"]["research_run"]
        self.assertTrue(run["coverage_search"]["performed"])
        self.assertEqual(run["coverage_search"]["additional_full_texts"], 3)
        self.assertTrue(state["result"]["answer_adequacy"]["can_answer_overall_question"])
        self.assertTrue(any(query["id"].startswith("query:coverage:") for query in run["queries"]))


if __name__ == "__main__":
    unittest.main()


def test_condition_defined_population_accepts_equivalent_wording():
    from sci_search.coverage import _population_aliases

    aliases = _population_aliases("adults with type 2 diabetes")
    assert "patients with type 2 diabetes" in aliases
    assert "type 2 diabetes" in aliases
    # Age-specific populations stay literal.
    assert _population_aliases("children with asthma") == ("children with asthma",)


def test_action_noun_concepts_accept_verbal_and_of_forms():
    from sci_search.coverage import _scope_aliases
    from sci_search.profiles import GENERIC_PROFILE

    aliases = _scope_aliases("atrial fibrillation detection", GENERIC_PROFILE, "")
    assert {"detecting atrial fibrillation", "detection of atrial fibrillation"} <= set(aliases)
    assert "af detection" in aliases


def test_consumer_qualifier_does_not_restrict_smartwatches():
    from sci_search.coverage import _scope_aliases
    from sci_search.profiles import GENERIC_PROFILE

    consumer = _scope_aliases("consumer wearable devices", GENERIC_PROFILE, "")
    assert "smartwatch" in consumer
    located = _scope_aliases("chest-patch wearable devices", GENERIC_PROFILE, "")
    assert "smartwatch" not in located
    assert "chest-patch smartwatch" in located


def test_evaluated_concepts_accept_the_evaluated_activity_wording():
    from sci_search.coverage import _evaluated_outcome_aliases, _scope_aliases
    from sci_search.profiles import GENERIC_PROFILE

    scope = _scope_aliases("accuracy of atrial fibrillation detection", GENERIC_PROFILE, "")
    assert "detecting atrial fibrillation" in scope
    outcome = _evaluated_outcome_aliases(
        "accuracy of atrial fibrillation detection", GENERIC_PROFILE
    )
    assert {"accuracy in detecting atrial fibrillation", "af detection accuracy"} <= set(outcome)
    assert "sensitivity" not in outcome
    assert _evaluated_outcome_aliases("hba1c", GENERIC_PROFILE) == ("hba1c",)


def _statement_ids(statement: str, passage: str, document: str, scope: dict) -> set[str]:
    from sci_search.coverage import evidence_context, statement_scope

    return set(
        evidence_context(statement, statement_scope(scope, passage, document))[
            "scope_dimension_ids"
        ]
    )


_ACIDIFICATION_SCOPE = {
    "dimensions": [
        {
            "id": "topic:0",
            "kind": "topic",
            "terms": ["ocean acidification"],
            "required": True,
            "statement_required": True,
        }
    ]
}


def test_statement_may_use_head_noun_of_phrase_named_in_its_passage():
    statement = "Calcification declined in scleractinian corals under acidification."
    passage = "We exposed corals to ocean acidification for 60 days. " + statement
    assert _statement_ids(statement, passage, passage, _ACIDIFICATION_SCOPE) == {"topic:0"}


def test_head_noun_alone_does_not_count_without_full_phrase_nearby():
    statement = "Calcification declined in corals under acidification."
    assert _statement_ids(statement, statement, statement, _ACIDIFICATION_SCOPE) == set()


def test_statement_may_use_abbreviation_its_document_defines():
    document = "Ocean acidification (OA) threatens reefs. Later text."
    statement = "Coral calcification generally decreases under OA."
    assert _statement_ids(statement, statement, document, _ACIDIFICATION_SCOPE) == {"topic:0"}
    assert (
        _statement_ids(statement, statement, "No definition here.", _ACIDIFICATION_SCOPE) == set()
    )


def test_generic_head_noun_does_not_stand_in_for_phrase():
    scope = {
        "dimensions": [
            {
                "id": "topic:0",
                "kind": "topic",
                "terms": ["class size reduction"],
                "required": True,
                "statement_required": True,
            }
        ]
    }
    passage = "Class size reduction was evaluated. A reduction in fees had no effect."
    assert _statement_ids("A reduction in fees had no effect.", passage, passage, scope) == set()


def test_study_population_named_in_methods_scopes_result_passages():
    filler = " ".join(f"Unrelated calibration note {i} about the testing room." for i in range(80))
    paper = CorpusDocument(
        publication=Publication("sleep", "Sleep and memory", "papers/sleep.txt", year=2024),
        text=(
            "## Methods\n\nThirty healthy adults were enrolled in the laboratory study.\n\n"
            f"## Discussion\n\n{filler}\n\n"
            "## Results\n\nWorking memory accuracy declined after 36 h of sleep deprivation.\n"
        ),
        evidence_type=EvidenceType.OBSERVATIONAL_STUDY,
        result_nature=ResultNature.MEASURED,
        technology=None,
        configuration=None,
        system_scale=None,
        calculation_boundary=None,
        assumptions=(),
    )
    question = "How does sleep deprivation affect working memory in adults?"
    plan = replace(
        plan_question(question),
        intent="relationship",
        subject_terms=("working memory",),
        driver_terms=("sleep deprivation",),
        population_terms=("adults",),
        concepts=("working memory", "sleep deprivation", "adults"),
    )
    report = GenericResearchEngine((paper,)).investigate(question, plan=plan)
    result_records = [item for item in report.evidence if "declined after 36 h" in item.statement]
    assert result_records
    population_ids = {
        dimension["id"]
        for dimension in report.research_scope["dimensions"]
        if dimension["kind"] == "population"
    }
    assert population_ids
    assert all(population_ids <= set(item.scope_dimension_ids) for item in result_records)
