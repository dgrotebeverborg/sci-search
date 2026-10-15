import json
from dataclasses import replace
from pathlib import Path

from sci_search.coverage import decompose_question, evidence_context
from sci_search.discovery import PublicationCandidate, screen_candidates
from sci_search.fulltext_screening import screen_full_text
from sci_search.question_planning import plan_from_brief


def example():
    data = json.loads((Path(__file__).parent / "fixtures/retrieval/hydrogen.json").read_text())
    return (
        data,
        plan_from_brief(data["question"], data["brief"]),
        PublicationCandidate(**data["candidate"]),
    )


def test_exact_source_abstract_cannot_be_discarded_as_missing_its_subject():
    _, plan, candidate = example()
    screened = screen_candidates([candidate], plan)[0]
    assert screened.screening_status == "unavailable"  # relevant, but no download URL supplied
    downloadable = replace(candidate, full_text_url="https://example.org/paper.pdf", has_pdf=True)
    assert screen_candidates([downloadable], plan)[0].screening_status == "selected"


def test_compound_subject_survives_fulltext_and_coverage_checks():
    data, plan, candidate = example()
    # Exercise the same relevance rules on a source-grounded passage, not a fake title match.
    decision = screen_full_text(data["question"], plan, candidate, candidate.abstract)
    assert decision.decision in {"included", "uncertain"}, decision
    assert decision.core_groups_matched == 1
    context = evidence_context(candidate.abstract, decompose_question(data["question"], plan))
    assert "subject:primary" in context["scope_dimension_ids"]


def test_solar_or_wind_does_not_require_both_sources():
    _, plan, candidate = example()
    text = (
        "This study examines configurations of off-grid hydrogen supply chains for "
        "hydrogen-based steelmaking powered by solar energy. We evaluate their "
        "techno-economic feasibility and CO2 emissions."
    )
    solar = replace(
        candidate,
        title="Off-grid solar hydrogen supply chains for steelmaking",
        abstract=text,
        has_pdf=True,
        full_text_url="https://example.org/solar.pdf",
    )
    assert screen_candidates([solar], plan)[0].screening_status == "selected"
    wind = replace(
        solar, title=solar.title.replace("solar", "wind"), abstract=text.replace("solar", "wind")
    )
    assert screen_candidates([wind], plan)[0].screening_status == "selected"


def test_related_energy_papers_missing_requested_industry_are_excluded():
    _, plan, candidate = example()
    text = (
        "This study examines configurations of off-grid hydrogen supply chains for "
        "maritime transport powered by solar or wind energy. We evaluate their "
        "techno-economic feasibility and CO2 emissions."
    )
    unrelated = replace(candidate, title="Hydrogen supply chains for shipping", abstract=text)
    assert screen_candidates([unrelated], plan)[0].screening_status == "excluded"


def test_oa_repository_landing_page_can_be_acquired_and_survives_serialization():
    from dataclasses import asdict

    from sci_search.discovery import merge_candidates
    from sci_search.research_runs import _publication_candidate

    _, plan, candidate = example()
    repository = "https://repository.example.org/handle/123"
    with_location = replace(candidate, oa_landing_urls=(repository,))
    restored = _publication_candidate(asdict(with_location))
    assert restored.oa_landing_urls == (repository,)
    merged = merge_candidates([candidate, restored])[0]
    assert merged.oa_landing_urls == (repository,)
    assert screen_candidates([merged], plan)[0].screening_status == "selected"
    closed = replace(merged, is_open_access=False)
    assert screen_candidates([closed], plan)[0].screening_status == "unavailable"


def test_scientific_polarity_is_preserved_across_screening_and_coverage():
    from sci_search.coverage import _contains as coverage_contains
    from sci_search.discovery import _term_in_text
    from sci_search.fulltext_screening import _contains as fulltext_contains

    for match in (coverage_contains, fulltext_contains):
        assert not match("HER2-negative breast cancer", "HER2+")
    assert not _term_in_text("HER2+", "HER2-negative breast cancer")


def test_retrieval_and_extraction_use_the_same_compound_subject_match():
    from sci_search.profiles import contains_term

    _, plan, candidate = example()
    assert contains_term(candidate.abstract, plan.subject_terms[0])
    assert not contains_term("HER2-negative breast cancer", "HER2+")


def test_study_passages_recognize_the_same_compound_subject_as_screening():
    from sci_search.study_matrix import _select_passages

    data, plan, candidate = example()
    dimensions = decompose_question(data["question"], plan)["dimensions"]
    passages = _select_passages(candidate.id, candidate.abstract, dimensions)
    assert any("subject:primary" in p["matched_dimension_ids"] for p in passages)
