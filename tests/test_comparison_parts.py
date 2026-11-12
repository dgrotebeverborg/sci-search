"""Questions with several places or subject parts are answered by combining publications.

The research plans are the interpretations of real questions; each publication needs to cover
one requested place or part, while the answer as a whole must still cover every one of them.
"""

from sci_search.coverage import assess_answer_adequacy, decompose_question, evidence_context
from sci_search.discovery import PublicationCandidate, plan_search_queries
from sci_search.fulltext_screening import screen_full_text
from sci_search.question_planning import plan_from_brief

HPV = "Did HPV vaccination lower cervical cancer incidence among young women in the Netherlands, Sweden and the United Kingdom?"
HPV_PLAN = {
    "intent": "relationship",
    "relationship_type": "influence",
    "subject_terms": ["cervical cancer"],
    "driver_terms": ["HPV vaccination"],
    "geography_terms": ["Netherlands", "Sweden", "United Kingdom"],
    "exclusion_terms": [],
    "population_terms": ["young women"],
    "time_terms": [],
    "outcome_measure_terms": ["incidence"],
    "evidence_preferences": [],
}
INSECTS = (
    "Is the decline in insect biomass in Germany since 1989 also seen in Dutch monitoring data?"
)
INSECTS_PLAN = {
    "intent": "comparison",
    "relationship_type": "unspecified",
    "subject_terms": ["insect biomass in Germany", "insect biomass in the Netherlands"],
    "driver_terms": [],
    "geography_terms": ["Germany", "Netherlands"],
    "exclusion_terms": [],
    "population_terms": [],
    "time_terms": ["since 1989"],
    "outcome_measure_terms": ["biomass"],
    "evidence_preferences": [],
}
EURO = "Did the introduction of the euro change inflation in Southern versus Northern Europe?"
EURO_PLAN = {
    "intent": "relationship",
    "relationship_type": "influence",
    "subject_terms": ["inflation in Southern Europe", "inflation in Northern Europe"],
    "driver_terms": ["introduction of the euro"],
    "geography_terms": ["Southern Europe", "Northern Europe"],
    "exclusion_terms": [],
    "population_terms": [],
    "time_terms": [],
    "outcome_measure_terms": [],
    "evidence_preferences": [],
}
PFAS = "Have concentrations of PFAS in European drinking water and surface water fallen since the PFOS restriction in 2009?"
PFAS_PLAN = {
    "intent": "temporal_trend",
    "relationship_type": "unspecified",
    "subject_terms": ["PFAS in drinking water", "PFAS in surface water"],
    "driver_terms": [],
    "geography_terms": ["Europe"],
    "exclusion_terms": [],
    "population_terms": [],
    "time_terms": ["since the 2009 PFOS restriction"],
    "outcome_measure_terms": ["concentrations"],
    "evidence_preferences": [],
}


def plan(question, structure):
    return plan_from_brief(question, {"original_question": question, "research_plan": structure})


def paper(identifier, title, abstract):
    return PublicationCandidate(
        id=identifier,
        title=title,
        abstract=abstract,
        year=2021,
        doi=None,
        authors=(),
        publication_type="article",
        source_url=None,
    )


def hpv_paper(country):
    title = f"Cervical cancer incidence after HPV vaccination among young women in {country}"
    abstract = (
        f"We investigated cervical cancer incidence among young women in {country} after HPV "
        "vaccination was introduced."
    )
    body = (
        f"{title}\n{abstract}\nIn {country}, HPV vaccination of young women was followed by a "
        "lower cervical cancer incidence. Vaccinated young women had a lower incidence of "
        f"cervical cancer than unvaccinated young women in {country}.\n"
    )
    return paper(country, title, abstract), body


def test_places_are_removed_from_the_subject():
    assert plan(INSECTS, INSECTS_PLAN).subject_terms == ("insect biomass",)
    assert plan(EURO, EURO_PLAN).subject_terms == ("inflation",)
    assert plan(PFAS, PFAS_PLAN).subject_terms == (
        "pfas in drinking water",
        "pfas in surface water",
    )


def test_a_study_of_one_requested_country_is_included():
    item, text = hpv_paper("Sweden")
    decision = screen_full_text(HPV, plan(HPV, HPV_PLAN), item, text)
    assert decision.decision == "included", decision.reason


