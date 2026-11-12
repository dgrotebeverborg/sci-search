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
