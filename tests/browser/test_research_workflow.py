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
    expect(page.get_by_label("Research question")).to_be_hidden()
    expect(page.locator("#question-brief")).to_be_hidden()
    page.get_by_role("button", name="Cancel review").click()
    expect(page.locator("#run-status")).to_have_text("cancel requested")
    expect(page.get_by_text("A source-linked scientific finding")).not_to_be_visible()
    expect(page.get_by_text("provenance", exact=True)).not_to_be_visible()
    expect(page.get_by_role("link", name="Download research package")).not_to_be_visible()
    page.close()


def test_running_review_shows_actual_activity_and_can_return_to_new_question(
    live_browser_url, chromium_browser
):
    page = chromium_browser.new_page(viewport={"width": 390, "height": 844})
    run = {
        "id": "progress-run",
        "project_id": "development-project",
        "question": "Annual burned area",
        "status": "running",
        "created_at": "2026-10-09T10:00:00Z",
        "progress": {
            "stage": "acquiring",
            "message": "Checking dataset 2: EFFIS",
            "started_at": "2026-10-09T10:00:00Z",
            "updated_at": "2026-10-09T10:00:05Z",
            "counters": {"full_texts_acquired": 3},
            "events": [
                {"at": "2026-10-09T10:00:01Z", "message": "Searching official datasets"},
                {"at": "2026-10-09T10:00:05Z", "message": "Checking dataset 2: EFFIS"},
            ],
        },
    }
    page.route("**/runs", lambda route: route.fulfill(status=201, json=run))
    page.route("**/runs/progress-run", lambda route: route.fulfill(json=run))
    try:
        _login(page, live_browser_url)
        page.get_by_label("Research question").fill("Annual burned area")
        page.get_by_role("button", name="Review question").click()
        page.get_by_role("button", name="Approve and start review").click()
        expect(page.locator("#research")).to_be_hidden()
        expect(page.locator("#run-question")).to_have_text("Annual burned area")
        expect(page.locator("#run-progress")).to_have_text("Checking dataset 2: EFFIS")
        expect(page.locator("#run-activity")).to_contain_text("Searching official datasets")
        expect(page.locator("#run-timing")).to_contain_text("Elapsed")
        run["progress"]["message"] = "Executing Python extraction"
        expect(page.locator("#run-progress")).to_have_text(
            "Executing Python extraction", timeout=6000
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.get_by_role("button", name="New research question", exact=True).click()
        expect(page.get_by_label("Research question")).to_be_visible()
        expect(page.locator("#run-panel")).to_be_hidden()
    finally:
        page.close()


def test_failed_start_preserves_question_and_confirmation(live_browser_url, chromium_browser):
    page = chromium_browser.new_page()
    page.route(
        "**/runs", lambda route: route.fulfill(status=503, json={"detail": "Worker unavailable"})
    )
    try:
        _login(page, live_browser_url)
        page.get_by_label("Research question").fill("Annual burned area")
        page.get_by_role("button", name="Review question").click()
        page.get_by_role("button", name="Approve and start review").click()
        expect(page.locator("#global-status")).to_have_text("Worker unavailable")
        expect(page.locator("#approval-status")).to_have_text("Worker unavailable")
        expect(page.get_by_label("Research question")).to_have_value("Annual burned area")
        expect(page.locator("#question-brief")).to_be_visible()
        expect(page.locator("#run-panel")).to_be_hidden()
    finally:
        page.close()


def test_progress_poll_recovers_after_network_failure(live_browser_url, chromium_browser):
    page = chromium_browser.new_page()
    run = {
        "id": "reconnecting",
        "project_id": "development-project",
        "question": "Annual population",
        "status": "running",
    }
    polls = []

    def poll(route):
        polls.append(True)
        if len(polls) == 1:
            route.abort()
        else:
            route.fulfill(
                json={**run, "progress": {"message": "Checking source definitions", "events": []}}
            )

    page.route("**/runs", lambda route: route.fulfill(status=201, json=run))
    page.route("**/runs/reconnecting", poll)
    try:
        _login(page, live_browser_url)
        page.get_by_label("Research question").fill("Annual population")
        page.get_by_role("button", name="Review question").click()
        page.get_by_role("button", name="Approve and start review").click()
        expect(page.locator("#run-connection")).to_contain_text(
            "Retrying automatically", timeout=5000
        )
        expect(page.locator("#run-progress")).to_have_text(
            "Checking source definitions", timeout=8000
        )
        expect(page.locator("#run-connection")).to_have_text("Status connection active.")
    finally:
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
        expect(page.locator("#run-status")).to_have_text("Processing complete")
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
