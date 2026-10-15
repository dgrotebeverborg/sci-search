"""Questions about the future may use projected data up to 2100."""

from datetime import UTC, datetime

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


def test_a_start_year_in_the_future_is_rejected():
    with pytest.raises(ValueError, match="years"):
        strategy(datetime.now(UTC).year + 1, 2100)


def test_a_reversed_interval_is_rejected():
    with pytest.raises(ValueError, match="interval"):
        strategy(2020, 2010)


def test_the_prompts_allow_projections_and_require_their_scenario():
    assert "projected" in PROMPT
    assert "scenario" in semantics.INSTRUCTIONS
