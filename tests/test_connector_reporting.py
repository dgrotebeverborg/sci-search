from sci_search.data_research.reporting import markdown_appendix

GAP = {"host": "waterinfo.rws.nl", "measurement": "river discharge", "evidence": "Loading only"}


def _result(**extra):
    return {"kind": "discovered", "analyses": [], "assessments": [], "limitations": [], **extra}


def test_appendix_lists_connector_gaps():
    text = markdown_appendix(_result(connector_gaps=[GAP]))
    assert "### Connector gaps" in text
    assert "- Needs an API connector for waterinfo.rws.nl (river discharge)" in text


def test_appendix_escapes_gap_text_and_omits_heading_without_gaps():
    assert "Connector gaps" not in markdown_appendix(_result())
    text = markdown_appendix(_result(connector_gaps=[{**GAP, "host": "a|b\nc"}]))
    assert "a/b c" in text


def test_appendix_lists_recovery_and_connector_provenance():
    assessment = {
        "title": "Life expectancy",
        "decision": "blocked",
        "reason": "No series",
        "recovery": [{"class": "selection", "action": "repair", "outcome": "Unobserved|code"}],
    }
    analysis = {
        "kind": "tabular",
        "series": [],
        "source": {
            "title": "T",
            "url": "https://x.example/d",
            "sha256": "ab",
            "publisher": "Eurostat",
            "connector": {
                "name": "eurostat",
                "dataset": "demo_mlexpec",
                "request": {"url": "https://x.example/api?a=1"},
            },
        },
    }
    text = markdown_appendix(_result(assessments=[assessment], analyses=[analysis]))
    assert "Automatic recovery: selection → repair · Unobserved/code" in text
    assert "Queried the Eurostat API: dataset demo_mlexpec" in text
    assert "Exact request: https://x.example/api?a=1" in text


def test_the_live_acceptance_report_is_named_after_its_provider(tmp_path, monkeypatch):
    from tests.live import test_data_connectors_live as live

    (tmp_path / "docs/operations").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(live, "OUTCOMES", [("Question", True, ["eurostat"], [])])
    monkeypatch.setattr(live, "PROVIDERS", {"mistral"})
    live.teardown_module(live)
    written = tmp_path / "docs/operations/data-connectors-acceptance-mistral.md"
    assert [p.name for p in (tmp_path / "docs/operations").iterdir()] == [written.name]
    assert "| Question | yes | eurostat | - |" in written.read_text()
