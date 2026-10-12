"""Regression cases from the South American linguistic-diversity run."""

from dataclasses import replace

import pytest

from sci_search.coverage import assess_answer_adequacy, decompose_question, evidence_context
from sci_search.discovery import PublicationCandidate, plan_search_queries, screen_candidates
from sci_search.fulltext_screening import screen_full_text
from sci_search.question_planning import plan_question

QUESTION = (
    "The role of social and biophysical factors in the evolution of "
    "linguistic diversity in South America"
)


def paper(title, abstract=""):
    return PublicationCandidate(
        id=title,
        title=title,
        abstract=abstract,
        year=2024,
        doi=None,
        authors=(),
        publication_type="article",
        source_url=None,
        is_open_access=True,
        has_pdf=True,
    )


def test_explanation_keeps_outcome_and_geography_in_search():
    plan, queries = plan_search_queries(QUESTION)
    assert plan.intent == "relationship"
    assert plan.concepts[0] == "linguistic diversity"
    assert "south america" in plan.concepts
    assert not {"role", "factors", "evolution", "south", "america"} & set(plan.concepts)
    for query in queries:
        assert "linguistic diversity" in query.text.lower()
        assert "south america" in query.text.lower()
        assert "time series" not in query.text.lower()
    scope = decompose_question(QUESTION, plan)
    subject = scope["dimensions"][0]
    assert subject["terms"] == ["linguistic diversity"]
    assert not any(d["id"] == "task:temporal_trend" for d in scope["dimensions"])


def test_explanatory_pattern_is_not_specific_to_linguistics():
    plan = plan_question(
        "The role of temperature and pressure in the formation of mineral deposits in Europe"
    )
    assert plan.intent == "relationship"
    assert plan.concepts[0] == "mineral deposits"
    assert "europe" in plan.concepts
    assert (
        plan_question("How has linguistic diversity changed over time?").intent == "temporal_trend"
    )


@pytest.mark.parametrize(
    "question",
    [
        "What role do social and biophysical factors play in the evolution of linguistic diversity in South America?",
        "How do social and biophysical factors influence the evolution of linguistic diversity in South America?",
        "How do social and biophysical factors influence changes in linguistic diversity in South America?",
        "How do social and biophysical factors influence variation in linguistic diversity in South America?",
    ],
)
def test_explanatory_paraphrases_keep_the_same_subject(question):
    plan = plan_question(question)
    assert plan.intent == "relationship"
    assert plan.concepts == plan_question(QUESTION).concepts


def test_driver_phrases_are_not_split_into_unrelated_words():
    plan = plan_question(
        "The role of population density and rainfall in language diversity in South America"
    )
    assert "population density" in plan.concepts
    assert "population" not in plan.concepts


def test_metadata_admits_subject_papers_without_every_driver_keyword():
    items = [
        paper("Linguistic Diversity and Plurality in Meso- and South America"),
        paper(
            "River systems and languages",
            "Linguistic diversity in South America reflects river networks.",
        ),
        paper(
            "Vegetable diversity in South America",
            "Social and biophysical factors shape crop evolution.",
        ),
    ]
    results = {p.id: p for p in screen_candidates(items, plan_question(QUESTION))}
    assert results[items[0].id].screening_status == "selected"
    assert results[items[1].id].screening_status == "selected"
    assert results[items[2].id].screening_status == "excluded"


def test_fulltext_accepts_one_driver_without_requiring_both_in_every_paper():
    item = paper("Social factors and linguistic diversity in South America")
    text = "Social contact shapes linguistic diversity in South America. We compare linguistic diversity across communities."
    assert screen_full_text(QUESTION, plan_question(QUESTION), item, text).decision == "included"
    assert (
        screen_full_text(
            QUESTION,
            plan_question(QUESTION),
            replace(item, title="Language diversity and environmental factors in Brazil"),
            "Environmental factors influence language diversity in Brazil. Language diversity varies across rivers.",
        ).decision
        == "included"
    )


def test_incidental_geography_does_not_make_a_foreign_study_in_scope():
    item = paper(
        "Cultural and Linguistic Diversity in Medieval Britain Society",
        "Social factors shape linguistic diversity in medieval Britain.",
    )
    text = (
        "Social factors shaped linguistic diversity in medieval Britain. " * 3
        + "Elsewhere, a comparison of South America and China is mentioned."
    )
    assert screen_full_text(QUESTION, plan_question(QUESTION), item, text).decision != "included"


def test_mexican_plant_use_and_crop_diversity_are_not_south_american_language_evidence():
    items = [
        paper(
            "Biodiversity and linguistic diversity in Mexican ethnobotany",
            "We study plant use by Mexican groups in Latin America.",
        ),
        paper(
            "Vegetable landraces in Brazil and Uruguay",
            "Social factors influence genetic diversity.",
        ),
    ]
    for item in items:
        text = (item.title + ". " + item.abstract + " ") * 3
        assert (
            screen_full_text(QUESTION, plan_question(QUESTION), item, text).decision != "included"
        )


