import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sci_search.configuration import load_env_file, load_legacy_mistral_key
from sci_search.data_research.strategy import validate_strategy
from sci_search.data_research.workflow import execute

pytestmark = pytest.mark.live_data

QUESTIONS = [
    ("Life expectancy for men and women by European country", dict(measurements=["life expectancy at birth"], geography="Netherlands, Germany, Greece", countries=["NLD", "DEU", "GRC"], start_year=2000, end_year=2024), True),
    ("Renewable electricity share in NL, DE and DK", dict(measurements=["renewable electricity share"], geography="Netherlands, Germany, Denmark", countries=["NLD", "DEU", "DNK"], start_year=2005, end_year=2024), True),
    ("Burned area in Spain, Portugal and Greece", dict(measurements=["burned area"], geography="Spain, Portugal, Greece", countries=["ESP", "PRT", "GRC"], start_year=2001, end_year=2024), True),
    ("Annual mean CO2 at Mauna Loa", dict(measurements=["annual mean atmospheric CO2 concentration"], geography="Mauna Loa", countries=[], start_year=2001, end_year=2024), True),
    ("Electricity storage in the Netherlands", dict(measurements=["battery electricity storage capacity"], geography="Netherlands", countries=["NLD"], start_year=None, end_year=None), True),
    ("Rhine discharge at Lobith", dict(measurements=["annual river discharge"], geography="Rhine at Lobith", countries=[], start_year=1980, end_year=2024), False),
    ("Coral cover on the Great Barrier Reef", dict(measurements=["total coral cover"], geography="Great Barrier Reef", countries=[], start_year=2000, end_year=2025), False),
]  # fmt: skip
OUTCOMES = []
# The provider is read during the run: the environment is restored before teardown_module.
PROVIDERS = set()
# Answered by sources without a connector (EFFIS workbook, NOAA), so they need web search.
WEB_ONLY = {"Burned area in Spain, Portugal and Greece", "Annual mean CO2 at Mauna Loa"}


@pytest.fixture(autouse=True)
def live_configuration():
    """Load provider credentials as the CLI does, and restore the environment afterwards."""
    saved = dict(os.environ)
    load_env_file(Path(".env.local"))
    load_legacy_mistral_key(Path("."))
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.mark.parametrize("question,values,should_succeed", QUESTIONS, ids=[q[0] for q in QUESTIONS])
def test_live_question(tmp_path, question, values, should_succeed):
    strategy = validate_strategy({"route": "data", "rationale": "Acceptance run", **values})
    result = execute(question, strategy, tmp_path)
    succeeded = bool(result["analyses"])
    sources = sorted(
        {
            a["source"].get("connector", {}).get("name") or a["source"]["publisher"]
            for a in result["analyses"]
        }
    )
    OUTCOMES.append(
        (question, succeeded, sources, [g["host"] for g in result.get("connector_gaps", [])])
    )

    provider = os.environ.get("SCI_SEARCH_ANALYSIS_PROVIDER", "mistral")
    PROVIDERS.add(provider)
    connector_only = provider == "mistral"
    if connector_only and (question in WEB_ONLY or not should_succeed):
        # Connector gaps are recorded only for web candidates.
        pytest.skip("needs web search; not measured with the connector-only provider")
    if should_succeed:
        assert succeeded, json.dumps(result["assessments"], default=str)[:3000]
    else:
        assert result.get("connector_gaps"), "expected a named connector gap"


def teardown_module(module):
    if not OUTCOMES:
        return
    provider = ", ".join(sorted(PROVIDERS))
    lines = [
        "# Data connectors acceptance run",
        "",
        f"Run: {datetime.now(UTC).isoformat(timespec='minutes')}. Provider: {provider}.",
        "",
        "| Question | Succeeded | Sources | Connector gaps |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {q} | {'yes' if ok else 'no'} | {', '.join(s) or '-'} | {', '.join(g) or '-'} |"
        for q, ok, s, g in OUTCOMES
    ]
    # One report per provider: the committed results are compared across providers.
    name = "-".join(sorted(PROVIDERS))
    Path(f"docs/operations/data-connectors-acceptance-{name}.md").write_text(
        "\n".join(lines) + "\n"
    )
