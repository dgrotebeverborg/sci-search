"""The same publisher indicator in two charts is not independent evidence."""

import json

import pytest

from sci_search.data_research.connectors import base, owid, stage
from tests.data_meaning_fixtures import positive_review
from tests.test_connector_owid import CANDIDATE, SCOPE, offline


@pytest.mark.parametrize(
    "change,duplicate", [(None, True), ("definition", False), ("value", False)]
)
def test_repeated_indicator_is_skipped_only_with_identical_definition_and_values(
    tmp_path, change, duplicate
):
    reviews = []

    def complete(prompt, schema):
        if schema.get("title") == "connector_selection":
            return {
                "filters": {"indicator": ["life_expectancy_0"], "entity": ["Germany"]},
                "series_dimensions": ["entity"],
                "reason": "Requested",
            }
        reviews.append(prompt)
        return positive_review(prompt)

    def run(candidate, fetch, **kwargs):
        return stage.analyse_dataset(
            "Life expectancy",
            {**SCOPE, "measurements": ["life expectancy"]},
            tmp_path,
            owid,
            candidate,
            "life expectancy",
            complete=complete,
            fetch=fetch,
            post=None,
            check_cancelled=lambda: None,
            progress=lambda _: None,
            **kwargs,
        )

    first, _ = run(CANDIDATE, offline)
    assert first

    def second_fetch(url):
        body, kind, _ = offline(url.replace("another-chart", "life-expectancy"))
        if ".metadata.json" in url:
            meta = json.loads(body)
            meta["chart"]["title"] = "Another chart"
            if change == "definition":
                next(iter(meta["columns"].values()))["descriptionShort"] = "A different definition."
            body = json.dumps(meta).encode()
        if change == "value" and ".csv" in url:
            # Every Germany observation changes; other entities remain intact.
            lines = body.decode().splitlines()
            for i, line in enumerate(lines):
                if line.startswith("Germany,"):
                    cells = line.split(",")
                    cells[-1] = str(float(cells[-1]) + 1)
                    lines[i] = ",".join(cells)
            body = "\n".join(lines).encode()
        return body, kind, url

    second, assessment = run(
        base.DatasetCandidate("owid", "another-chart", "Another chart", "annual"),
        second_fetch,
        existing_analyses=[first],
    )
    if duplicate:
        assert second is None
        assert assessment["decision"] == "duplicate"
        assert assessment["duplicate_of"] == first["source"]["url"]
        assert len(reviews) == 1
    else:
        assert second
        assert len(reviews) == 2
