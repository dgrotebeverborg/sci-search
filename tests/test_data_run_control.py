import json

from sci_search.data_research import workflow
from tests.test_autonomous_data import strategy


def test_exhausted_budget_blocks_external_calls_and_writes_a_readable_result(tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("No operation can start after the budget is exhausted")

    result = workflow.execute(
        "Population",
        strategy(),
        tmp_path,
        connectors={},
        search=forbidden,
        complete=forbidden,
        budget_limits={"model_calls": 0, "search_calls": 0},
    )
    assert result["status"] == "blocked"
    assert result["run_control"]["stop_reason"]
    saved = json.loads((tmp_path / "analysis.json").read_text())
    assert saved["run_control"]["counts"]["search_calls"] == 0
    assert saved["coverage"]["gaps"]


def test_all_model_calls_share_a_budget_including_connector_planning(tmp_path):
    from sci_search.data_research.connectors import eurostat
    from tests.test_connector_eurostat import offline
    from tests.test_connector_recovery import GOOD, model
    from tests.test_connector_stage import STRATEGY

    complete, seen = model([GOOD])
    result = workflow.execute(
        "Life expectancy",
        STRATEGY,
        tmp_path,
        connectors={"eurostat": eurostat},
        fetch=offline,
        complete=complete,
        budget_limits={"model_calls": 1},
    )
    assert seen == ["connector_terms"]
    assert result["run_control"]["counts"]["model_calls"] == 1
    assert result["status"] == "blocked"


def test_completed_sources_survive_budget_exhaustion(tmp_path):
    from sci_search.data_research.connectors import eurostat
    from tests.test_connector_eurostat import offline
    from tests.test_connector_recovery import GOOD, model
    from tests.test_connector_stage import STRATEGY

    complete, _ = model([{**GOOD, "filters": {**GOOD["filters"], "geo": ["NL"]}}])
    result = workflow.execute(
        "Life expectancy",
        STRATEGY,
        tmp_path,
        connectors={"eurostat": eurostat},
        fetch=offline,
        complete=complete,
        budget_limits={"model_calls": 4},
    )
    assert result["analyses"], "Keep the completed Dutch source when replanning exhausts the budget"
    assert result["analyses"][0]["execution"]["status"] == "verified"
    assert result["status"] == "partial"
    assert result["run_control"]["stop_reason"]
