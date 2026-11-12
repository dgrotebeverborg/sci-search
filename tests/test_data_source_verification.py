import gzip
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


@pytest.mark.parametrize("kind", ["text", "csv", "json"])
def test_gzip_numeric_references_resolve_and_reject_changed_values(kind):
    sources = {
        "text": (b"Year\tValue\n2020\t12.5\n", {"line": 2, "column": 2, "delimiter": "\t"}),
        "csv": (b"Year,Value\n2020,12.5\n", {"line": 2, "column": "Value"}),
        "json": (b'{"value":12.5}', {"path": ["value"]}),
    }
    raw, locator = sources[kind]
    row = {"value": 12.5, "source_locator": {"format": kind, **locator}}
    body = gzip.compress(raw)
    assert verify(body, row)["value_verified"] == 1
    with pytest.raises(ValueError, match="differs"):
        verify(body, {**row, "value": 13})


def test_gzip_reference_expansion_is_bounded(monkeypatch):
    from sci_search.data_research import statistical_tables

    monkeypatch.setattr(statistical_tables, "MAX_EXPANDED", 10)
    with pytest.raises(ValueError, match="expanded-size limit"):
        verify(
            gzip.compress(b"1 " * 100),
            {"value": 1, "source_locator": {"format": "text", "line": 1, "column": 1}},
        )


def test_corrupt_gzip_reference_is_a_validation_error():
    body = bytes.fromhex("1f8b0800000000000003") + b"\xff" * 20
    with pytest.raises(ValueError, match="Invalid GZIP"):
        verify(body, {"value": 1, "source_locator": {"format": "text", "line": 1, "column": 1}})
