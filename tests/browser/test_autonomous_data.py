from playwright.sync_api import expect

from sci_search.dashboard import build_dashboard
from sci_search.data_research.workflow import investigation


def test_automatic_plan_and_source_failure_are_clear(live_browser_url, chromium_browser):
    from sci_search.question_interpretation import interpret_question

    brief = interpret_question("Population in the Netherlands")
    brief.update(ambiguity="clear", provider="openai", model="fixture")
    brief["data_research"] = {
        "adapter": "discovered_data_v1",
        "route": "data",
        "rationale": "Annual data answer the question",
        "measurements": ["population"],
        "geography": "Netherlands",
        "start_year": 2001,
        "end_year": 2024,
    }
    brief["options"] = []  # the response itself is the only version
    page = chromium_browser.new_page()
    page.request.post(live_browser_url + "/auth/development")
    page.route("**/runs/interpret", lambda route: route.fulfill(json=brief))
    page.goto(live_browser_url + "/app")
    page.get_by_label("Research question", exact=True).fill("Population in the Netherlands")
    page.get_by_role("button", name="Review question", exact=True).click()
    approach = page.locator(".choice-row[data-detail='approach']")
    expect(approach.locator(".choice-current")).to_have_text("Find and analyse datasets")
    approach.get_by_role("button", name="Datasets and literature", exact=True).click()
    expect(approach.locator(".choice-current")).to_have_text("Datasets and literature")
    expect(page.get_by_role("button", name="Approve and start review")).to_be_enabled()
    page.close()


