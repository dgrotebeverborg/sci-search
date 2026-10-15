"""Synthetic OData pages derived from the retained, redistributable CBS fixture."""

import json
from urllib.parse import unquote_plus, urlsplit

import pytest

from sci_search.data_research.connectors import cbs
from sci_search.data_research.packages import prepare_table
from sci_search.data_research.tabular import analyse_csv
from tests.test_connector_cbs import CANDIDATE, SCOPE, offline, selection_for


def api(next_link=None):
    raw = offline(cbs.package_url(CANDIDATE.dataset))[0]
    _, prep = prepare_table(raw)
    metadata = json.loads(prep["metadata"])
    documents = {
        "Properties": metadata["dataset"][0],
        "Dimensions": metadata["dimensions"],
        "MeasureCodes": metadata["measures"],
    }
    documents.update({d + "Codes": list(codes.values()) for d, codes in metadata["codes"].items()})
    seen = []

    def fetch(url):
        seen.append(url)
        if "/CSV/" in url:
            raise ValueError("Dataset exceeds the 5 MB acquisition limit")
        endpoint = urlsplit(url).path.rsplit("/", 1)[-1]
        if endpoint == "Observations":
            query = unquote_plus(urlsplit(url).query)
            assert "$filter=" in query and "Measure eq 'M002416_2'" in query
            assert "Perioden eq '2000JJ00'" in query
            response = {
                "value": [
                    dict(
                        Measure="M002416_2",
                        BronTechniek="T001100",
                        Perioden="2000JJ00",
                        Value=2.64,
                        StringValue=None,
                        ValueAttribute="None",
                    )
                ]
            }
            # Use the actual total's code from the fixture.
            response["value"][0]["BronTechniek"] = next(
                c["Identifier"]
                for c in documents["BronTechniekCodes"]
                if c["Title"].strip() == "Totaal hernieuwbare energiebronnen"
            )
            if next_link:
                response["@odata.nextLink"] = next_link
        else:
            value = documents[endpoint]
            response = {"value": value} if isinstance(value, list) else value
        return json.dumps(response).encode(), "application/json", url

    return fetch, seen


def test_large_package_falls_back_to_a_filtered_api_slice():
    fetch, seen = api()
    description = cbs.describe(CANDIDATE, SCOPE, fetch=fetch)
    selection = selection_for(description)
    acquired = cbs.fetch(description, selection, SCOPE, fetch=fetch, post=None)
    assert any("Observations?" in url for url in seen)
    table, preparation = prepare_table(acquired.raw, acquired.selection)
    result = analyse_csv(table, cbs.mapping(table, preparation, selection, "share"), SCOPE)
    assert result["series"][0]["annual"][0]["value"] == 2.64
    assert acquired.request["pages"]
    assert acquired.artifact == "source.json"


def test_api_pagination_cannot_leave_the_exact_dataset_endpoint():
    fetch, seen = api("https://evil.example/Observations")
    description = cbs.describe(CANDIDATE, SCOPE, fetch=fetch)
    with pytest.raises(ValueError, match="pagination"):
        cbs.fetch(description, selection_for(description), SCOPE, fetch=fetch, post=None)
    assert not any("evil.example" in url for url in seen)


def test_api_snapshot_is_calculated_and_replayed_offline(tmp_path):
    import subprocess
    import sys

    from sci_search.data_research.artifacts import write_replay
    from sci_search.data_research.connectors import stage
    from tests.data_meaning_fixtures import with_positive_meaning_review

    fetch, _ = api()
    description = cbs.describe(CANDIDATE, SCOPE, fetch=fetch)
    result, decision = stage.analyse_dataset(
        "Share",
        {**SCOPE, "measurements": ["share"]},
        tmp_path,
        cbs,
        CANDIDATE,
        "share",
        complete=with_positive_meaning_review(lambda *a: selection_for(description)),
        fetch=fetch,
        post=None,
        check_cancelled=lambda: None,
        progress=lambda _: None,
    )
    assert result is not None, decision
    folder = next(tmp_path.glob("connector-*"))
    write_replay(folder)
    assert result["execution"]["status"] == "verified"
    subprocess.run([sys.executable, str(folder / "reproduce.py")], check=True, capture_output=True)
