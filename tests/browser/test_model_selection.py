from dataclasses import replace

from playwright.sync_api import expect


def test_user_selects_model_and_changing_it_invalidates_brief(
    live_browser_url, chromium_browser, monkeypatch
):
    from sci_search import question_interpretation

    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_MODELS", '{"openai":["model-a","model-b"]}')

    def interpretation(question, plan, analyzer):
        return replace(
            question_interpretation._deterministic_brief(question, plan),
            provider=analyzer.provider.name,
            model=analyzer.model,
            method="openai_structured_question_interpretation_v1",
        )

    monkeypatch.setattr(question_interpretation, "_model_interpretation", interpretation)
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


def test_failed_model_interpretation_disables_approval(
    live_browser_url, chromium_browser, monkeypatch
):
    from sci_search import question_interpretation

    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_MODELS", '{"openai":["model-a"]}')

    def unavailable(*args):
        raise ValueError("offline test")

    monkeypatch.setattr(question_interpretation, "_model_interpretation", unavailable)
    page = chromium_browser.new_page()
    try:
        page.goto(live_browser_url)
        page.get_by_role("button", name="Continue with development account").click()
        models = page.get_by_label("Analysis model", exact=True)
        expect(models).to_be_enabled()
        models.select_option(label="OpenAI · model-a")
        page.get_by_label("Research question", exact=True).fill(
            "How does salinity affect tomato germination?"
        )
        page.get_by_role("button", name="Review question", exact=True).click()
        expect(page.locator("#question-brief")).to_be_visible()
        expect(page.locator("#question-brief")).to_contain_text("could not be validated")
        expect(page.get_by_role("button", name="Approve and start review")).to_be_disabled()
        expect(page.locator("#run-panel")).not_to_be_visible()
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
        # Project initialization clears any previous dashboard. Wait until its
        # history has loaded before exercising the renderer directly.
        expect(page.get_by_role("link", name="Saved evidence review", exact=True)).to_be_visible()
        snapshot = build_dashboard(
            {
                "question": "Question",
                "answer_adequacy": {"can_answer_overall_question": False},
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
        render = "async snapshot => { const {renderDashboard} = await import(new URL('./dashboard.js', document.querySelector('script[type=module]').src).href); renderDashboard(snapshot); }"
        page.evaluate(render, snapshot)
        expect(page.locator("#dashboard-model")).to_contain_text(
            "Analysis model: OpenAI · chosen-model"
        )
        expect(page.locator("#dashboard-answer")).to_contain_text(
            "Processing complete · Insufficient evidence"
        )
        expect(page.locator("#dashboard-answer")).to_contain_text("expert scientific validation")
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


def test_model_chooser_ignores_pre_upgrade_cached_module(live_browser_url, chromium_browser):
    page = chromium_browser.new_page()
    try:
        # Model the cached pre-upgrade module under its original, unversioned URL.
        page.route(
            "**/static/runs.js",
            lambda route: route.fulfill(
                content_type="text/javascript",
                body="""
            export function initializeRuns() {}
            export function configureRunPermissions() {}
            export function currentRun() { return null; }
            export function selectRun() {}
        """,
            ),
        )
        page.goto(live_browser_url)
        page.get_by_role("button", name="Continue with development account").click()
        expect(page.get_by_label("Analysis model", exact=True)).to_be_enabled()
        expect(page.get_by_label("Analysis model", exact=True)).not_to_contain_text(
            "Loading models"
        )
    finally:
        page.close()


def test_new_search_defaults_to_sol_and_deep_but_user_can_change(
    live_browser_url, chromium_browser, monkeypatch
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6-luna")
    monkeypatch.delenv("SCI_SEARCH_ANALYSIS_MODELS", raising=False)
    page = chromium_browser.new_page()
    try:
        page.goto(live_browser_url)
        page.get_by_role("button", name="Continue with development account").click()
        models = page.get_by_label("Analysis model", exact=True)
        depth = page.get_by_label("Review depth", exact=True)
        expect(models).to_have_value('{"provider":"openai","model":"gpt-6-sol"}')
        expect(depth).to_have_value("deep")
        models.select_option(label="OpenAI · gpt-6-luna")
        depth.select_option("focused")
        expect(models).to_have_value('{"provider":"openai","model":"gpt-6-luna"}')
        expect(depth).to_have_value("focused")
    finally:
        page.close()


def test_codex_default_interpretation_and_run_keep_provider(
    live_browser_url, chromium_browser, monkeypatch
):
    from sci_search import codex_provider, question_interpretation

    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_PROVIDER", "codex")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    monkeypatch.setattr(codex_provider, "available", lambda: True)

    def interpretation(question, plan, analyzer):
        return replace(
            question_interpretation._deterministic_brief(question, plan),
            provider=analyzer.provider.name,
            model=analyzer.model,
            method="codex_structured_question_interpretation_v1",
        )

    monkeypatch.setattr(question_interpretation, "_model_interpretation", interpretation)
    page = chromium_browser.new_page()
    try:
        page.goto(live_browser_url)
        page.get_by_role("button", name="Continue with development account").click()
        models = page.get_by_label("Analysis model", exact=True)
        expect(models).to_have_value('{"provider":"codex","model":"gpt-6-sol"}')
        expect(models).to_contain_text("Codex (ChatGPT login)")
        page.get_by_label("Research question", exact=True).fill(
            "How does salinity affect tomato germination?"
        )
        page.get_by_role("button", name="Review question", exact=True).click()
        expect(page.locator("#brief-method")).to_contain_text("Codex (ChatGPT login)")
        with page.expect_request("**/runs") as started:
            page.get_by_role("button", name="Approve and start review").click()
        assert started.value.post_data_json["analysis_selection"] == {
            "provider": "codex",
            "model": "gpt-6-sol",
        }
        expect(page.locator("#run-model")).to_contain_text("Codex (ChatGPT login)")
    finally:
        page.close()


def test_unavailable_codex_default_requires_explicit_api_selection(
    live_browser_url, chromium_browser, monkeypatch
):
    from sci_search import codex_provider

    monkeypatch.setenv("SCI_SEARCH_ANALYSIS_PROVIDER", "codex")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    monkeypatch.setattr(codex_provider, "available", lambda: False)
    page = chromium_browser.new_page()
    try:
        page.goto(live_browser_url)
        page.get_by_role("button", name="Continue with development account").click()
        models = page.get_by_label("Analysis model", exact=True)
        review = page.get_by_role("button", name="Review question", exact=True)
        expect(models).to_be_enabled()
        expect(models).to_have_value('{"provider":"codex","model":"gpt-6-sol"}')
        expect(review).to_be_disabled()
        expect(page.locator("#analysis-model-help")).to_contain_text("Sign in")
        models.select_option(label="OpenAI · gpt-6-sol")
        expect(review).to_be_enabled()
    finally:
        page.close()
