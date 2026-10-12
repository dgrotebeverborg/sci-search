from sci_search.data_research.adaptive import research_candidates
from tests.data_meaning_fixtures import with_positive_meaning_review


def test_recovery_uses_observed_link_and_keeps_existing_result():
    source = {"url": "https://example.org/page", "title": "Data", "publisher": "Agency"}
    result = {
        "analyses": [{"source": {"title": "Kept"}, "series": []}],
        "assessments": [],
        "limitations": [],
    }
    plans = iter(
        [
            dict(
                action="retry_link",
                source_index=0,
                link_index=0,
                query="",
                reason="Viewer linked CSV",
            ),
            dict(
                action="stop",
                source_index=-1,
                link_index=-1,
                query="",
                reason="No further useful route",
            ),
        ]
    )
    stream = research_candidates(
        "trend",
        {},
        {"candidates": [source]},
        result,
        lambda *a, **k: {"candidates": []},
        None,
        lambda *a: next(plans),
        lambda *a: None,
        lambda *a: None,
        lambda: None,
    )
    assert next(stream) == source
    result["assessments"].append(
        {
            **source,
            "decision": "blocked",
            "reason": "HTML viewer",
            "failure_stage": "parse",
            "recovery_links": ["https://example.org/data.csv"],
        }
    )
    recovered = next(stream)
    assert recovered["url"] == "https://example.org/data.csv"
    assert list(stream) == []
    assert result["analyses"][0]["source"]["title"] == "Kept"
    assert result["research_process"]["stop_reason"] == "No further useful route"


def test_invalid_link_never_fetched_and_budget_is_bounded():
    result = {"analyses": [], "assessments": [], "limitations": []}

    def plan(*a):
        return dict(action="retry_link", source_index=99, link_index=0, query="", reason="Guess")

    assert (
        list(
            research_candidates(
                "trend",
                {},
                {"candidates": []},
                result,
                lambda *a, **k: {"candidates": []},
                None,
                plan,
                lambda *a: None,
                lambda *a: None,
                lambda: None,
            )
        )
        == []
    )
    assert result["research_process"]["stop_reason"]


def test_targeted_search_replans_after_failure_and_respects_bounds():
    result = {"analyses": [], "assessments": [], "limitations": []}
    plans = iter(
        [
            dict(
                action="search",
                source_index=-1,
                link_index=-1,
                query="archive",
                reason="Older data",
            ),
            dict(
                action="search",
                source_index=-1,
                link_index=-1,
                query="download",
                reason="Different access",
            ),
            dict(
                action="stop", source_index=-1, link_index=-1, query="", reason="No further route"
            ),
        ]
    )
    calls = []

    def search(question, scope, **kwargs):
        calls.append(question)
        assert scope == {"start_year": 2000, "end_year": 2024}
        if len(calls) == 1:
            raise ValueError("Source search unavailable")
        return {"candidates": [dict(url="https://example.org/data", title="Data")]}

    saved = []
    items = list(
        research_candidates(
            "trend",
            {"start_year": 2000, "end_year": 2024},
            {"candidates": []},
            result,
            search,
            None,
            lambda *a: next(plans),
            lambda *a: saved.append(a),
            lambda *a: None,
            lambda: None,
        )
    )
    assert len(items) == 1
    assert len(saved) == 1
    assert result["research_process"]["steps"][0]["status"] == "failed"
    assert result["research_process"]["steps"][1]["status"] == "checked"


def test_repeated_query_does_not_spend_another_search_call():
    result = {"analyses": [], "assessments": [], "limitations": []}
    calls = []

    def search(*a, **k):
        calls.append(a)
        return {"candidates": []}

    list(
        research_candidates(
            "trend",
            {},
            {"candidates": []},
            result,
            search,
            None,
            lambda *a: dict(
                action="search", query="same query", source_index=-1, link_index=-1, reason="Check"
            ),
            lambda *a: None,
            lambda *a: None,
            lambda: None,
        )
    )
    assert len(calls) == 1
    assert len(result["research_process"]["steps"]) == 3


