from pathlib import Path

from playwright.sync_api import expect

from sci_search.dashboard import build_dashboard
from sci_search.data_research.wildfire import investigation, propose, run
from sci_search.question_interpretation import interpret_question


def test_wildfire_plan_exposes_route_scope_and_years(live_browser_url, chromium_browser):
    page = chromium_browser.new_page()
    page.goto(live_browser_url)
    page.get_by_role("button", name="Continue with development account").click()
    page.get_by_label("Research question", exact=True).fill(
        "What are the developments in European wildfire numbers and km2 this century?"
    )
    page.get_by_role("button", name="Review question", exact=True).click()
    expect(page.get_by_label("Research approach", exact=True)).to_have_value("data")
    expect(page.get_by_label("Country scope", exact=True)).to_have_value("europe")
    page.get_by_label("First year", exact=True).fill("2020")
    page.get_by_label("Last year", exact=True).fill("2010")
    expect(page.get_by_role("button", name="Approve and start review")).to_be_disabled()
    page.get_by_label("Last year", exact=True).fill("2024")
    expect(page.get_by_role("button", name="Approve and start review")).to_be_enabled()
    page.close()


def test_saved_wildfire_data_has_charts_and_missing_coverage(
    live_browser_url, chromium_browser, tmp_path
):
    question = "European wildfire counts and burned area this century"
    result = run(
        propose(question),
        tmp_path,
        fetch=lambda: (
            Path(__file__).parents[1] / "fixtures/data_research/effis_report_2024.xlsx"
        ).read_bytes(),
    )
    snapshot = build_dashboard(
        investigation(question, interpret_question(question), result),
        run_id="fire-data",
        revision=1,
    )
    page = chromium_browser.new_page(viewport={"width": 390, "height": 844})
    page.route("**/runs?*", lambda route: route.fulfill(json={"items": [], "next_cursor": None}))
    page.route(
        "**/runs/fire-data/dashboard**",
        lambda route: route.fulfill(json={**snapshot, "role": "owner", "current_revision": 1}),
    )
    page.route(
        "**/runs/fire-data/revisions",
        lambda route: route.fulfill(json={"items": [{"revision": 1}]}),
    )
    page.request.post(f"{live_browser_url}/auth/development")
    page.goto(f"{live_browser_url}/app?project=development-project&run=fire-data")
    expect(page.get_by_text("A reporting panel, not all Europe", exact=True)).to_be_visible()
    expect(page.locator("#dashboard-data svg")).to_have_count(2)
    expect(page.locator("#dashboard-model")).to_contain_text("no AI-generated numerical values")
    page.get_by_text("Annual values and coverage", exact=True).click()
    expect(
        page.locator("#dashboard-data").get_by_role("cell", name="Missing", exact=True).first
    ).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.close()
