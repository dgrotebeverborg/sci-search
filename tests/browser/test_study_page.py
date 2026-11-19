"""The study-plan page in a real browser, with a fake model."""

import socket
import threading
import time

import pytest
import uvicorn
from playwright.sync_api import Browser, expect

from sci_search.study.service import StudyService
from sci_search.study.store import StudyStore
from sci_search.study.web import create_app
from tests.study.conftest import SCAN, make_plan
from tests.study.test_service import FakeAnalyzer


@pytest.fixture
def study_url(tmp_path):
    reply = make_plan(definitions=[{"term": "Storage", "definition": "Energy and power."}])
    analyzer = FakeAnalyzer(make_plan(), reply)
    service = StudyService(
        StudyStore(tmp_path),
        analyzer_factory=lambda: analyzer,
        scan=lambda q, progress: dict(SCAN),
        extend=lambda s, terms, progress: s,
        background=False,
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(
        uvicorn.Config(create_app(service), log_level="warning", lifespan="off")
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    try:
        yield origin
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()


def test_plan_revision_marks_the_changed_section(study_url: str, chromium_browser: Browser):
    page = chromium_browser.new_page()
    page.goto(study_url)
    page.get_by_label("Research question").fill("How much storage?")
    page.get_by_role("button", name="Make study plan").click()
    expect(page.get_by_role("heading", name="Definitions")).to_be_visible()
    expect(page.get_by_role("button", name="Reopen")).to_be_hidden()
    expect(page.get_by_role("button", name="Restore this version")).to_be_hidden()
    expect(page.get_by_role("link", name="II3050 scenarios")).to_have_attribute(
        "href", "https://example.org/ii3050"
    )
    box = page.get_by_label("What should change in Definitions?")
    box.fill("Split energy and power")
    box.press("Enter")
    expect(page.locator("h2", has_text="Definitions").locator(".changed")).to_have_text("Changed")
    expect(page.locator("h2", has_text="Scope and assumptions").locator(".changed")).to_have_count(
        0
    )
    page.get_by_role("button", name="Approve plan").click()
    expect(page.get_by_text("This plan is approved. Reopen it to make changes.")).to_be_visible()
    expect(page.get_by_label("What should change in Definitions?")).to_have_count(0)
    page.close()


def test_points_about_the_question_can_be_dismissed(study_url: str, chromium_browser: Browser):
    page = chromium_browser.new_page()
    page.goto(study_url)
    page.get_by_label("Research question").fill("How much storage at 0, 50 and 100%?")
    page.get_by_role("button", name="Make study plan").click()
    section = page.locator("section.section", has=page.get_by_role("heading", name="Questions about the question"))
    expect(section).to_contain_text("The shares 0, 50 and 100% are arbitrary.")
    expect(section).to_contain_text("Alternative: Use 0-100% in steps of 10%.")
    expect(section.get_by_role("button", name="Adopt")).to_be_visible()
    section.get_by_role("button", name="Dismiss").click()
    expect(section).to_contain_text("Dismissed")
    expect(section.get_by_role("button", name="Dismiss")).to_have_count(0)
    page.close()
