import json

import pytest


def test_inspection_can_read_lines_outside_the_initial_preview(tmp_path):
    from sci_search.data_research.inspection import inspect_source

    body = ("metadata\n" * 2000 + "Year,Value\n2020,12\n").encode()
    result = inspect_source(
        body, {"kind": "text", "offset": 2000, "limit": 2, "name": ""}, tmp_path / "inspect"
    )
    assert result["text"] == "Year,Value\n2020,12"
    assert result["offset"] == 2000
    assert (tmp_path / "inspect/execution.json").exists()


def test_targeted_inspection_rejects_unbounded_or_unknown_requests(tmp_path):
    from sci_search.data_research.inspection import inspect_source

    with pytest.raises(ValueError, match="inspection"):
        inspect_source(b"data", {"kind": "shell", "offset": 0, "limit": 1, "name": ""}, tmp_path)
    with pytest.raises(ValueError, match="inspection"):
        inspect_source(
            b"data", {"kind": "text", "offset": 0, "limit": 1000000, "name": ""}, tmp_path
        )


def test_model_can_inspect_then_extract_within_bounded_attempts(tmp_path):
    from sci_search.data_research.python_recovery import recover
    from tests.data_meaning_fixtures import with_positive_meaning_review
    from tests.test_python_data_recovery import CODE, SCOPE, SOURCE

    calls = []

    def model(prompt, schema):
        if "code" in schema["properties"]:
            calls.append(prompt)
            if len(calls) == 1:
                return {
                    "code": "",
                    "explanation": "Inspect structure",
                    "inspection": {"kind": "text", "offset": 0, "limit": 2, "name": ""},
                }
            assert "additional_inspections" in prompt
            return {"code": CODE, "explanation": "Read", "inspection": None}
        return {"accepted": True, "reason": "Read the source", "limitations": []}

    result = recover(
        "Population",
        SCOPE,
        b'{"values":{"2001":9}}',
        SOURCE,
        tmp_path,
        complete=with_positive_meaning_review(model),
        reason="Unknown JSON",
    )
    assert result["series"][0]["annual"][0]["value"] == 9
    assert len(calls) == 2
    assert json.loads((tmp_path / "python/targeted-1/output/inspection.json").read_text())["text"]
