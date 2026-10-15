import json

import pytest


def verify(body, row):
    from sci_search.data_research.verification import verify_observations

    return verify_observations(body, {"observations": [row]})


def test_exact_json_reference_is_checked_against_original_bytes():
    row = {"value": 12, "source_locator": {"format": "json", "path": ["data", 0, "value"]}}
    result = verify(b'{"data":[{"value":12}]}', row)
    assert result["value_verified"] == 1
    assert result["unverified"] == 0


def test_wrong_value_cannot_pass_with_a_plausible_reference():
    row = {"value": 13, "source_locator": {"format": "json", "path": ["data", "value"]}}
    with pytest.raises(ValueError, match="differs"):
        verify(b'{"data":{"value":12}}', row)


def test_csv_reference_reads_the_original_line_and_column():
    row = {
        "value": 12.5,
        "source_locator": {"format": "csv", "line": 3, "column": "Value", "decimal_separator": ","},
    }
    assert verify(b"Year;Value\n2020;9\n2021;12,5\n", row)["value_verified"] == 1


def test_free_text_reference_is_explicitly_unverified():
    assert verify(b"anything", {"value": 12, "source_reference": "page 4"})["unverified"] == 1


def test_missing_reference_path_is_not_treated_as_missing_data():
    with pytest.raises(ValueError, match="reference"):
        verify(
            b'{"data":12}',
            {"value": None, "source_locator": {"format": "json", "path": ["absent"]}},
        )


def test_boolean_is_not_accepted_as_a_numeric_source():
    with pytest.raises(ValueError):
        verify(
            json.dumps({"value": True}).encode(),
            {"value": 1, "source_locator": {"format": "json", "path": ["value"]}},
        )
