"""A data-only answer is labelled from its verified numerical completeness."""

from sci_search.data_research.workflow import investigation
from sci_search.result_quality import result_quality


def data_result(*, answer_status="complete", conflicts=()):
    return {
        "kind": "discovered",
        "strategy": {
            "route": "data",
            "measurements": ["renewable share of electricity (%)"],
            "start_year": 2010,
            "end_year": 2022,
        },
        "analyses": [{"series": []}],
        "coverage": {
            "cells": [
                {"entity": "DEU", "status": "complete", "conflicts": list(conflicts)},
                {"entity": "FRA", "status": "complete", "conflicts": []},
            ]
        },
        "output_completion": {
            "numerical_answer_status": answer_status,
            "calculation_status": "complete",
        },
        "limitations": [],
    }


def test_complete_numbers_are_an_adequate_answer():
    payload = investigation("Renewable share", {}, data_result())
    assert payload["answer_adequacy"] == {"status": "adequate", "can_answer_overall_question": True}
    assert "DEU, FRA" in payload["answer_summary"]
    assert "2010–2022" in payload["answer_summary"]
    assert result_quality(payload)["status"] == "adequate"


def test_partial_numbers_stay_partial():
    payload = investigation("Renewable share", {}, data_result(answer_status="partial"))
    assert payload["answer_adequacy"]["status"] == "partial"
    assert payload["answer_adequacy"]["can_answer_overall_question"] is False
    assert result_quality(payload)["status"] == "partial"


def test_conflicting_sources_are_never_adequate_and_are_named():
    conflict = {"sources": [0, 1], "years": [2015], "units": ["deaths", "NR"]}
    payload = investigation("Renewable share", {}, data_result(conflicts=[conflict]))
    assert payload["answer_adequacy"]["status"] == "partial"
    assert "Sources report different values for DEU" in payload["answer_summary"]
    assert result_quality(payload)["status"] == "partial"


def test_summary_names_measurement_when_question_has_no_geography():
    from sci_search.data_research.workflow import _data_answer_summary

    result = {
        "strategy": {"measurements": ["student achievement"]},
        "coverage": {
            "cells": [
                {
                    "measurement": "student achievement",
                    "entity": "",
                    "status": "partial",
                    "conflicts": [{"sources": [0, 1]}],
                }
            ]
        },
        "analyses": [{}],
    }
    summary = _data_answer_summary(result, 1)
    assert "different values for student achievement;" in summary
