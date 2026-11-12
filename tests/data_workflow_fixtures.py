"""Shared declarative inputs for data workflow tests; no test-module imports."""

from sci_search.data_research.strategy import validate_strategy


def strategy(**updates):
    return validate_strategy(
        dict(
            route="data",
            rationale="Annual observations answer the question.",
            measurements=["population"],
            geography="Netherlands",
            start_year=2001,
            end_year=2003,
        )
        | updates
    )


def mapping():
    return {
        "year_column": "Year",
        "entity_column": "Country",
        "entities": ["Netherlands"],
        "value_column": "Population",
        "unit": "people",
        "output_unit": "people",
        "filters": {},
        "label": "Population",
        "missing_values": ["", ":"],
        "decimal_separator": ".",
    }