def test_a_study_of_no_requested_country_is_excluded():
    item, text = hpv_paper("Brazil")
    decision = screen_full_text(HPV, plan(HPV, HPV_PLAN), item, text)
    assert decision.decision == "excluded"
    assert "outside required scope" in decision.reason


def test_the_krefeld_study_covers_the_insect_biomass_subject():
    title = "More than 75 percent decline over 27 years in total flying insect biomass in protected areas"
    abstract = (
        "We used a standardized protocol to measure total insect biomass using Malaise traps, "
        "deployed over 27 years in 63 nature protection areas in Germany."
    )
    body = (
        f"{title}\n{abstract}\nFlying insect biomass declined by 76% between 1989 and 2016. "
        "Insect biomass in Germany fell in every habitat type. Biomass declined by 82% in "
        "midsummer.\n"
    )
    decision = screen_full_text(
        INSECTS, plan(INSECTS, INSECTS_PLAN), paper("krefeld", title, abstract), body
    )
    assert "insect biomass" in decision.matched_groups
    assert decision.decision == "included", decision.reason


def test_a_surface_water_study_is_not_excluded_for_missing_drinking_water():
    title = "Trends in PFAS concentrations in European surface water since 2009"
    abstract = (
        "We analysed PFAS in surface water from rivers across Europe and report the trend in "
        "PFAS concentrations between 2009 and 2021."
    )
    body = (
        f"{title}\n{abstract}\nPFAS in surface water declined across Europe: PFOS concentrations "
        "fell from 2009 to 2021 in a long-term time series. The trend in PFAS in surface water "
        "was downward at most European sites between 2009 and 2021.\n"
    )
    decision = screen_full_text(PFAS, plan(PFAS, PFAS_PLAN), paper("pfas", title, abstract), body)
    assert decision.decision != "excluded", decision.reason


def record(identifier, text, scope):
    context = evidence_context(text, scope)
    return {
        "id": identifier,
        "publication_id": identifier,
        "statement": text,
        "passage": text,
        "scope_dimension_ids": context["scope_dimension_ids"],
        "statement_dimension_ids": context["scope_dimension_ids"],
        "trend_evidence": context["trend_evidence"],
        "statement_trend_signal": context["trend_signal"],
        "direction": context["direction"],
        "time_mentions": context["time_mentions"],
    }


def test_studies_of_different_countries_together_contribute_to_the_answer():
    scope = decompose_question(HPV, plan(HPV, HPV_PLAN))
    evidence = [
        record(
            country,
            f"In {country}, HPV vaccination of young women lowered cervical cancer incidence.",
            scope,
        )
        for country in ("Netherlands", "Sweden")
    ]
    checks = {c["id"]: c for c in assess_answer_adequacy(evidence, scope)["checks"]}
    assert checks["coverage:independent_publications"]["publication_count"] == 2
    assert checks["coverage:geography:netherlands"]["passed"]
    assert checks["coverage:geography:sweden"]["passed"]
    # The answer as a whole still needs the third country.
    assert not checks["coverage:geography:united_kingdom"]["passed"]


def test_each_subject_part_is_checked_across_the_answer():
    scope = decompose_question(PFAS, plan(PFAS, PFAS_PLAN))
    evidence = [
        record(
            "surface",
            "PFAS in surface water in Europe declined between 2009 and 2021 in a long-term trend.",
            scope,
        )
    ]
    checks = assess_answer_adequacy(evidence, scope)["checks"]
    parts = {c["label"]: c for c in checks if c["kind"] == "subject_part"}
    assert parts["pfas in surface water"]["publication_count"] == 1
    assert parts["pfas in drinking water"]["publication_count"] == 0
    assert not parts["pfas in drinking water"]["passed"]


def test_each_requested_country_and_part_gets_its_own_search():
    _, queries = plan_search_queries(HPV, plan=plan(HPV, HPV_PLAN))
    texts = [q.text.casefold() for q in queries]
    for country in ("netherlands", "sweden", "united kingdom"):
        assert any(
            country in t
            and "cervical cancer" in t
            and sum(c in t for c in ("netherlands", "sweden", "united kingdom")) == 1
            for t in texts
        ), country
    _, queries = plan_search_queries(PFAS, plan=plan(PFAS, PFAS_PLAN))
    texts = [q.text.casefold() for q in queries]
    assert any("surface water" in t and "drinking water" not in t for t in texts)
    assert any("drinking water" in t and "surface water" not in t for t in texts)
