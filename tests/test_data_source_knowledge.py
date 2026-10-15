from tests.data_meaning_fixtures import with_positive_meaning_review
from tests.test_python_data_recovery import CODE, SCOPE, SOURCE


def test_reuse_executes_again_and_reviews_meaning_again(tmp_path):
    from sci_search.data_research.python_recovery import recover

    calls = []

    def model(prompt, schema):
        calls.append("extract" if "code" in schema["properties"] else "review")
        if "code" in schema["properties"]:
            return {"code": CODE, "explanation": "Read"}
        return {"accepted": True, "reason": "Grounded", "limitations": []}

    complete = with_positive_meaning_review(model)
    for run in ("first", "second"):
        result = recover(
            "Population",
            SCOPE,
            b'{"values":{"2001":9}}',
            SOURCE,
            tmp_path / run,
            complete=complete,
            reason="Read",
            knowledge_dir=tmp_path / "knowledge",
        )
        assert result["series"][0]["annual"][0]["value"] == 9
    assert calls == ["extract", "review", "review"]
    assert result["python_extraction"]["reused_recipe"] is True
    assert (tmp_path / "second/python/attempt-1/execution.json").exists()


def test_changed_source_cannot_reuse_an_old_extraction_recipe(tmp_path):
    from sci_search.data_research.python_recovery import recover

    calls = []

    def model(prompt, schema):
        if "code" in schema["properties"]:
            calls.append(prompt)
            return {"code": CODE, "explanation": "Read"}
        return {"accepted": True, "reason": "Grounded", "limitations": []}

    for index, body in enumerate((b'{"values":{"2001":9}}', b'{"values":{"2001":10}}')):
        recover(
            "Population",
            SCOPE,
            body,
            SOURCE,
            tmp_path / str(index),
            complete=with_positive_meaning_review(model),
            reason="Read",
            knowledge_dir=tmp_path / "knowledge",
        )
    assert len(calls) == 2
