"""Choosing a version of the question and adjusting its details by clicking."""

from playwright.sync_api import expect

from sci_search.question_choices import option_briefs
from tests.test_question_choices import BASE, CLOSEST_OPTION, DATA_OPTION, QUESTION


def interpretation(**extra):
    return {
        **BASE,
        "options": option_briefs(QUESTION, BASE, [CLOSEST_OPTION, DATA_OPTION]),
        "clarification_options": [],
        **extra,
    }


def open_question(page, url, responses):
    requests = []

    def interpret(route):
        requests.append(route.request.post_data_json)
        route.fulfill(json=responses[min(len(requests), len(responses)) - 1])

    page.route("**/runs/interpret", interpret)
    page.goto(url)
    page.get_by_role("button", name="Continue with development account").click()
    page.get_by_label("Research question", exact=True).fill(QUESTION)
    page.get_by_role("button", name="Review question", exact=True).click()
    expect(page.locator("#question-brief")).to_be_visible()
    return requests


def test_versions_and_details_are_chosen_by_clicking(live_browser_url, chromium_browser):
    page = chromium_browser.new_page()
    try:
        requests = open_question(page, live_browser_url, [interpretation(), interpretation()])
        cards = page.locator(".choice-card")
        expect(cards).to_have_count(2)
        expect(cards.first).to_contain_text("Closest to your question")
        expect(cards.first).to_have_attribute("aria-pressed", "true")
        # Every approach can be chosen; data without measurements explains what is missing.
        approach = page.locator(".choice-row[data-detail='approach']")
        for name in ("Literature review", "Find and analyse datasets", "Datasets and literature"):
            expect(approach.get_by_role("button", name=name, exact=True)).to_be_enabled()
        approach.get_by_role("button", name="Find and analyse datasets", exact=True).click()
        expect(approach.locator(".choice-error")).to_contain_text(
            "Choose or type at least one measurement"
        )

        # The data version: its measurements and a geography chip from the alternatives.
        cards.nth(1).click()
        expect(page.locator("#brief-question")).to_contain_text("projected to change until 2100")
        geography = page.locator(".choice-row[data-detail='geography']")
        geography.get_by_role("button", name="Indus basin", exact=True).click()
        expect(geography.locator(".choice-current")).to_have_text("Indus basin")

        # The last option is typing it yourself.
        measurements = page.locator(".choice-row[data-detail='measurements']")
        measurements.get_by_role("button", name="Edit…", exact=True).click()
        page.get_by_label("Measurements, separated by commas").fill("glacier runoff, glacier mass")
        measurements.get_by_role("button", name="Apply", exact=True).click()
        expect(measurements.locator(".choice-current")).to_have_text("glacier runoff, glacier mass")

        # Starting sends the chosen, adjusted brief without its choices.
        with page.expect_request("**/api/v1/projects/*/runs") as started:
            page.get_by_role("button", name="Approve and start review").click()
        sent = started.value.post_data_json["question_brief"]
        assert "options" not in sent and "clarification_options" not in sent
        assert sent["research_plan"]["geography_terms"] == ["Indus basin"]
        assert sent["data_research"]["measurements"] == ["glacier runoff", "glacier mass"]
        assert sent["data_research"]["end_year"] == 2100
        assert sent["original_question"] == QUESTION
        assert len(requests) == 1
    finally:
        page.close()


def test_steering_asks_for_new_versions(live_browser_url, chromium_browser):
    page = chromium_browser.new_page()
    try:
        requests = open_question(page, live_browser_url, [interpretation(), interpretation()])
        page.locator(".choice-steer").get_by_role("button", name="More data", exact=True).click()
        expect(page.locator(".choice-card")).to_have_count(2)
        assert requests[1]["steer"]["direction"] == "more_data"
        assert requests[1]["steer"]["option"]["title"] == CLOSEST_OPTION["title"]
        assert requests[1]["question"] == QUESTION
    finally:
        page.close()


def test_a_clarification_is_answered_by_clicking(live_browser_url, chromium_browser):
    unclear = {
        **BASE,
        "ambiguity": "material",
        "clarification_question": "Which rivers do you mean?",
        "options": [],
        "clarification_options": ["Indus", "Ganges and Brahmaputra"],
    }
    page = chromium_browser.new_page()
    try:
        requests = open_question(page, live_browser_url, [unclear, interpretation()])
        expect(page.get_by_role("button", name="Approve and start review")).to_be_disabled()
        clarify = page.locator(".choice-clarify")
        expect(clarify).to_contain_text("Which rivers do you mean?")
        clarify.get_by_role("button", name="Indus", exact=True).click()
        expect(page.locator(".choice-card")).to_have_count(2)
        assert requests[1]["clarification"] == "Indus"
        expect(page.get_by_role("button", name="Approve and start review")).to_be_enabled()
    finally:
        page.close()
