"""Regression examples from the September 2026 benchmark; no network required."""

import json
from dataclasses import replace
from pathlib import Path

from sci_search.discovery import PublicationCandidate, screen_candidates
from sci_search.fulltext_screening import screen_full_text
from sci_search.question_planning import ResearchPlan
from sci_search.research_runs import _prioritize_acquisition_candidates


def paper(identifier, title, abstract="", **kwargs):
    return PublicationCandidate(
        id=identifier,
        title=title,
        abstract=abstract,
        year=2024,
        doi=None,
        authors=(),
        publication_type="article",
        source_url=None,
        is_open_access=True,
        has_pdf=True,
        **kwargs,
    )


def plan(subject, driver, *, question="How are these related?"):
    return ResearchPlan(
        question=question,
        profile_id="generic",
        intent="relationship",
        concepts=(subject, driver),
        entity_phrases=(subject, driver),
        expanded_terms=(subject, driver),
        evidence_preferences=(),
        comparison_dimensions=(),
        subject_terms=(subject,),
        driver_terms=(driver,),
    )


def test_language_evolution_subject_recognizes_core_subject_without_accepting_biodiversity():
    brief = plan("evolution of linguistic diversity", "social factors")
    records = screen_candidates(
        [
            paper("language", "Language diversity and cultural contact in South America"),
            paper("wrong", "Evolution of biological diversity and social factors"),
        ],
        brief,
    )
    assert {r.id: r.screening_status for r in records} == {
        "language": "selected",
        "wrong": "excluded",
    }


def test_actual_biochar_experimental_sources_survive_equivalent_wording():
    fixture = json.loads((Path(__file__).parent / "fixtures/retrieval/biochar.json").read_text())
    brief = ResearchPlan(**fixture["plan"])
    for example in (fixture["examples"][0], fixture["examples"][2]):
        decision = screen_full_text(
            brief.question, brief, PublicationCandidate(**example["candidate"]), example["text"]
        )
        assert decision.decision == "included", (example["candidate"]["title"], decision)


def test_biochar_does_not_include_crop_yield_without_biochar_or_soil_carbon_only():
    brief = plan("crop yield", "biochar application")
    for title, text in [
        (
            "Crop yield under irrigation",
            "Crop yield improved with irrigation. Crop yield was measured.",
        ),
        (
            "Biochar and soil carbon",
            "Biochar application increased soil carbon. Biochar application was tested.",
        ),
    ]:
        assert (
            screen_full_text(brief.question, brief, paper("negative", title, text), text).decision
            != "included"
        )


def test_green_space_relationship_precedes_high_citation_diabetes_reviews():
    brief = plan("type 2 diabetes", "neighborhood green space")
    direct = paper("direct", "Residential greenness and type 2 diabetes risk", relevance_score=0.5)
    generic = [
        replace(
            paper(
                f"generic-{i}",
                "Type 2 diabetes risk: systematic review",
                relevance_score=0.95,
                cited_by_count=1000,
            ),
            publication_type="review",
        )
        for i in range(6)
    ]
    more_direct = [replace(direct, id=f"direct-{i}") for i in range(6)]
    ranked = _prioritize_acquisition_candidates(generic + more_direct, brief)
    assert all(r.id.startswith("direct-") for r in ranked[:6])


def test_relationship_priority_also_applies_without_reviews():
    brief = plan("type 2 diabetes", "neighborhood green space")
    direct = paper("direct", "Residential greenness and type 2 diabetes risk", relevance_score=0.5)
    generic = paper("generic", "Type 2 diabetes clinical treatment", relevance_score=0.95)
    assert _prioritize_acquisition_candidates([generic, direct], brief)[0].id == "direct"
