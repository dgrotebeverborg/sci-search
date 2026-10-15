"""Joining inputs must not silently mix geography, strata or sources."""

import copy
import json
import subprocess
import sys

import pytest

from tests.test_data_calculations import plan, scope, series


def analysis(label, entity="Netherlands", values=(200, 220, 300), unit="euro"):
    item = series(values, unit)
    item.update(label=label, entity=entity)
    return {
        "series": [item],
        "source": {"sha256": label + entity},
        "execution": {"status": "verified"},
    }


def prepared(request, analyses):
    from sci_search.data_research.derived_outputs import prepare_jobs

    return prepare_jobs(request, analyses)


def test_two_sources_for_one_input_are_not_spliced_or_chosen_silently():
    a = analysis("price")
    b = copy.deepcopy(a)
    b["source"]["sha256"] = "second"
    jobs = prepared(scope([plan()]), [a, b])
    assert len(jobs) == 1
    assert "ambiguous" in jobs[0]["reason"].lower()


def test_reference_country_must_match_input_country():
    item = {
        **plan(),
        "operation": "share",
        "base_year": None,
        "input": "hydro",
        "reference": "total",
    }
    jobs = prepared(
        scope([item]), [analysis("hydro", unit="GWh"), analysis("total", "Germany", unit="GWh")]
    )
    assert jobs[0]["reference"] is None
    assert "reference" in jobs[0]["reason"].lower()


def test_explicit_sex_breakdown_is_not_joined_to_a_total_reference():
    request = scope([{**plan(), "operation": "share", "base_year": None, "reference": "total"}])
    request["requirements"] = [
        {"measurement": "price", "breakdowns": [{"dimension": "sex", "values": ["female"]}]}
    ]
    source = analysis("price", "Netherlands female")
    reference = analysis("total")
    jobs = prepared(request, [source, reference])
    assert jobs[0]["reason"]


def test_cross_source_arithmetic_requires_a_validated_meaning_review():
    from sci_search.data_research.derived_outputs import compute

    item = {
        **plan(),
        "operation": "share",
        "base_year": None,
        "input": "hydro",
        "reference": "total",
    }
    request = scope([item])
    analyses = [
        analysis("hydro", values=(1, 2, 3), unit="TWh"),
        analysis("total", values=(2, 4, 6), unit="TWh"),
    ]
    result = compute({"scope": request, "analyses": analyses, "jobs": prepared(request, analyses)})
    assert result["status"] == "blocked"
    assert all(r["value"] is None for r in result["outputs"][0]["annual"])
    assert "review" in result["outputs"][0]["reason"].lower()


def test_calculation_completion_is_separate_from_raw_coverage():
    from sci_search.data_research.derived_outputs import completion

    coverage = {"cells": [{"status": "complete"}], "gaps": []}
    assert (
        completion({"calculations": [plan()]}, coverage, {"status": "blocked"})[
            "numerical_answer_status"
        ]
        == "partial"
    )
    assert (
        completion({}, coverage, {"status": "not_assessed"})["numerical_answer_status"]
        == "not_assessed"
    )
    assert (
        completion({"calculations": []}, coverage, {"status": "not_requested"})[
            "numerical_answer_status"
        ]
        == "complete"
    )


def retained(tmp_path):
    from sci_search.data_research import artifacts
    from tests.test_python_data_artifacts import fixture

    folder = tmp_path / "source-1"
    folder.mkdir()
    a = artifacts.execute_analysis(fixture(folder), folder)
    (folder / "analysis.json").write_text(json.dumps(a))
    request = dict(
        route="data",
        rationale="Index",
        measurements=["population"],
        geography="population",
        start_year=2001,
        end_year=2003,
        calculations=[{**plan(), "input": "population", "base_year": 2001}],
    )
    return {"kind": "discovered", "strategy": request, "analyses": [a]}


def test_derived_values_are_isolated_replayable_and_tamper_checked(tmp_path):
    from sci_search.data_research import artifacts, derived_artifacts

    result = retained(tmp_path)
    derived_artifacts.finalize(result, tmp_path)
    assert [r["value"] for r in result["derived_outputs"]["outputs"][0]["annual"]] == [
        100,
        None,
        120,
    ]
    assert result["output_completion"]["calculation_status"] == "partial"
    (tmp_path / "analysis.json").write_text(json.dumps(result))
    artifacts.write_replay(tmp_path)
    replay = subprocess.run(
        [sys.executable, str(tmp_path / "reproduce.py")], capture_output=True, text=True
    )
    assert replay.returncode == 0, replay.stderr
    result["derived_outputs"]["outputs"][0]["annual"][0]["value"] = 999
    (tmp_path / "analysis.json").write_text(json.dumps(result))
    replay = subprocess.run(
        [sys.executable, str(tmp_path / "reproduce.py")], capture_output=True, text=True
    )
    assert replay.returncode != 0
    assert "derived" in replay.stderr.lower()


