"""Conservative phrase matching for literal and locally restated concepts."""

import pytest

from sci_search.concept_matching import concept_present, concept_spans

SUBJECT = (
    "off-grid solar- and/or wind-based hydrogen supply chain configurations "
    "for hydrogen-based steelmaking"
)
# Opening passage of the exact source rejected in job429pubs.
SOURCE_ABSTRACT = (
    "Off-grid hydrogen supply from solar or wind sources to hydrogen-based steelmaking "
    "can reduce CO₂ emissions. However, the techno-economic feasibility of different "
    "supply chain configurations remains uncertain. This study evaluates 61 off-grid "
    "hydrogen supply chains for a 15 Mt. steel/year plant in 2030."
)


def test_source_abstract_supports_long_restated_subject():
    assert concept_present(SOURCE_ABSTRACT, SUBJECT)
    spans = concept_spans(SOURCE_ABSTRACT, SUBJECT)
    assert spans
    assert any("configurations" in SOURCE_ABSTRACT[start:end] for start, end in spans)


@pytest.mark.parametrize("source", ["solar", "wind"])
def test_explicit_alternatives_need_only_one_source(source):
    text = f"Off-grid hydrogen supply for steelmaking uses {source}. Chain configurations vary."
    assert concept_present(text, SUBJECT)


@pytest.mark.parametrize(
    "missing", ["off", "grid", "hydrogen", "supply", "chain", "configurations", "steelmaking"]
)
def test_no_required_content_anchor_can_be_dropped(missing):
    text = "off grid solar hydrogen supply chain configurations steelmaking"
    assert not concept_present(" ".join(word for word in text.split() if word != missing), SUBJECT)


@pytest.mark.parametrize(
    "text",
    [
        "Hydrogen transport supply chain configurations use solar and wind energy.",
        "Off-grid solar and wind community energy configurations power local supply chains.",
        "Off-grid hydrogen supply chain configurations for steelmaking use biomass.",
    ],
)
def test_related_but_different_subjects_do_not_match(text):
    assert not concept_present(text, SUBJECT)


def test_dispersed_anchors_are_not_document_wide_matches():
    text = (
        "off grid solar hydrogen supply chain " + "unrelated " * 90 + "configurations steelmaking"
    )
    assert not concept_present(text, SUBJECT)


@pytest.mark.parametrize(
    ("term", "text"),
    [
        (
            "urban flood risk assessment using satellite rainfall observations",
            "Satellite observations of rainfall support assessment of flood risk in urban areas.",
        ),
        (
            "portable optical or magnetic sensor networks for remote wildlife monitoring",
            "Remote wildlife monitoring uses a network of portable optical sensors.",
        ),
        (
            "CO2 capture membrane performance under variable temperature conditions",
            "Under variable temperature conditions, CO₂ capture shows improved membrane performance.",
        ),
    ],
)
def test_long_concepts_are_domain_independent(term, text):
    assert concept_present(text, term)


@pytest.mark.parametrize(
    ("text", "term", "expected"),
    [
        ("Green-hydrogen production", "green hydrogen", True),
        ("green sustainable hydrogen", "green hydrogen", False),
        ("hydrogenated steelmaking", "hydrogen", False),
        ("network sensor", "sensor network", False),
        ("sensor networks", "sensor network", False),
        ("CO₂ capture", "co2 capture", True),
        ("arbitrary text", "", False),
    ],
)
def test_short_phrases_remain_exact_normalized_boundary_matches(text, term, expected):
    assert concept_present(text, term) is expected


def test_spans_refer_to_original_text_even_after_unicode_normalization():
    text = "x CO₂—capture, then CO2 capture."
    assert concept_spans(text, "co2 capture") == [(2, 13), (20, 31)]


def test_and_requires_both_options_in_long_concept():
    term = "portable optical and magnetic sensor networks for remote wildlife monitoring"
    assert not concept_present(
        "Remote wildlife monitoring uses portable optical sensor networks.", term
    )


def test_multiword_alternatives_with_shared_noun_fail_closed():
    term = "lithium ion batteries or iron air batteries for remote renewable energy storage"
    # Combining only adjacent words around 'or' would incorrectly make 'iron'
    # optional here, allowing a text that describes neither complete option.
    text = "Remote renewable energy storage uses lithium ions and iron exposed to air."
    assert not concept_present(text, term)
    assert concept_present(term, term)


def test_hyphenated_constraint_must_remain_a_local_compound():
    text = (
        "Hydrogen supply chain configurations for solar steelmaking turn equipment off "
        "when demand on the electricity grid peaks."
    )
    assert not concept_present(text, SUBJECT)


def test_later_redundant_anchor_does_not_discard_required_compound():
    text = (
        "Off-grid equipment is switched off. Solar hydrogen supply chain "
        "configurations enable steelmaking."
    )
    assert concept_present(text, SUBJECT)


@pytest.mark.parametrize(("text", "term"), [
    ("C++ programming", "C"),
    ("CD4+ cells", "CD4−"),
    ("CD4− cells", "CD4+"),
    ("CD4− cells", "CD4"),
    ("HER2+ cancer", "HER2-negative"),
    ("input output", "input/output"),
    ("CD4+ cell population response following targeted immune therapy", 
     "CD4− cell population response following targeted immune therapy"),
])
def test_meaningful_symbols_are_not_erased(text, term):
    assert not concept_present(text, term)


@pytest.mark.parametrize(("text", "term"), [
    ("CD4− cells", "CD4−"),
    ("C++ programming", "C++"),
    ("input/output", "input/output"),
    ("green‐hydrogen production", "green hydrogen"),
])
def test_literal_symbols_and_hyphen_normalization_are_supported(text, term):
    assert concept_present(text, term)


def test_expanding_unicode_before_match_preserves_original_quote_offsets():
    assert concept_spans("Straße CO₂ capture", "co2 capture") == [(7, 18)]


def test_unicode_charge_sign_does_not_enable_relaxed_opposite_match():
    term = "CD4＋ cell population response following targeted immune therapy"
    text = "CD4− cell population response following targeted immune therapy"
    assert not concept_present(text, term)
