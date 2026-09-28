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
    page.get_by_role("button", name="Review question").click()
    page.get_by_role("button", name="Approve and start review").click()
    expect(page.locator("#run-status")).to_have_text("queued")
    page.get_by_role("button", name="Cancel review").click()
    expect(page.locator("#run-status")).to_have_text("cancel requested")
    expect(page.get_by_text("A source-linked scientific finding")).not_to_be_visible()
    expect(page.get_by_text("provenance", exact=True)).not_to_be_visible()
    expect(page.get_by_role("link", name="Download research package")).not_to_be_visible()
    page.close()


def test_research_controls_wait_for_javascript_initialization(
    live_browser_url: str,
    chromium_browser: Browser,
) -> None:
    page = chromium_browser.new_page()
    try:
        page.route("**/static/**/app.js", lambda route: route.abort())
        _login(page, live_browser_url)
        expect(page.get_by_role("button", name="Review question")).to_be_disabled()
        expect(page.get_by_label("Research question")).to_be_disabled()
        page.get_by_text("New project", exact=True).click()
        expect(page.get_by_role("button", name="Create project")).to_be_disabled()
        expect(page.get_by_role("button", name="Sign out")).to_be_disabled()

        page.unroute("**/static/**/app.js")
        page.reload()
        page.get_by_label("Research question").fill("What evidence is available?")
        page.get_by_role("button", name="Review question").click()
        page.get_by_role("button", name="Approve and start review").click()
        expect(page.locator("#run-status")).to_have_text("queued")
        expect(page).to_have_url(f"{live_browser_url}/app")
    finally:
        page.close()


def test_completed_review_refreshes_results_without_switching_projects(
    live_browser_url: str,
    chromium_browser: Browser,
) -> None:
    page = chromium_browser.new_page()
    completed = False

    def evidence(route):
        route.fulfill(
            json={
                "items": (
                    [
                        {
                            "id": "fresh-evidence",
                            "statement": "Fresh research finding",
                            "source_passage": "Newly acquired source passage",
                            "version": 1,
                        }
                    ]
                    if completed
                    else []
                ),
                "total": 1 if completed else 0,
            }
        )

    def run(route):
        nonlocal completed
        completed = True
        route.fulfill(
            status=201,
            json={
                "id": "finished-run",
                "project_id": "development-project",
                "question": "What does the evidence say?",
                "status": "completed",
            },
        )

    page.route("**/evidence?*", evidence)
    page.route("**/runs", run)
    try:
        _login(page, live_browser_url)
        expect(page.locator(".evidence-card")).to_have_count(0)
        page.get_by_label("Research question").fill("What does the evidence say?")
        page.get_by_role("button", name="Review question").click()
        page.get_by_role("button", name="Approve and start review").click()
        expect(page.locator("#run-status")).to_have_text("completed")
        expect(page.get_by_text("Fresh research finding", exact=True)).to_be_visible()
    finally:
        page.close()


def test_start_screen_does_not_fetch_or_display_previous_project_results(
    live_browser_url, chromium_browser
):
    page = chromium_browser.new_page()
    results_requests = []
    page.on(
        "request",
        lambda request: (
            results_requests.append(request.url)
            if "/api/" in request.url
            and any(part in request.url for part in ("/evidence?", "/validation", "/exports"))
            else None
        ),
    )
    try:
        _login(page, live_browser_url)
        expect(page.get_by_role("button", name="Review question")).to_be_enabled()
        for name in ("evidence", "validation", "exports"):
            expect(page.locator("#" + name)).to_be_hidden()
        expect(page.get_by_text("A source-linked scientific finding")).not_to_be_visible()
        assert results_requests == []
    finally:
        page.close()
