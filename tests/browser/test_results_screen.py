from playwright.sync_api import Browser, expect

from sci_search.dashboard import build_dashboard
from tests.test_result_summary import hpv_snapshot


def open_snapshot(page, url, snapshot):
    page.route("**/runs/A/dashboard", lambda route: route.fulfill(json=snapshot))
    page.route(
        "**/runs/A/revisions", lambda route: route.fulfill(json={"items": [{"revision": 1}]})
    )
    page.request.post(f"{url}/auth/development")
    page.goto(f"{url}/app?project=development-project&run=A")


def test_one_clean_page_with_the_answer_first(live_browser_url: str, chromium_browser: Browser):
    page = chromium_browser.new_page()
    open_snapshot(page, live_browser_url, {**hpv_snapshot(), "role": "owner"})
    sections = page.locator("[data-result-section]")
    expect(sections.first).to_have_attribute("data-result-section", "answer")
    order = sections.evaluate_all("nodes => nodes.map(n => n.dataset.resultSection)")
    assert order == ["answer", "literature", "why", "landscape", "details"]
    answer = page.locator("#dashboard-answer")
    expect(answer.locator(".certainty-pill")).to_have_text("Weak evidence")
    expect(answer).to_contain_text("covering the Netherlands and Sweden")
    expect(page.locator("#dashboard-why")).to_contain_text(
        "No included study covers the United Kingdom."
    )
    expect(page.locator("#dashboard-why")).to_contain_text("Cervical screening in Brazil")
    expect(page.locator("#dashboard-why")).to_contain_text("Literature coverage is not verified")
    # Three tabs; the landscape and details are separate views, the landscape drawn when shown.
    tabs = page.get_by_role("tab")
    expect(tabs).to_have_text(["Answer", "Research landscape", "Details"])
    expect(page.get_by_role("tab", name="Answer")).to_have_attribute("aria-selected", "true")
    expect(page.locator("#dashboard-landscape")).to_be_hidden()
    expect(page.locator("#dashboard-details")).to_be_hidden()
    page.get_by_role("tab", name="Research landscape").click()
    expect(page.locator("#dashboard-landscape")).to_contain_text("Discovered studies")
    expect(page.locator("#dashboard-answer")).to_be_hidden()
    page.get_by_role("tab", name="Answer").click()
    # Evidence links switch to the details and open the passage.
    answer.get_by_role("link", name="Evidence e1", exact=True).click()
    expect(page.get_by_role("tab", name="Details")).to_have_attribute("aria-selected", "true")
    expect(page.locator("#evidence-e1")).to_be_visible()
    page.get_by_role("tab", name="Answer").click()

    # The content starts where the question starts.
    def left(selector):
        return page.locator(selector).evaluate("n => Math.round(n.getBoundingClientRect().left)")

    assert left("#dashboard-answer") == left("#dashboard-question")
    # No internal identifiers on the answer tab.
    expect(page.locator("#dashboard-navigation")).to_have_count(0)
    visible = page.locator("#dashboard-panel-answer").all_inner_texts()
    assert not any("coverage:" in t or "executive_summary" in t for t in visible)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.screenshot(path="/tmp/sci-search-results-screen.png", full_page=True)
    page.close()


def test_a_data_answer_shows_the_data_part_only(live_browser_url: str, chromium_browser: Browser):
    from tests.test_result_summary import data_snapshot

    page = chromium_browser.new_page()
    open_snapshot(page, live_browser_url, data_snapshot())
    expect(page.locator("#dashboard-answer")).to_be_visible()
    order = page.locator("[data-result-section]").evaluate_all(
        "nodes => nodes.map(n => n.dataset.resultSection)"
    )
    assert order == ["answer", "data", "details"]
    expect(page.locator("#dashboard-data")).to_contain_text("Krefeld S1 Dataset")
    expect(page.locator("#dashboard-data")).to_contain_text("Germany · 1989–2016 · g/day")
    page.close()


def test_a_saved_snapshot_without_summary_still_opens(
    live_browser_url: str, chromium_browser: Browser
):
    snapshot = build_dashboard(
        {"question": "Old question", "answer_summary": "Old answer"}, run_id="A", revision=1
    )
    snapshot.pop("summary")
    page = chromium_browser.new_page()
    open_snapshot(page, live_browser_url, snapshot)
    expect(page.locator("#dashboard-answer")).to_contain_text("Old answer")
    expect(page.locator(".certainty-pill")).to_have_text("Not assessed")
    page.close()
