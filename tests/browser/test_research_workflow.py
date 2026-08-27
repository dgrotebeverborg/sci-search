from __future__ import annotations

from playwright.sync_api import Browser, expect


def _login(page, origin: str) -> None:
    page.goto(origin)
    page.get_by_role("button", name="Continue with development account").click()
    expect(page).to_have_url(f"{origin}/app")


def test_start_cancel_evidence_validation_and_download_workflow(
    live_browser_url: str,
    chromium_browser: Browser,
) -> None:
    page = chromium_browser.new_page()
    _login(page, live_browser_url)

    page.get_by_label("Research question").fill(
        "What round-trip efficiencies have been reported for iron-air batteries?"
    )
    page.get_by_role("button", name="Start review").click()
    expect(page.locator("#run-status")).to_have_text("queued")
    page.get_by_role("button", name="Cancel review").click()
    expect(page.locator("#run-status")).to_have_text("cancel requested")
    expect(page.get_by_text("A source-linked scientific finding")).to_be_visible()
    expect(page.get_by_text("provenance", exact=True)).to_be_visible()
    expect(page.get_by_role("link", name="Download research package")).to_be_visible()
    page.close()
