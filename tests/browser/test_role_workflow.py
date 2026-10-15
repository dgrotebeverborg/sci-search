from __future__ import annotations

from io import BytesIO

from playwright.sync_api import Browser, expect
from pypdf import PdfWriter


def _login_as(page, origin: str, user_id: str) -> None:
    response = page.request.post(f"{origin}/auth/development?user_id={user_id}")
    assert response.ok
    page.goto(f"{origin}/app?project={user_id}-project&run=browser-completed")


def test_role_controls_and_cross_project_api_denial(
    live_browser_url: str,
    chromium_browser: Browser,
) -> None:
    reviewer = chromium_browser.new_page()
    _login_as(reviewer, live_browser_url, "reviewer")
    expect(reviewer.get_by_role("button", name="Accept evidence")).to_be_visible()
    expect(reviewer.get_by_role("button", name="Add authorized full text")).to_be_hidden()
    expect(
        reviewer.get_by_role("button", name="Review question", include_hidden=True)
    ).to_be_disabled()

    viewer = chromium_browser.new_page()
    _login_as(viewer, live_browser_url, "viewer")
    expect(viewer.get_by_role("button", name="Accept evidence")).to_have_count(0)
    expect(
        viewer.get_by_role("button", name="Review question", include_hidden=True)
    ).to_be_disabled()
    denied = viewer.evaluate(
        """async () => {
          const response = await fetch('/api/v1/projects/reviewer-project/evidence');
          return {status: response.status, body: await response.json()};
        }"""
    )
    assert denied == {"status": 404, "body": {"detail": "resource not found"}}

    editor = chromium_browser.new_page()
    _login_as(editor, live_browser_url, "editor")
    expect(editor.get_by_role("button", name="Add authorized full text")).to_be_visible()
    editor.get_by_role("button", name="New research question", exact=True).click()
    expect(editor.get_by_role("button", name="Review question")).to_be_enabled()
    editor.get_by_label("Research question").fill("What evidence is available?")
    editor.get_by_role("button", name="Review question").click()
    editor.get_by_role("button", name="Approve and start review").click()
    expect(editor.locator("#run-status")).to_have_text("queued")
    editor.get_by_label("Publication or candidate identifier").fill("candidate-1")
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(output)
    editor.locator("#authorized-document").set_input_files(
        {"name": "paper.pdf", "mimeType": "application/pdf", "buffer": output.getvalue()}
    )
    expect(editor.get_by_text("Authorized full text added to this project.")).to_be_visible()
    reviewer.close()
    viewer.close()
    editor.close()


def test_simultaneous_review_conflict_is_visible_and_recoverable(
    live_browser_url: str,
    chromium_browser: Browser,
) -> None:
    first = chromium_browser.new_page()
    second = chromium_browser.new_page()
    _login_as(first, live_browser_url, "reviewer")
    _login_as(second, live_browser_url, "reviewer")
    # Both sessions must have loaded the original revision before either edits it.
    # Navigation alone does not wait for the asynchronous evidence request.
    expect(first.get_by_text("version 1", exact=True)).to_be_visible()
    expect(second.get_by_text("version 1", exact=True)).to_be_visible()

    first.get_by_role("button", name="Accept evidence").click()
    expect(first.get_by_text("Evidence review saved.")).to_be_visible()
    second.get_by_role("button", name="Reject evidence").click()
    expect(second.get_by_text("This evidence changed in another session")).to_be_visible()
    expect(second.get_by_text("version 2")).to_be_visible()
    first.close()
    second.close()


def test_rejected_evidence_disappears_and_stays_hidden_after_reload(
    live_browser_url: str,
    chromium_browser: Browser,
) -> None:
    page = chromium_browser.new_page()
    try:
        _login_as(page, live_browser_url, "reviewer")
        page.get_by_role("button", name="Reject evidence").click()
        expect(page.locator(".evidence-card")).to_have_count(0)
        expect(page.locator("#review-status")).to_contain_text("rejected")
        page.reload()
        expect(page.get_by_role("button", name="Sign out")).to_be_enabled()
        expect(page.get_by_text("Rejected items are hidden.", exact=False)).to_be_visible()
        expect(page.locator(".evidence-card")).to_have_count(0)
        records = page.request.get(
            f"{live_browser_url}/api/v1/projects/reviewer-project/evidence"
        ).json()["items"]
        assert records[0]["review_decision"] == "rejected"
    finally:
        page.close()