def test_changed_raw_source_cannot_feed_a_new_calculation(tmp_path):
    from sci_search.data_research import derived_artifacts

    result = retained(tmp_path)
    (tmp_path / "source-1/source.csv").write_bytes(b"Year,Value\n2001,999\n")
    derived_artifacts.finalize(result, tmp_path)
    assert result["derived_outputs"]["status"] == "blocked"
    assert "hash" in result["derived_outputs"]["reason"].lower()


def sealed_series(root, name, values, unit, definition):
    import hashlib

    from sci_search.data_research import artifacts
    from sci_search.data_research.tabular import analyse_csv

    folder = root / ("source-" + name)
    folder.mkdir()
    body = (
        "Year,Country,Value\n"
        + "".join(f"{2000 + i},Netherlands,{v}\n" for i, v in enumerate(values))
    ).encode()
    (folder / "source.csv").write_bytes(body)
    (folder / "semantic-review.json").write_text(
        json.dumps({"review": {"accepted": True}, "evidence_documents": {"metadata": definition}})
    )
    mapping = dict(
        year_column="Year",
        value_column="Value",
        entity_column="Country",
        entities=["Netherlands"],
        label=name,
        unit=unit,
        output_unit=unit,
    )
    a = analyse_csv(body, mapping, {"start_year": 2000, "end_year": 2002})
    a.update(
        kind="tabular",
        source={
            "title": name,
            "url": "https://example.test/" + name,
            "artifact": "source.csv",
            "sha256": hashlib.sha256(body).hexdigest(),
        },
    )
    a = artifacts.execute_analysis(a, folder)
    (folder / "analysis.json").write_text(json.dumps(a))
    return a


@pytest.mark.parametrize("decision", ["supported", "conflicting", "invented_quote"])
def test_cross_source_review_validates_original_evidence_before_publication(tmp_path, decision):
    from sci_search.data_research import derived_artifacts

    left = sealed_series(
        tmp_path,
        "hydro",
        [100, 200, 300],
        "GWh",
        "Annual gross hydro electricity production in GWh for Netherlands.",
    )
    right = sealed_series(
        tmp_path,
        "total",
        [200, 400, 600],
        "GWh",
        "Annual gross total electricity production in GWh for Netherlands.",
    )
    item = {
        **plan(),
        "operation": "share",
        "input": "hydro",
        "reference": "total",
        "base_year": None,
    }
    result = {"strategy": scope([item]), "analyses": [left, right]}

    def complete(prompt, schema):
        payload = json.loads(prompt.rsplit("\n", 1)[1])
        docs = payload["evidence_documents"]
        return {
            "measurements": [
                {
                    "measurement": item["label"],
                    "transformation": "derived",
                    "checks": [
                        {
                            "aspect": aspect,
                            "status": "conflicting" if decision == "conflicting" else "supported",
                            "reason": "Inputs establish the same gross production basis."
                            if decision != "conflicting"
                            else "Gross and net definitions differ.",
                            "evidence": [
                                {
                                    "document": key,
                                    "quote": "This is not in the source."
                                    if decision == "invented_quote"
                                    else value,
                                }
                                for key, value in docs.items()
                            ],
                        }
                        for aspect in ("definition", "unit", "geography", "time", "calculation")
                    ],
                    "followup_question": "",
                }
            ]
        }

    derived_artifacts.finalize(result, tmp_path, complete=complete)
    outputs = result["derived_outputs"]["outputs"]
    assert len(outputs) == 1
    if decision == "supported":
        assert [r["value"] for r in outputs[0]["annual"]] == [50, 50, 50]
    else:
        assert outputs[0]["status"] == "blocked"
        assert all(r["value"] is None for r in outputs[0]["annual"])


def test_budget_exit_still_records_unfinished_requested_calculations(tmp_path):
    from sci_search.data_research.workflow import execute

    result = execute(
        "Index", scope([plan()]), tmp_path, budget_limits={"seconds": 0}, connectors={}
    )
    assert result["derived_outputs"]["status"] == "blocked"
    assert result["output_completion"]["numerical_answer_status"] == "blocked"
    saved = json.loads((tmp_path / "analysis.json").read_text())
    assert saved["derived_outputs"] == result["derived_outputs"]


def test_missing_base_year_does_not_spend_a_review_call(tmp_path):
    from sci_search.data_research import derived_artifacts

    left = sealed_series(
        tmp_path,
        "price",
        [200, 220, 300],
        "euro",
        "Annual average nominal house price in euros for Netherlands.",
    )
    right = sealed_series(
        tmp_path,
        "CPI",
        [80, 88, 100],
        "2015 = 100",
        "Annual consumer price index for Netherlands, 2015 = 100.",
    )
    item = {**plan(), "operation": "real_index", "reference": "CPI", "base_year": 1999}
    result = {"strategy": scope([item]), "analyses": [left, right]}

    def forbidden(*args):
        raise AssertionError("Missing baseline must be detected before meaning review")

    derived_artifacts.finalize(result, tmp_path, complete=forbidden)
    assert result["derived_outputs"]["status"] == "blocked"
    assert "1999" in result["derived_outputs"]["outputs"][0]["reason"]


