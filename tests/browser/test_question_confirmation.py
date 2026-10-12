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


def test_confirmation_shows_executable_evidence_filters_and_screening_exclusions(
    live_browser_url, chromium_browser
):
    page = chromium_browser.new_page()
    question = "How does salinity affect tomato germination in Europe?"
    brief = {
        "original_question": question,
        "interpreted_question": question,
        "objective": "Assess the relationship between salinity and tomato germination.",
        "evidence_scope": ["Controlled experiments"],
        "assumptions": [],
        "exclusions": ["Studies of other crops"],
        "research_plan": {
            "intent": "relationship",
            "subject_terms": ["tomato germination"],
            "driver_terms": ["salinity"],
            "geography_terms": ["Europe"],
            "evidence_preferences": ["empirical", "model_or_assumption"],
            "exclusion_terms": ["wheat", "rice"],
        },
    }
    try:
        page.route("**/runs/interpret", lambda route: route.fulfill(json=brief))
        page.goto(live_browser_url)
        page.get_by_role("button", name="Continue with development account").click()
        expect(page.get_by_role("link", name="Saved evidence review", exact=True)).to_be_visible()
        page.get_by_label("Research question", exact=True).fill(question)
        page.get_by_role("button", name="Review question", exact=True).click()
        expect(page.locator("#question-brief")).to_be_visible()
        details = page.locator("#brief-details")
        filters = details.get_by_role("heading", name="Automatic evidence filters", exact=True)
        expect(filters).to_be_visible()
        expect(
            filters.locator("xpath=following-sibling::ul[1]").get_by_role("listitem")
        ).to_have_text(["empirical", "model or assumption"])
        exclusions = details.get_by_role(
            "heading", name="Excluded terms used in screening", exact=True
        )
        expect(exclusions).to_be_visible()
        expect(
            exclusions.locator("xpath=following-sibling::ul[1]").get_by_role("listitem")
        ).to_have_text(["wheat", "rice"])
        expect(details.get_by_text("Studies of other crops", exact=True)).to_be_visible()
        expect(
            page.get_by_role("button", name="Approve and start review", exact=True)
        ).to_be_enabled()
        expect(page.locator("#run-panel")).not_to_be_visible()
    finally:
        page.close()


def test_relationship_confirmation_separates_roles_and_requires_resolving_missing_factor(
    live_browser_url, chromium_browser
):
    page = chromium_browser.new_page()
    question = "Is neighborhood green space associated with a lower risk of type 2 diabetes?"
    structure = dict(
        intent="relationship",
        relationship_type="association",
        outcome_measure_terms=["risk"],
        subject_terms=["type 2 diabetes"],
        driver_terms=["neighborhood green space"],
        geography_terms=[],
        population_terms=[],
        time_terms=[],
        evidence_preferences=[],
        exclusion_terms=[],
    )
    brief = dict(
        original_question=question,
        interpreted_question=question,
        objective="Evaluate the association.",
        ambiguity="clear",
        research_plan=structure,
        evidence_scope=[
            "Studies comparing diabetes outcomes across levels of neighborhood green space, including no association."
        ],
    )
    try:
        page.route("**/runs/interpret", lambda route: route.fulfill(json=brief))
        page.goto(live_browser_url)
        page.get_by_role("button", name="Continue with development account").click()
        page.get_by_label("Research question").fill(question)
        page.get_by_role("button", name="Review question", exact=True).click()
        details = page.locator("#brief-details")
        for label, value in [
            ("Factor being studied", "neighborhood green space"),
            ("Outcome being studied", "type 2 diabetes (risk)"),
            ("Location", "Not specified — no restriction"),
            ("People or study subjects", "Not specified — no restriction"),
            ("Time period", "Not specified — no restriction"),
        ]:
            expect(
                details.get_by_role("heading", name=label, exact=True).locator(
                    "xpath=following-sibling::ul[1]"
                )
            ).to_have_text(value)
        expect(details.get_by_role("heading", name="Subject or outcome")).to_have_count(0)
        expect(details).to_contain_text("does not establish cause and effect")
        expect(page.get_by_role("button", name="Approve and start review")).to_be_enabled()
        structure["driver_terms"] = []
        page.get_by_role("button", name="Review question", exact=True).click()
        expect(details).to_contain_text("Not identified — clarify the question")
        expect(page.get_by_role("button", name="Approve and start review")).to_be_disabled()
    finally:
        page.close()


def test_data_question_shows_why_approval_is_blocked(live_browser_url, chromium_browser):
    page = chromium_browser.new_page()
    question = "How has burned area changed in Portugal?"
    brief = {
        "original_question": question, "interpreted_question": question,
        "objective": "Compare burned area", "ambiguity": "material",
        "clarification_question": "Which years should be compared?",
        "data_research": {"adapter": "discovered_data_v1", "route": "data",
                          "measurements": ["burned area"], "geography": "Portugal",
                          "rationale": "Official annual observations"},
    }
    try:
        page.route("**/runs/interpret", lambda route: route.fulfill(json=brief))
        page.goto(live_browser_url)
        page.get_by_role("button", name="Continue with development account").click()
        page.get_by_label("Research question").fill(question)
        page.get_by_role("button", name="Review question", exact=True).click()
        expect(page.locator("#question-brief")).to_contain_text("Which years should be compared?")
        expect(page.get_by_role("button", name="Approve and start review")).to_be_disabled()
    finally:
        page.close()
