"""Questions about the future may use projected data up to 2100."""

import pytest

from sci_search.data_research import semantics
from sci_search.data_research.strategy import PROMPT, validate_strategy

BASE = {
    "route": "both",
    "rationale": "Projected glacier runoff per basin.",
    "measurements": ["projected glacier runoff (SSP scenarios)"],
    "geography": "Indus, Ganges and Brahmaputra basins",
}


def strategy(start, end):
    return validate_strategy({**BASE, "start_year": start, "end_year": end})


def test_projections_may_end_in_2100():
    assert strategy(2000, 2100)["end_year"] == 2100


def test_years_after_2100_are_rejected():
    with pytest.raises(ValueError, match="years"):
        strategy(2000, 2101)


def test_a_future_only_interval_is_preserved():
    result = strategy(2027, 2030)
    assert (result["start_year"], result["end_year"]) == (2027, 2030)


def test_start_years_after_2100_are_rejected():
    with pytest.raises(ValueError, match="years"):
        strategy(2101, None)


def test_a_reversed_interval_is_rejected():
    with pytest.raises(ValueError, match="interval"):
        strategy(2020, 2010)


def test_the_prompts_allow_projections_and_require_their_scenario():
    assert "projected" in PROMPT
    assert "scenario" in semantics.INSTRUCTIONS


def test_literature_strategy_accepts_null_optional_data_lists():
    """The Codex provider returns null for data-only lists on literature questions."""
    result = validate_strategy(
        {
            "route": "literature",
            "rationale": "Diagnostic accuracy studies.",
            "geography": "",
            "measurements": [],
            "requirements": None,
            "calculations": None,
            "unresolved_calculations": None,
            "calculation_requests": None,
            "start_year": None,
            "end_year": None,
        }
    )
    assert result["route"] == "literature"
    assert "requirements" not in result


@pytest.mark.parametrize(
    "placeholder", ["Unspecified", "unspecified", "Cities", "Various countries"]
)
def test_placeholder_geography_means_no_geography(placeholder):
    from sci_search.data_research.strategy import validate_strategy

    strategy = validate_strategy(
        {"route": "data", "rationale": "x", "geography": placeholder, "measurements": ["m"]}
    )
    assert strategy["geography"] == ""


def test_real_geography_is_kept():
    from sci_search.data_research.strategy import validate_strategy

    for place in ("Europe", "Netherlands", "Global"):
        strategy = validate_strategy(
            {"route": "data", "rationale": "x", "geography": place, "measurements": ["m"]}
        )
        assert strategy["geography"] == place