def test_cancelled_research_does_not_become_a_source_failure():
    import pytest

    class Cancelled(RuntimeError):
        pass

    def cancel():
        raise Cancelled()

    with pytest.raises(Cancelled):
        list(
            research_candidates(
                "trend",
                {},
                {"candidates": []},
                {"analyses": [], "assessments": [], "limitations": []},
                None,
                None,
                None,
                None,
                None,
                cancel,
            )
        )


def test_workflow_recovers_from_html_download_to_observed_csv(tmp_path):
    from sci_search.data_research.workflow import execute

    scope = dict(
        route="data",
        rationale="Trend",
        geography="A",
        measurements=["use"],
        start_year=2020,
        end_year=2021,
    )
    first = dict(
        adapter="csv",
        download_link_index=0,
        reason="Annual use",
        definition_quote="Annual use",
        license_note="Unknown",
        covered_measurements=["use"],
    )
    mapping = dict(
        suitable=True,
        reason="Direct measured use",
        unit_evidence="kWh",
        measurement="use",
        mapping=dict(
            year_column="Year",
            entity_column="Entity",
            entities=["A"],
            value_column="Use kWh",
            unit="kWh",
            output_unit="kWh",
            label="Use",
            filters=[],
            missing_values=[""],
            decimal_separator=".",
        ),
    )
    replies = iter(
        [
            first,
            dict(link_index=0, reason="Viewer exposes CSV"),
            mapping,
            dict(
                action="stop",
                source_index=-1,
                link_index=-1,
                query="",
                reason="Requested years covered",
            ),
        ]
    )
    pages = {
        "https://example.org/page": (
            b'<html>Annual use<a href="/viewer">Open table</a></html>',
            "text/html",
        ),
        "https://example.org/viewer": (
            b'<html>Interactive view<a href="/data.csv">CSV</a></html>',
            "text/html",
        ),
        "https://example.org/data.csv": (
            b"Year,Entity,Use kWh\n2020,A,10\n2021,A,20\n",
            "text/csv",
        ),
    }
    result = execute(
        "use trend",
        scope,
        tmp_path,
        search=lambda *a, **k: {
            "candidates": [
                dict(url="https://example.org/page", title="Annual data", publisher="Office")
            ]
        },
        fetch=lambda url: (*pages[url], url),
        complete=with_positive_meaning_review(lambda *a: next(replies)),
    )
    assert len(result["analyses"]) == 1
    assert result["assessments"][0]["decision"] == "analysed"
    assert (
        result["assessments"][0]["download_navigation"][0]["target"]
        == "https://example.org/data.csv"
    )
    assert result["analyses"][0]["series"][0]["annual"][-1]["value"] == 20
    assert result["research_process"]["steps"][0]["status"] == "stopped"


def test_reviewer_can_reprocess_download_with_documentation_and_see_outcome():
    calls=[]
    result={'analyses':[], 'assessments':[dict(url='https://example.org/data',title='Data',decision='blocked',reason='No units',python_error='missing units',recovery_links=['https://example.org/methods'])], 'limitations':[]}
    def model(prompt,schema):
        calls.append(prompt)
        if len(calls)==1:
            assert 'missing units' in prompt
            return dict(action='reassess',source_index=0,link_index=0,query='',measurements=['cover'],reason='Read units then extract the available cover subset')
        assert 'validated cover' in prompt
        return dict(action='stop',source_index=-1,link_index=-1,query='',reason='Cover retained; no bleaching source remains')
    def reassess(index,measurements,link,round_number):
        assert (index,measurements,link)==(0,['cover'],0)
        result['analyses'].append({'source':{'title':'Data'},'series':[]})
        return {'status':'retained','reason':'validated cover'}
    assert list(research_candidates('cover and bleaching',{'measurements':['cover','bleaching']},{'candidates':[]},result,None,None,model,lambda *a:None,lambda *a:None,lambda:None,review_source=reassess))==[]
    assert result['research_process']['steps'][0]['outcome']['status']=='retained'
