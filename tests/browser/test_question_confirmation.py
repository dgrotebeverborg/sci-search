from playwright.sync_api import expect


def test_question_is_interpreted_before_explicit_approval(
    live_browser_url, chromium_browser, monkeypatch
):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    page = chromium_browser.new_page()
    try:
        page.goto(live_browser_url)
        page.get_by_role("button", name="Continue with development account").click()
        page.get_by_label("Research question").fill(
            "How do energy markets affect European consumers?"
        )
        page.get_by_role("button", name="Review question", exact=True).click()
        expect(page.locator("#question-brief")).to_be_visible()
        expect(page.locator("#run-panel")).not_to_be_visible()
        page.get_by_label("Research question").fill(
            "How do energy markets affect household electricity prices in Europe?"
        )
        expect(page.locator("#question-brief")).not_to_be_visible()
        page.get_by_role("button", name="Review question", exact=True).click()
        expect(page.locator("#brief-question")).to_contain_text("household electricity prices")
        page.get_by_role("button", name="Approve and start review").click()
        expect(page.locator("#run-status")).to_have_text("queued")
    finally:
        page.close()
