from playwright.sync_api import expect


def test_user_selects_model_and_changing_it_invalidates_brief(
    live_browser_url, chromium_browser, monkeypatch
):
    from sci_search import question_interpretation

    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_MODELS", '{"openai":["model-a","model-b"]}')

    def unavailable(*args):
        raise ValueError("offline test")

    monkeypatch.setattr(question_interpretation, "_model_interpretation", unavailable)
    page = chromium_browser.new_page()
    try:
        page.goto(live_browser_url)
        page.get_by_role("button", name="Continue with development account").click()
        models = page.get_by_label("Analysis model", exact=True)
        expect(models).to_be_enabled()
        models.select_option(label="OpenAI · model-b")
        page.screenshot(path="/tmp/sci-search-model-chooser.png", full_page=True)
        page.get_by_label("Research question", exact=True).fill(
            "How does salinity affect tomato germination?"
        )
        with page.expect_request("**/runs/interpret") as request:
            page.get_by_role("button", name="Review question", exact=True).click()
        assert request.value.post_data_json["analysis_selection"] == {
            "provider": "openai",
            "model": "model-b",
        }
        expect(page.locator("#question-brief")).to_be_visible()
        models.select_option(label="OpenAI · model-a")
        expect(page.locator("#question-brief")).not_to_be_visible()
        page.get_by_role("button", name="Review question", exact=True).click()
        expect(page.locator("#question-brief")).to_be_visible()
        with page.expect_request("**/runs") as started:
            page.get_by_role("button", name="Approve and start review").click()
        assert started.value.post_data_json["analysis_selection"] == {
            "provider": "openai",
            "model": "model-a",
        }
        expect(page.locator("#run-model")).to_contain_text("OpenAI · model-a")
    finally:
        page.close()


def test_dashboard_reports_coverage_limited_ai_and_legacy_fallback(
    live_browser_url, chromium_browser
):
    from sci_search.dashboard import build_dashboard

    page = chromium_browser.new_page()
    try:
        page.goto(live_browser_url)
        page.get_by_role("button", name="Continue with development account").click()
        snapshot = build_dashboard(
            {
                "question": "Question",
                "ai_analysis": {
                    "status": "coverage_limited",
                    "provider": "openai",
                    "model": "chosen-model",
                    "method": "openai_structured_evidence_analysis_v1",
                },
            },
            run_id="run",
            revision=1,
        )
        render = "async snapshot => { const {renderDashboard} = await import('/static/dashboard.js'); renderDashboard(snapshot); }"
        page.evaluate(render, snapshot)
        expect(page.locator("#dashboard-model")).to_contain_text(
            "Analysis model: OpenAI · chosen-model"
        )
        snapshot["analysis"]["fallback_reason"] = "No evidence"
        snapshot["analysis"]["method"] = "deterministic_extractive_fallback"
        page.evaluate(render, snapshot)
        expect(page.locator("#dashboard-model")).to_contain_text("Extractive analysis")
        del snapshot["analysis"]
        next(b for b in snapshot["blocks"] if b["id"] == "methods")["data"]["methodology"] = {
            "model": {
                "provider": "openai",
                "name": "attempted-model",
                "method": "deterministic_extractive_fallback",
            }
        }
        page.evaluate(render, snapshot)
        expect(page.locator("#dashboard-model")).to_contain_text("Extractive analysis")
    finally:
        page.close()
