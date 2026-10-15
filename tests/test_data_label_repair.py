"""A documented entity qualifier can be repaired without altering numeric evidence."""

import json

import pytest

from sci_search.data_research.python_recovery import recover
from tests.data_meaning_fixtures import positive_review
from tests.test_python_data_recovery import CODE, SCOPE, SOURCE


@pytest.mark.parametrize(
    "aspect,status,quote",
    [
        ("definition", "unresolved", "Documented territory"),
        ("geography", "unresolved", "Documented territory"),
        ("geography", "conflicting", "Invented quote"),
    ],
)
def test_label_repair_cannot_bypass_missing_meaning_or_citations(aspect, status, quote):
    from sci_search.data_research.semantics import can_clarify_labels

    review = positive_review(
        "Review\n"
        + json.dumps(
            {
                "measurements": ["population"],
                "evidence_documents": {"metadata": "Documented territory"},
            }
        )
    )
    check = next(c for c in review["measurements"][0]["checks"] if c["aspect"] == aspect)
    check.update(status=status, evidence=[{"document": "metadata", "quote": quote}])
    assert not can_clarify_labels(review, ["population"], {"metadata": "Documented territory"})


@pytest.mark.parametrize("change_values", [False, True])
def test_label_repair_requires_unchanged_observations_and_fresh_review(tmp_path, change_values):
    attempts = []
    reviews = []

    def model(prompt, schema):
        if "action" in schema["properties"]:
            return dict(
                action="clarify_labels" if len(attempts) == 1 else "stop",
                measurements=["population"],
                years=[],
                entities=[],
                reason="Qualify the published entity",
            )
        if "code" in schema["properties"]:
            attempts.append(1)
            code = CODE
            if len(attempts) > 1:
                code = code.replace(
                    'entity="Netherlands"', 'entity="Netherlands (documented reporting territory)"'
                )
                if change_values:
                    code = code.replace("value=value", "value=value+1")
            return dict(code=code, explanation="Read source and label actual territory")
        ctx = json.loads(prompt.split("\n", 1)[1])
        reviews.append(ctx)
        review = positive_review(prompt)
        if len(attempts) == 1:
            check = next(
                c for c in review["measurements"][0]["checks"] if c["aspect"] == "geography"
            )
            check.update(
                status="conflicting",
                reason="The entity label omits the documented reporting territory qualifier.",
            )
        return {
            **review,
            "accepted": len(attempts) > 1,
            "reason": "Check territory label",
            "limitations": [],
        }

    def run():
        return recover(
            "Population",
            SCOPE,
            b'{"values":{"2001":9}}',
            SOURCE,
            tmp_path,
            complete=model,
            reason="Read",
            metadata="Population in the Netherlands (documented reporting territory), in people.",
        )

    if change_values:
        with pytest.raises(ValueError, match="Label repair changed"):
            run()
        assert not (tmp_path / "observations.json").exists()
    else:
        result = run()
        assert result["series"][0]["entity"] == "Netherlands (documented reporting territory)"
        assert result["series"][0]["annual"][0]["value"] == 9
        assert len(reviews) == 2
        assert result["semantic_review"]["accepted"]
