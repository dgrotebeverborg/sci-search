import json
from pathlib import Path

from sci_search.cli import main

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "fixtures" / "iron_air_pilot"
GOLD = CORPUS / "gold" / "round_trip_efficiency.json"
RTE_QUESTION = "What round-trip efficiencies are reported for iron-air batteries?"


def test_compare_and_evaluate_commands_emit_structured_results(capsys):
    assert main(("--corpus", str(CORPUS), "compare")) == 0
    comparison = json.loads(capsys.readouterr().out)
    assert comparison["metric"] == "round_trip_efficiency"
    assert comparison["results"]

    assert main(("--corpus", str(CORPUS), "evaluate", "--gold", str(GOLD))) == 0
    evaluation = json.loads(capsys.readouterr().out)
    assert evaluation["passed"] is True


def test_export_command_writes_both_versioned_artifact_formats(tmp_path):
    evidence_path = tmp_path / "evidence.json"
    graph_path = tmp_path / "graph.json"

    assert (
        main(
            (
                "--corpus",
                str(CORPUS),
                "export",
                "--format",
                "evidence",
                "--output",
                str(evidence_path),
            )
        )
        == 0
    )
    assert (
        main(
            (
                "--corpus",
                str(CORPUS),
                "export",
                "--format",
                "graph",
                "--output",
                str(graph_path),
            )
        )
        == 0
    )

    assert json.loads(evidence_path.read_text())["artifact_contract_version"] == (
        "scientific_evidence_v1"
    )
    assert json.loads(graph_path.read_text())["artifact_contract_version"] == (
        "scientific_evidence_graph_v1"
    )


def test_investigate_command_renders_specialist_and_generic_formats(tmp_path, capsys):
    specialist_json = tmp_path / "specialist.json"
    generic_html = tmp_path / "generic.html"

    assert (
        main(
            (
                "--corpus",
                str(CORPUS),
                "investigate",
                "--question",
                RTE_QUESTION,
                "--format",
                "json",
                "--output",
                str(specialist_json),
            )
        )
        == 0
    )
    assert json.loads(specialist_json.read_text())["question"] == RTE_QUESTION

    assert (
        main(
            (
                "--corpus",
                str(CORPUS),
                "investigate",
                "--question",
                "How do dolphins communicate with cuttlefish?",
                "--format",
                "html",
                "--output",
                str(generic_html),
            )
        )
        == 0
    )
    assert "What the corpus shows" in generic_html.read_text()

    assert (
        main(
            (
                "--corpus",
                str(CORPUS),
                "investigate",
                "--question",
                RTE_QUESTION,
                "--format",
                "markdown",
            )
        )
        == 0
    )
    assert "# Sci-Search research report" in capsys.readouterr().out
