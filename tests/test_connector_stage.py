# tests/test_connector_stage.py
from sci_search.data_research.connectors import base, stage
from tests.data_meaning_fixtures import with_positive_meaning_review


def offline(url):
    from tests.test_connector_eurostat import offline as eurostat_offline

    return eurostat_offline(url)


STRATEGY = {
    "adapter": "discovered_data_v1",
    "route": "data",
    "rationale": "Annual statistics",
    "measurements": ["life expectancy at birth"],
    "geography": "Netherlands, Germany and Greece",
    "country_scope": "other",
    "countries": ["NLD", "DEU", "GRC"],
    "start_year": 2000,
    "end_year": 2024,
}


def scripted(prompt, schema):
    title = schema.get("title", "")
    if title == "connector_terms":
        return {
            "terms": [
                {"measurement": "life expectancy at birth", "terms": ["life expectancy", "sex"]}
            ]
        }
    if title == "connector_choice":
        return {
            "choices": [
                {
                    "candidate": "eurostat:demo_mlexpec",
                    "measurement": "life expectancy at birth",
                    "reason": "Annual by sex and country",
                }
            ]
        }
    if title == "connector_selection":
        return {
            "filters": {
                "freq": ["A"],
                "unit": ["YR"],
                "sex": ["F", "M"],
                "age": ["Y_LT1"],
                "geo": ["NL", "DE", "EL"],
            },
            "series_dimensions": ["sex", "geo"],
            "reason": "Birth, both sexes, requested countries",
        }
    raise AssertionError("unexpected model call " + title)


def test_stage_produces_an_executed_analysis(tmp_path):
    from sci_search.data_research.connectors import eurostat

    result = stage.run(
        "How has life expectancy changed for men and women in NL, DE and GR?",
        STRATEGY,
        tmp_path,
        complete=with_positive_meaning_review(scripted),
        fetch=offline,
        post=None,
        check_cancelled=lambda: None,
        progress=lambda m: None,
        connectors={"eurostat": eurostat},
        cache_dir=tmp_path / "cache",
    )
    assert result["covered"] == ["life expectancy at birth"]
    analysis = result["analyses"][0]
    assert analysis["execution"]["status"] == "verified"
    assert analysis["source"]["connector"]["dataset"] == "demo_mlexpec"
    assert (
        "/data/demo_mlexpec/A.YR.F+M.Y_LT1.NL+DE+EL/"
        in analysis["source"]["connector"]["request"]["url"]
    )
    assert len(analysis["series"]) == 6
    assert result["assessments"][0]["decision"] == "analysed"


def test_selection_schema_enumerates_observed_codes():
    description = base.DatasetDescription(
        candidate=base.DatasetCandidate("x", "d", "t", "annual"),
        dimensions=(base.Dimension("geo", "Country", {"NL": "Netherlands"}),),
        years=(),
        licence_url="",
        definitions="",
        publisher="",
    )
    schema = stage.selection_schema(description)
    assert schema["properties"]["filters"]["properties"]["geo"]["items"]["enum"] == ["NL"]
    assert schema["properties"]["series_dimensions"]["items"]["enum"] == ["geo"]