def test_global_study_needs_regional_evidence_in_subject_context():
    item = paper(
        "Global drivers of linguistic diversity",
        "We investigate global linguistic diversity and environmental factors.",
    )
    text = "Environmental factors explain linguistic diversity in South America. Linguistic diversity varies with river systems."
    assert screen_full_text(QUESTION, plan_question(QUESTION), item, text).decision == "included"
    assert (
        screen_full_text(
            QUESTION, plan_question(QUESTION), item, text.replace("South America", "Europe")
        ).decision
        != "included"
    )


def test_driver_coverage_can_come_from_different_studies():
    scope = decompose_question(QUESTION, plan_question(QUESTION))
    evidence = []
    for index, driver in enumerate(("social", "social", "biophysical", "biophysical")):
        statement = f"Linguistic diversity in South America is explained by {driver} factors."
        context = evidence_context(statement, scope)
        evidence.append(
            {
                "id": str(index),
                "publication_id": str(index),
                "statement": statement,
                "passage": statement,
                **context,
                "statement_dimension_ids": context["scope_dimension_ids"],
            }
        )
    result = assess_answer_adequacy(evidence, scope)
    assert result["qualifying_publications"] == 4
    assert result["can_answer_overall_question"]
    # Two social studies alone cannot establish coverage of biophysical drivers.
    assert not assess_answer_adequacy(evidence[:2], scope)["can_answer_overall_question"]
    unrelated = "Biophysical factors determine crop yields in Europe."
    context = evidence_context(unrelated, scope)
    distractor = {
        "id": "unrelated",
        "publication_id": "unrelated",
        "statement": unrelated,
        "passage": unrelated,
        **context,
        "statement_dimension_ids": context["scope_dimension_ids"],
    }
    result = assess_answer_adequacy([*evidence[:2], distractor], scope)
    assert not result["can_answer_overall_question"]
    assert "biophysical" in result["missing_requirements"]


@pytest.mark.parametrize(
    ("title", "abstract"),
    [
        (
            "HIV/AIDS in the state of Amazonas, Brazilian Amazon",
            "Amazonas is Brazil's largest state: vast territories connected mainly by rivers, "
            "high cultural and linguistic diversity, and multiple co-endemic infections. "
            "This review synthesizes programmatic changes in HIV services and community action.",
        ),
        (
            "Urban biocultural diversity in a Brazilian favela",
            "Biocultural diversity has traditionally highlighted coevolution between biodiverse "
            "regions and the linguistic diversity of indigenous communities. "
            "We investigate human-nature relationships in Rio de Janeiro, Brazil.",
        ),
    ],
)
def test_background_subject_mentions_need_adjudication(title, abstract):
    item = paper(title, abstract)
    text = (
        abstract + "\nIntroduction\nCultural and linguistic diversity in Brazil provides "
        "the social and environmental context for the study.\nResults\n"
        "Our findings concern access to local services and public facilities."
    )
    decision = screen_full_text(QUESTION, plan_question(QUESTION), item, text)
    assert decision.decision == "uncertain"
    assert "focus" in decision.reason.lower()


def test_research_subject_in_abstract_establishes_focus_without_title_match():
    item = paper(
        "Human expansion and population structure in the Americas",
        "Demographic events shaped human settlement. We find spatial structure in linguistic "
        "diversity in South America after social contact is accounted for.",
    )
    text = item.abstract + " Social contact explains linguistic diversity in South America."
    assert screen_full_text(QUESTION, plan_question(QUESTION), item, text).decision == "included"


def test_explanatory_abstract_focus_is_domain_independent():
    question = "The role of rainfall in mineral deposits in South America"
    item = paper(
        "Weathering processes in Brazil",
        "We investigate how rainfall controls mineral deposits in Brazil.",
    )
    assert (
        screen_full_text(question, plan_question(question), item, item.abstract).decision
        == "included"
    )


def test_simple_effect_question_preserves_atomic_outcomes_for_retrieval():
    plan = plan_question("How does salinity affect tomato seed germination?")
    assert {"salinity", "tomato", "germination"} <= set(plan.concepts)
    scope = decompose_question(plan.question, plan)
    subject = next(d for d in scope["dimensions"] if d["kind"] == "subject")
    assert "tomato seed germination" not in subject["terms"]


def test_simple_effect_question_preserves_canonical_alias_planning():
    first = plan_question("How does El Niño affect weather patterns in Europe?")
    second = plan_question("What is the influence of ENSO on European weather patterns?")
    assert "el niño" in first.concepts
    assert "el niño" in second.concepts
    assert "weather" in first.concepts
    assert "weather" in second.concepts
    assert "weather patterns" not in first.concepts


def test_simple_effect_question_keeps_a_recognized_explanatory_subject():
    question = "How does rainfall affect linguistic diversity in South America?"
    plan = plan_question(question)
    assert plan.concepts == ("linguistic diversity", "south america", "rainfall")
    scope = decompose_question(question, plan)
    subject = next(d for d in scope["dimensions"] if d["kind"] == "subject")
    assert subject["terms"] == ["linguistic diversity"]
    assert scope["requirements"]["alternative_driver_dimensions"] == ["topic:0"]