def test_changed_analysis_cannot_replace_sealed_executed_values(tmp_path):
    from sci_search.data_research import derived_artifacts

    result = retained(tmp_path)
    result["analyses"][0]["series"][0]["annual"][0]["value"] = 1
    (tmp_path / "source-1/analysis.json").write_text(json.dumps(result["analyses"][0]))
    derived_artifacts.finalize(result, tmp_path)
    assert result["derived_outputs"]["status"] == "blocked"
    assert "executed" in result["derived_outputs"]["reason"].lower()


def test_unsealed_documentation_is_not_definition_evidence(tmp_path):
    from sci_search.data_research import derived_artifacts

    result = retained(tmp_path)
    (tmp_path / "source-1/semantic-review-extra.json").write_text(
        json.dumps(
            {
                "review": {"accepted": True},
                "evidence_documents": {"fabricated": "Fake gross definition"},
            }
        )
    )
    folders = derived_artifacts._retained(tmp_path, result["analyses"])
    assert derived_artifacts._documents(folders, [0]) == {}


def test_mutable_cached_approval_cannot_authorize_a_calculation(tmp_path):
    from sci_search.data_research import derived_artifacts
    from sci_search.data_research.execution import digest

    left = sealed_series(tmp_path, "hydro", [1, 2, 3], "GWh", "Net production")
    right = sealed_series(tmp_path, "total", [2, 4, 6], "GWh", "Gross production")
    item = {
        **plan(),
        "operation": "share",
        "input": "hydro",
        "reference": "total",
        "base_year": None,
    }
    result = {"strategy": scope([item]), "analyses": [left, right]}
    group = prepared(result["strategy"], result["analyses"])
    fingerprint = digest(
        json.dumps(
            {"plan": item, "analyses": result["analyses"], "group": group}, sort_keys=True
        ).encode()
    )
    result["calculation_reviews"] = {
        item["id"]: {"fingerprint": fingerprint, "review": {"accepted": True}}
    }
    derived_artifacts.finalize(result, tmp_path)
    assert result["derived_outputs"]["status"] == "blocked"


def test_exhausted_review_budget_preserves_prior_reviewed_calculation(tmp_path):
    from sci_search.data_research import derived_artifacts
    from sci_search.data_research.run_control import BudgetExhausted

    left = sealed_series(tmp_path, "hydro", [1, 2, 3], "GWh", "Annual gross hydro production")
    right = sealed_series(tmp_path, "total", [2, 4, 6], "GWh", "Annual gross total production")
    first = {
        **plan(),
        "operation": "share",
        "input": "hydro",
        "reference": "total",
        "base_year": None,
    }
    second = {**first, "id": "second", "label": "second share"}
    result = {"strategy": scope([first, second]), "analyses": [left, right]}
    calls = []

    def complete(prompt, schema):
        calls.append(prompt)
        if len(calls) == 2:
            raise BudgetExhausted("Review budget exhausted")
        docs = json.loads(prompt.rsplit("\n", 1)[1])["evidence_documents"]
        return {
            "measurements": [
                {
                    "measurement": first["label"],
                    "transformation": "derived",
                    "checks": [
                        {
                            "aspect": aspect,
                            "status": "supported",
                            "reason": "Matching gross production",
                            "evidence": [
                                {"document": key, "quote": value} for key, value in docs.items()
                            ],
                        }
                        for aspect in ("definition", "unit", "geography", "time", "calculation")
                    ],
                    "followup_question": "",
                }
            ]
        }

    derived_artifacts.finalize(result, tmp_path, complete=complete)
    outputs = result["derived_outputs"]["outputs"]
    assert [r["value"] for r in outputs[0]["annual"]] == [50, 50, 50]
    assert outputs[1]["status"] == "blocked"
    assert result["derived_outputs"]["status"] == "partial"


@pytest.mark.parametrize("separator", [" ", "\n"])
def test_large_definition_document_preserves_cited_original_context(tmp_path, separator):
    from sci_search.data_research import artifacts, derived_artifacts
    from tests.test_python_data_artifacts import fixture

    folder = tmp_path / "source-1"
    folder.mkdir()
    source = fixture(folder)
    quote = "Annual gross electricity production."
    original_quote = quote.replace("gross ", "gross" + separator)
    original = (
        quote
        + " Excludes pumped storage."
        + "Unrelated catalogue entry. " * 15000
        + original_quote
        + " Includes pumped storage."
    )
    (folder / "semantic-review.json").write_text(
        json.dumps(
            {
                "review": {
                    "accepted": True,
                    "measurements": [
                        {"checks": [{"evidence": [{"document": "metadata", "quote": quote}]}]}
                    ],
                },
                "evidence_documents": {"metadata": original},
            }
        )
    )
    source = artifacts.execute_analysis(source, folder)
    (folder / "analysis.json").write_text(json.dumps(source))
    folders = derived_artifacts._retained(tmp_path, [source])
    documents = derived_artifacts._documents(folders, [0])
    combined = "\n".join(documents.values())
    assert original_quote in combined
    assert "Excludes pumped storage." in combined
    assert "Includes pumped storage." in combined
    assert len(combined) < 30000