def test_generic_series_preserves_small_values_and_model_provenance(
    live_browser_url, chromium_browser
):
    data = {
        "kind": "discovered",
        "status": "partial",
        "strategy": {
            "route": "data",
            "measurements": ["concentration"],
            "rationale": "Annual data",
        },
        "analyses": [
            {
                "kind": "tabular",
                "source": {
                    "title": "Official table",
                    "url": "https://example.org/data.csv",
                    "definition": "Concentration in ppm",
                    "sha256": "abc",
                    "license_note": "Unknown",
                },
                "series": [
                    {
                        "entity": "Station",
                        "label": "Concentration",
                        "unit": "ppm",
                        "missing_years": [2003],
                        "change_percent": None,
                        "annual": [
                            {"year": 2001, "value": 0.04, "source_row": 2},
                            {"year": 2002, "value": 0.06, "source_row": 3},
                            {"year": 2003, "value": None, "source_row": None},
                        ],
                    }
                ],
                "limitations": [],
                "execution": {
                    "status": "verified",
                    "checks": [
                        "Original source hash",
                        "Executed calculation equals published values",
                    ],
                },
                "python_extraction": {
                    "attempts": 2,
                    "review": {"reason": "Source units and selected years checked"},
                    "assumptions": ["Annual concentration"],
                },
            }
        ],
        "limitations": ["Coverage is incomplete"],
        "assessments": [
            {
                "title": "Prepared source",
                "url": "https://example.org/data.csv",
                "decision": "analysed",
                "reason": "Annual table",
                "preparation_checks": {
                    "input_rows": 3,
                    "output_rows": 3,
                    "removed_empty_columns": 2,
                },
                "transformation_attempts": [
                    {
                        "status": "validated",
                        "plan": {"operation": "unpivot"},
                        "checks": {"transformed_rows": 3},
                    }
                ],
            }
        ],
        "discovery": {
            "provider": "openai",
            "model": "fixture",
            "observed_urls": [],
            "search_actions": [],
        },
    }
    snapshot = build_dashboard(
        investigation("Concentration", {}, data), run_id="auto-data", revision=1
    )
    page = chromium_browser.new_page(viewport={"width": 390, "height": 844})
    page.route("**/runs?*", lambda route: route.fulfill(json={"items": [], "next_cursor": None}))
    page.route(
        "**/runs/auto-data/dashboard**",
        lambda route: route.fulfill(json={**snapshot, "role": "owner", "current_revision": 1}),
    )
    page.route(
        "**/runs/auto-data/revisions",
        lambda route: route.fulfill(json={"items": [{"revision": 1}]}),
    )
    page.request.post(live_browser_url + "/auth/development")
    page.goto(live_browser_url + "/app?project=development-project&run=auto-data")
    expect(page.locator("#dashboard-data svg")).to_have_count(1)
    expect(page.locator("#dashboard-model")).to_contain_text("openai · fixture")
    page.get_by_text("Executed Python and validation", exact=True).click()
    expect(
        page.get_by_text("The model wrote and executed the extraction in 2 attempt(s).", exact=True)
    ).to_be_visible()
    expect(
        page.get_by_text("Model review does not replace expert validation.", exact=True)
    ).to_be_visible()
    page.get_by_text("Annual observations and source rows", exact=True).click()
    expect(page.get_by_role("cell", name="0,04", exact=True)).to_be_visible()
    expect(page.get_by_role("cell", name="Missing", exact=True)).to_be_visible()
    page.get_by_text("Why sources were used or could not be used", exact=True).click()
    expect(
        page.get_by_text(
            "Table checked: 3 source rows, 3 prepared rows; 2 entirely empty trailing columns removed.",
            exact=True,
        )
    ).to_be_visible()
    page.get_by_text("Data preparation attempts and checks", exact=True).click()
    expect(page.get_by_text("validated: unpivot.", exact=False)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.close()


def test_many_statistical_series_are_expandable_with_country_and_sex_labels(
    live_browser_url, chromium_browser
):
    data = {
        "kind": "discovered",
        "status": "partial",
        "strategy": {"route": "data", "measurements": ["Life expectancy"], "rationale": "Annual"},
        "analyses": [
            {
                "kind": "tabular",
                "source": {
                    "title": "Statistics",
                    "url": "https://example.org/data",
                    "definition": "Life expectancy",
                    "sha256": "abc",
                    "license_note": "Unknown",
                },
                "preparation": {
                    "selection": {
                        "series_dimensions": ["geo", "sex"],
                        "code_labels": {
                            "geo": {"NL": "Netherlands"},
                            "sex": {"F": "Females"},
                            "unit": {"YR": "Year"},
                        },
                    }
                },
                "series": [
                    {
                        "entity": f"series-{i}",
                        "label": "Life expectancy",
                        "unit": "YR",
                        "annual": [
                            {
                                "year": 2000,
                                "value": 80,
                                "source_row": 2,
                                "source_status": "p",
                                "source_dimensions": {"geo": "NL", "sex": "F"},
                            }
                        ],
                        "missing_years": [],
                        "absolute_change": None,
                        "change_percent": None,
                    }
                    for i in range(11)
                ],
                "limitations": [],
            }
        ],
        "limitations": ["Partial coverage"],
        "assessments": [],
    }
    snapshot = build_dashboard(
        investigation("Life expectancy", {}, data), run_id="stats", revision=1
    )
    page = chromium_browser.new_page(viewport={"width": 390, "height": 844})
    page.route("**/runs?*", lambda route: route.fulfill(json={"items": [], "next_cursor": None}))
    page.route(
        "**/runs/stats/dashboard**",
        lambda route: route.fulfill(json={**snapshot, "role": "owner", "current_revision": 1}),
    )
    page.route(
        "**/runs/stats/revisions", lambda route: route.fulfill(json={"items": [{"revision": 1}]})
    )
    page.request.post(live_browser_url + "/auth/development")
    page.goto(live_browser_url + "/app?project=development-project&run=stats")
    expect(page.get_by_text("Netherlands · Females", exact=True)).to_have_count(11)
    expect(page.locator("#dashboard-data svg")).to_have_count(0)
    page.get_by_text("Netherlands · Females", exact=True).first.click()
    expect(page.locator("#dashboard-data svg")).to_have_count(1)
    expect(page.get_by_text("Unit: Year. Missing years: none.", exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.close()


def test_chart_uses_round_ticks_and_preserves_observations(live_browser_url, chromium_browser):
    page = chromium_browser.new_page()
    try:
        page.request.post(live_browser_url + "/auth/development")
        page.goto(live_browser_url + "/app")
        result = page.evaluate("""async () => {
            const {renderDataResearch} = await import('/static/data_research.js');
            const host = document.createElement('div');
            const values = [539921, 0.000539921, -539921, 0];
            renderDataResearch({kind:'discovered', analyses:[{
                source:{title:'Test',url:'https://example.org/data'}, limitations:[],
                series:values.map(value => ({entity:'Portugal',label:'Burned area',unit:'ha',
                    annual:[{year:2017,value}],missing_years:[]}))
            }]}, host);
            return [...host.querySelectorAll('svg')].map(svg => ({
                ticks:[...svg.querySelectorAll('text[text-anchor="end"]')].map(n => n.textContent),
                title:svg.querySelector('circle title').textContent,
                y:Number(svg.querySelector('circle').getAttribute('cy'))
            }));
        }""")
        assert result[0]["ticks"] == [
            "0",
            "100.000",
            "200.000",
            "300.000",
            "400.000",
            "500.000",
            "600.000",
        ]
        assert result[0]["title"] == "2017: 539.921 ha"
        assert result[1]["ticks"] == [
            "0",
            "0,0001",
            "0,0002",
            "0,0003",
            "0,0004",
            "0,0005",
            "0,0006",
        ]
        assert result[2]["ticks"][0] == "-600.000"
        assert result[2]["ticks"][-1] == "0"
        for chart in result:
            assert 27 <= chart["y"] <= 195
            assert len(set(chart["ticks"])) == len(chart["ticks"])
    finally:
        page.close()


def test_partial_investigation_review_is_visible_without_claiming_overall_answer(
    live_browser_url, chromium_browser
):
    import json
    from pathlib import Path

    snapshot = json.loads((Path(__file__).parents[1] / "fixtures/dashboard_v1.json").read_text())
    for block in snapshot["blocks"]:
        if block["id"] == "answer":
            block["status"] = "ready"
            block["data"]["investigation_review"] = {
                "qualification": "Partial evidence only; the whole question remains unresolved.",
                "partial_findings": [
                    {
                        "subject": "coral cover",
                        "title": "Observed reef sites",
                        "quote": "Coral cover declined at the surveyed sites.",
                        "qualification": "2000–2010 only.",
                        "doi": "10.123/example",
                    }
                ],
                "steps": [
                    {
                        "decision": {"reason": "Review cover separately"},
                        "outcome": {"status": "retained"},
                    }
                ],
                "stop_reason": "No evidence for 2026.",
            }
    page = chromium_browser.new_page()
    try:
        page.route(
            "**/runs?*", lambda route: route.fulfill(json={"items": [], "next_cursor": None})
        )
        page.route(
            "**/runs/reflection/dashboard**",
            lambda route: route.fulfill(json={**snapshot, "role": "owner", "current_revision": 1}),
        )
        page.route(
            "**/runs/reflection/revisions",
            lambda route: route.fulfill(json={"items": [{"revision": 1}]}),
        )
        page.request.post(live_browser_url + "/auth/development")
        page.goto(live_browser_url + "/app?project=development-project&run=reflection")
        expect(
            page.get_by_text("Coral cover declined at the surveyed sites.", exact=True)
        ).to_be_visible()
        expect(
            page.get_by_text(
                "Partial evidence only; the whole question remains unresolved.", exact=True
            )
        ).to_be_visible()
        expect(page.get_by_role("link", name="Source publication", exact=True)).to_have_attribute(
            "href", "https://doi.org/10.123/example"
        )
    finally:
        page.close()


def test_unconfirmed_meaning_and_malformed_reviews_remain_visible(
    live_browser_url, chromium_browser
):
    page = chromium_browser.new_page()
    page.request.post(live_browser_url + "/auth/development")
    page.goto(live_browser_url + "/app")
    page.evaluate("""async () => {
      const {renderDataResearch} = await import('/static/data_research.js');
      const host = document.createElement('div'); host.id = 'meaning-test'; document.body.append(host);
      renderDataResearch({kind:'discovered', analyses:[], limitations:[], assessments:[{
        title:'Source', url:'https://example.org/data', decision:'blocked', reason:'Definitions conflict',
        semantic_reviews:[{accepted:false, reason:'Addition may double count',
          measurements:[null, {measurement:'Total', checks:[null, {aspect:'calculation',status:'conflicting',reason:'Same definition',evidence:[null,{document:'readme',quote:'Both fields measure live coral cover.'}]}]}],
          followup_questions:['Which components are disjoint?']}]
      }]}, host);
    }""")
    expect(
        page.locator("#meaning-test").get_by_text("Addition may double count", exact=True)
    ).to_be_visible()
    expect(page.locator("#meaning-test blockquote")).to_have_text(
        "Both fields measure live coral cover."
    )
    expect(
        page.locator("#meaning-test").get_by_text(
            "Documentation needed: Which components are disjoint?", exact=True
        )
    ).to_be_visible()
    page.close()


def test_connector_gaps_and_recovery_are_visible(live_browser_url, chromium_browser):
    page = chromium_browser.new_page()
    page.request.post(live_browser_url + "/auth/development")
    page.goto(live_browser_url + "/app")
    page.evaluate("""async () => {
      const {renderDataResearch} = await import('/static/data_research.js');
      const host = document.createElement('div'); host.id = 'gap-test'; document.body.append(host);
      renderDataResearch({kind:'discovered', analyses:[], limitations:[],
        connector_gaps:[{host:'waterinfo.rws.nl', measurement:'river discharge', evidence:'Loading only'},
          {host:'<img src=x onerror=window.pwned=1>', measurement:'m', evidence:'e'}],
        assessments:[{title:'Life expectancy', url:'https://ec.europa.eu/x', decision:'blocked', reason:'No published series',
          connector:'eurostat', recovery:[{class:'selection', action:'repair', outcome:'Unobserved code for sex'}]}]}, host);
    }""")
    gap = page.locator("#gap-test")
    expect(
        gap.get_by_text("Needs an API connector for waterinfo.rws.nl (river discharge)", exact=True)
    ).to_be_visible()
    expect(
        gap.get_by_text(
            "Automatic recovery: selection → repair · Unobserved code for sex", exact=True
        )
    ).to_be_attached()
    assert page.locator("#gap-test img").count() == 0
    assert page.evaluate("window.pwned") is None
    page.close()
