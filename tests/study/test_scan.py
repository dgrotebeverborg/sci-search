from sci_search.discovery import PublicationCandidate
from sci_search.study.scan import extend_scan, run_scan

BRIEF = {
    "interpreted_question": "How much energy storage does the Netherlands need?",
    "research_plan": None,
    "data_research": {"route": "both", "measurements": ["electricity demand"]},
}


def candidate(title, doi, cited=0):
    return PublicationCandidate(
        id=doi,
        title=title,
        abstract="A" * 900,
        year=2023,
        doi=doi,
        authors=(),
        publication_type="article",
        source_url=f"https://doi.org/{doi}",
        cited_by_count=cited,
    )


class FakeProvider:
    name = "fake"

    def __init__(self, results=None):
        self.queries = []
        self.results = results

    def search(self, query, *, limit):
        self.queries.append(query)
        if self.results is not None:
            return self.results
        if query.purpose == "existing models":
            return (candidate("Storage model study", "10.1/model", 5),)
        return (candidate("Storage needs review", "10.1/review", 50),)


def interpret(question):
    return {**BRIEF, "options": [{"closest": True, "brief": BRIEF}]}


def datasets(question, strategy):
    return {
        "candidates": [
            {
                "title": "Hourly load",
                "url": "https://x/load",
                "landing_url": "https://x",
                "publisher": "ENTSO-E",
                "rationale": "demand",
            }
        ]
    }


def test_scan_collects_studies_models_and_datasets():
    messages = []
    scan = run_scan(
        "Q?",
        interpret=interpret,
        providers=(FakeProvider(),),
        find_datasets=datasets,
        progress=messages.append,
    )
    assert scan["interpretation"]["question"] == BRIEF["interpreted_question"]
    kinds = {p["kind"] for p in scan["publications"]}
    assert kinds == {"study", "model"}
    assert [p["id"] for p in scan["publications"]] == ["P1", "P2"]
    assert all(len(p["abstract"]) <= 600 for p in scan["publications"])
    assert scan["datasets"] == [
        {
            "id": "D1",
            "title": "Hourly load",
            "url": "https://x/load",
            "publisher": "ENTSO-E",
            "rationale": "demand",
        }
    ]
    assert {s["name"]: s["status"] for s in scan["steps"]} == {
        "interpretation": "ok",
        "publications": "ok",
        "models": "ok",
        "datasets": "ok",
    }
    assert len(messages) >= 4


def test_failed_step_does_not_stop_the_scan():
    def broken(question, strategy):
        raise ValueError("no web search")

    scan = run_scan("Q?", interpret=interpret, providers=(FakeProvider(),), find_datasets=broken)
    steps = {s["name"]: s for s in scan["steps"]}
    assert (
        steps["datasets"]["status"] == "failed" and "no web search" in steps["datasets"]["detail"]
    )
    assert scan["publications"]


def test_interpretation_failure_falls_back_to_the_question():
    def broken(question):
        raise ValueError("model down")

    scan = run_scan(
        "Raw question?", interpret=broken, providers=(FakeProvider(),), find_datasets=datasets
    )
    assert scan["interpretation"]["question"] == "Raw question?"
    assert {s["name"]: s["status"] for s in scan["steps"]}["interpretation"] == "failed"


def test_literature_route_skips_datasets():
    literature = {**BRIEF, "data_research": {"route": "literature"}}

    def only_literature(question):
        return {**literature, "options": [{"closest": True, "brief": literature}]}

    called = []
    scan = run_scan(
        "Q?",
        interpret=only_literature,
        providers=(FakeProvider(),),
        find_datasets=lambda *a: called.append(a),
    )
    assert {s["name"]: s["status"] for s in scan["steps"]}["datasets"] == "skipped"
    assert not called and scan["datasets"] == []


def test_extend_scan_continues_ids_and_skips_duplicates():
    scan = run_scan("Q?", interpret=interpret, providers=(FakeProvider(),), find_datasets=datasets)
    provider = FakeProvider(
        results=(
            candidate("Storage needs review", "10.1/review"),
            candidate("Hydrogen storage", "10.1/h2"),
        )
    )
    extended = extend_scan(
        scan,
        ["hydrogen storage"],
        providers=(provider,),
        find_datasets=lambda q, s: {"candidates": []},
    )
    new = extended["publications"][len(scan["publications"]) :]
    assert [(p["id"], p["title"]) for p in new] == [("P3", "Hydrogen storage")]
    assert "hydrogen storage" in provider.queries[0].text


def test_extra_search_terms_keep_the_study_subject():
    scan = run_scan("Q?", interpret=interpret, providers=(FakeProvider(),), find_datasets=datasets)
    scan["interpretation"]["brief"]["research_plan"] = {
        "subject_terms": ["electricity storage", "Netherlands"]
    }
    provider = FakeProvider(results=())
    extend_scan(
        scan,
        ["hydrogen storage"],
        providers=(provider,),
        find_datasets=lambda q, s: {"candidates": []},
    )
    assert provider.queries[0].text == "hydrogen storage electricity storage Netherlands"
