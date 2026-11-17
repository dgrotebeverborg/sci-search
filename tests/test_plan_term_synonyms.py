"""Model-supplied wording variants widen recognition of plan terms only."""

from dataclasses import replace

from sci_search.coverage import decompose_question
from sci_search.question_planning import parse_term_synonyms, plan_question


def test_synonyms_are_kept_only_for_known_terms_and_bounded():
    parsed = parse_term_synonyms(
        [
            {"term": "Freshwater Zooplankton", "synonyms": ["Daphnia", "cladocerans", "daphnia"]},
            {"term": "unknown term", "synonyms": ["x y"]},
            {"term": "survival", "synonyms": ["survival", "", "mortality", 7]},
            "malformed",
        ],
        ("freshwater zooplankton", "survival"),
    )
    assert parsed == (
        ("freshwater zooplankton", ("Daphnia", "cladocerans", "daphnia")),
        ("survival", ("mortality",)),
    )
    assert parse_term_synonyms(None, ("a",)) == ()


def test_decomposition_adds_synonyms_to_every_dimension_using_the_term():
    question = (
        "What is the effect of reducing class size on student achievement in primary schools?"
    )
    plan = replace(
        plan_question(question),
        intent="relationship",
        subject_terms=("student achievement",),
        driver_terms=("class size",),
        population_terms=("primary school students",),
        term_synonyms=(
            ("primary school students", ("elementary school students", "pupils")),
            ("student achievement", ("test scores",)),
        ),
    )
    dimensions = {d["label"]: d for d in decompose_question(question, plan)["dimensions"]}
    assert "elementary school students" in dimensions["primary school students"]["terms"]
    subject = next(d for d in dimensions.values() if d["kind"] == "subject")
    assert "test scores" in subject["term_groups"][0]


def test_placeholder_driver_is_checked_as_any_explicit_explanation():
    question = "What factors explain the gender wage gap in European labour markets?"
    plan = replace(
        plan_question(question),
        intent="relationship",
        subject_terms=("gender wage gap",),
        driver_terms=("factors explaining the gender wage gap",),
    )
    topic = next(
        d for d in decompose_question(question, plan)["dimensions"] if d["kind"] == "topic"
    )
    assert "explained by" in topic["terms"]
    assert "factors explaining the gender wage gap" not in topic["terms"]


def test_setting_populations_and_exposure_drivers_accept_common_wording():
    from sci_search.coverage import _exposure_aliases, _population_aliases

    assert "primary school" in _population_aliases("primary school students")
    assert _population_aliases("older adults") == ("older adults",)
    assert {"exposure to microplastic", "microplastic"} <= set(
        _exposure_aliases("microplastic exposure")
    )
    assert _exposure_aliases("class size") == ()


def test_outcome_only_abstract_is_reviewed_not_auto_selected_for_a_relationship():
    from sci_search.discovery import PublicationCandidate, screen_candidates

    question = "How effective are carbon taxes at reducing greenhouse gas emissions?"
    plan = replace(
        plan_question(question),
        intent="relationship",
        concepts=("greenhouse gas emissions", "carbon taxes"),
        subject_terms=("greenhouse gas emissions",),
        driver_terms=("carbon taxes",),
        term_synonyms=(("carbon taxes", ("carbon taxation",)),),
    )

    def paper(identifier, abstract):
        return PublicationCandidate(
            id=identifier,
            title="Greenhouse gas emissions study",
            abstract=abstract,
            year=2024,
            doi=None,
            authors=(),
            publication_type="article",
            source_url=None,
            is_open_access=True,
            full_text_url="https://example.org/a.pdf",
            has_pdf=True,
        )

    screened = {
        c.id: c.screening_status
        for c in screen_candidates(
            [
                paper("meat", "Greenhouse gas emissions of beef production systems were modelled."),
                paper("tax", "Carbon taxation lowered greenhouse gas emissions in Norway."),
            ],
            plan,
        )
    }
    assert screened == {"meat": "uncertain", "tax": "selected"}


def test_metadata_gate_accepts_reordered_and_process_noun_concepts():
    from sci_search.discovery import _concept_present, _tokens

    question = "What role did the printing press play in the spread of the Protestant Reformation?"
    plan = replace(
        plan_question(question),
        intent="relationship",
        concepts=("protestant reformation spread", "printing press"),
        subject_terms=("protestant reformation spread",),
        driver_terms=("printing press",),
    )
    for title in (
        "The Spread of the Protestant Reformation of the Sixteenth Century",
        "Printing and the Protestant Reformation",
    ):
        text = title.lower()
        assert _concept_present("protestant reformation spread", plan, text, set(_tokens(text)))
    text = "reformed spreadsheets for protestant schools"
    assert not _concept_present("protestant reformation spread", plan, text, set(_tokens(text)))


def test_class_geography_uses_equivalent_names_and_is_not_statement_bound():
    question = "Does microfinance reduce household poverty in developing countries?"
    plan = replace(
        plan_question(question),
        intent="relationship",
        subject_terms=("household poverty",),
        driver_terms=("microfinance",),
        geography_terms=("developing countries",),
    )
    geography = next(
        d for d in decompose_question(question, plan)["dimensions"] if d["kind"] == "geography"
    )
    assert {"lmics", "low-income countries"} <= set(geography["terms"])
    assert geography["place_class"] and not geography["statement_required"]
