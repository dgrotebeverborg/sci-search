from playwright.sync_api import Browser, expect

from sci_search.dashboard import build_dashboard


def test_saved_dashboard_history_refresh_and_feedback(
    live_browser_url: str, chromium_browser: Browser
):
    page = chromium_browser.new_page()
    sequence = 0
    revision = 1
    submissions = []
    snapshots = {}
    for name in ("A", "B"):
        snapshots[name] = build_dashboard(
            {
                "question": f"Question {name}",
                "analysis_selection": {"provider": "openai", "model": "chosen-model"},
                "ai_analysis": {"status": "complete", "provider": "openai", "model": "chosen-model"}
                if name == "A"
                else {"status": "fallback", "fallback_reason": "Provider unavailable"},
                "evidence": [
                    {
                        "id": f"e{name}",
                        "publication_id": "p1",
                        "passage": f"Exact passage {name}",
                        "start_offset": 1,
                        "end_offset": 16,
                    }
                ],
                "literature_review_report": {
                    "executive_summary": {"text": f"Review {name}", "evidence_ids": [f"e{name}"]},
                    "references": [{"number": 1, "publication_id": "p1", "title": "Paper one"}],
                },
                "study_matrix": {
                    "studies": [
                        {
                            "publication_id": "p1",
                            "title": "Paper one",
                            "screening": {"decision": "included"},
                        }
                    ]
                },
            },
            run_id=name,
            revision=1,
        )

    def api(route):
        nonlocal sequence, revision
        url = route.request.url
        if route.request.method == "POST":
            submissions.append(route.request.post_data_json)
            sequence += 1
            revision += 1
            route.fulfill(json={"feedback_sequence": sequence, "rebuild_status": "queued"})
        elif "/dashboard" in url:
            name = url.split("/runs/")[1].split("/")[0]
            route.fulfill(
                json={
                    **snapshots[name],
                    "revision": revision if name == "A" else 1,
                    "feedback_sequence": sequence,
                    "role": "owner",
                    "rebuild_status": "idle",
                }
            )
        elif "/revisions" in url:
            route.fulfill(json={"items": [{"revision": n} for n in range(1, revision + 1)]})
        else:
            route.fulfill(
                json={
                    "items": [
                        {
                            "id": n,
                            "question": f"Question {n}",
                            "status": "completed",
                            "project_id": "development-project",
                        }
                        for n in ("B", "A")
                    ],
                    "next_cursor": None,
                }
            )

    snapshots["A"]["artifacts"] = [
        {
            "filename": "research-package.zip",
            "content_type": "application/zip",
            "url": "/api/v1/projects/development-project/exports/bundle-A",
        }
    ]
    page.route(
        "**/exports/bundle-A",
        lambda route: route.fulfill(
            body=b"test saved archive",
            content_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="research-package.zip"'},
        ),
    )
    page.route("**/api/v1/projects/*/runs**", api)
    page.goto(live_browser_url)
    page.get_by_role("button", name="Continue with development account").click()
    page.get_by_role("link", name="Question A", exact=True).click()
    expect(page.locator("[data-dashboard-block]")).to_have_count(13)
    with page.expect_download() as download:
        page.get_by_role("link", name="Download all", exact=True).click()
    assert download.value.suggested_filename == "research-package.zip"
    expect(page.locator("#dashboard-model")).to_have_text("Analysis model: OpenAI · chosen-model")
    expect(page.locator("#dashboard-model")).to_be_visible()
    page.screenshot(path="/tmp/sci-search-model-dashboard.png", full_page=True)
    before = page.locator("[data-dashboard-block]").all_text_contents()
    page.reload()
    expect(page.locator("[data-dashboard-block]")).to_have_count(13)
    assert page.locator("[data-dashboard-block]").all_text_contents() == before
    page.get_by_role("link", name="Question B", exact=True).click()
    expect(page.locator("#dashboard-question")).to_have_text("Question B")
    expect(page.locator("#dashboard-model")).to_contain_text(
        "Extractive analysis · selected: OpenAI · chosen-model"
    )
    expect(page.get_by_role("link", name="Download all", exact=True)).to_have_count(0)
    page.go_back()
    expect(page.locator("#dashboard-question")).to_have_text("Question A")
    page.get_by_role("link", name="Studies & evidence", exact=True).click()
    page.get_by_role("button", name="Exclude article", exact=True).click()
    page.get_by_label("Reason", exact=True).fill("Different study population")
    page.get_by_role("button", name="Save decision", exact=True).click()
    expect(page.locator("[data-dashboard-revision='2']")).to_be_visible()
    assert submissions == [
        {
            "decision": "exclude",
            "reason": "Different study population",
            "expected_sequence": 0,
            "reviewed_revision": 1,
            "idempotency_key": submissions[0]["idempotency_key"],
        }
    ]
    page.close()


def test_landscape_filters_and_historical_permissions(
    live_browser_url: str, chromium_browser: Browser
):
    page = chromium_browser.new_page(viewport={"width": 390, "height": 844})
    snapshot = build_dashboard(
        {
            "question": "Landscape question",
            "research_landscape": {
                "population_definition": "discovered",
                "publication_timeline": [
                    {"year": 2024, "publications": 1},
                    {"year": 2025, "publications": 1},
                ],
            },
            "study_matrix": {
                "studies": [
                    {
                        "publication_id": "p1",
                        "title": "Included paper",
                        "year": 2024,
                        "screening": {"decision": "included"},
                    },
                    {
                        "publication_id": "p2",
                        "title": "Excluded paper",
                        "year": 2025,
                        "screening": {"decision": "excluded"},
                    },
                ]
            },
        },
        run_id="A",
        revision=1,
    )
    page.route("**/runs?*", lambda route: route.fulfill(json={"items": [], "next_cursor": None}))
    page.route(
        "**/runs/A/dashboard**",
        lambda route: route.fulfill(json={**snapshot, "role": "owner", "current_revision": 2}),
    )
    page.route(
        "**/runs/A/revisions",
        lambda route: route.fulfill(json={"items": [{"revision": 1}, {"revision": 2}]}),
    )
    page.request.post(f"{live_browser_url}/auth/development")
    page.goto(f"{live_browser_url}/app?project=development-project&run=A&revision=1")
    expect(page.locator("#dashboard-question")).to_have_text("Landscape question")
    page.get_by_role("link", name="Studies & evidence", exact=True).click()
    expect(page.get_by_role("button", name="Exclude article", exact=True).first).to_be_disabled()
    page.get_by_role("link", name="Research landscape", exact=True).click()
    landscape = page.locator("#dashboard-landscape")
    expect(landscape.get_by_role("cell", name="Excluded paper", exact=True)).to_be_visible()
    landscape.get_by_role("button", name="2024: 1 publications", exact=True).click()
    expect(landscape.get_by_role("cell", name="Excluded paper", exact=True)).to_have_count(0)
    landscape.get_by_role("button", name="Show all years", exact=True).click()
    page.get_by_label("Search landscape studies").fill("Excluded")
    expect(landscape.get_by_role("cell", name="Included paper", exact=True)).to_have_count(0)
    page.get_by_label("Search landscape studies").fill("")
    page.get_by_label("Landscape population").select_option("included")
    expect(landscape.get_by_role("cell", name="Excluded paper", exact=True)).to_have_count(0)
    expect(landscape.get_by_role("cell", name="Included paper", exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.screenshot(path="/tmp/sci-search-dashboard-mobile.png", full_page=True)
    page.evaluate(
        "document.querySelector('#dashboard-panel').scrollIntoView({block: 'start', behavior: 'instant'})"
    )
    page.screenshot(path="/tmp/sci-search-dashboard-mobile-viewport.png")
    page.close()


def test_feedback_conflict_preserves_dashboard(live_browser_url: str, chromium_browser: Browser):
    page = chromium_browser.new_page()
    snapshot = build_dashboard(
        {
            "question": "Conflict question",
            "study_matrix": {"studies": [{"publication_id": "p1", "title": "Paper"}]},
        },
        run_id="A",
        revision=1,
    )
    page.route("**/runs?*", lambda route: route.fulfill(json={"items": [], "next_cursor": None}))
    page.route(
        "**/runs/A/dashboard",
        lambda route: route.fulfill(json={**snapshot, "role": "owner", "feedback_sequence": 2}),
    )
    page.route(
        "**/runs/A/revisions", lambda route: route.fulfill(json={"items": [{"revision": 1}]})
    )
    page.route(
        "**/articles/p1/feedback",
        lambda route: route.fulfill(status=409, json={"detail": "stale feedback sequence"}),
    )
    page.request.post(f"{live_browser_url}/auth/development")
    page.goto(f"{live_browser_url}/app?project=development-project&run=A")
    page.get_by_role("link", name="Studies & evidence", exact=True).click()
    page.get_by_role("button", name="Reset article decision", exact=True).click()
    page.get_by_role("button", name="Save decision", exact=True).click()
    expect(page.get_by_text("Another decision was saved.", exact=False)).to_be_visible()
    expect(page.locator("[data-dashboard-revision='1']")).to_be_visible()
    expect(page.get_by_role("button", name="Save decision", exact=True)).to_be_enabled()
    page.close()


def test_unauthenticated_dashboard_link_restores_after_login(
    live_browser_url: str, chromium_browser: Browser
):
    page = chromium_browser.new_page()
    snapshot = build_dashboard({"question": "Deep linked question"}, run_id="A", revision=1)
    page.route("**/runs?*", lambda route: route.fulfill(json={"items": [], "next_cursor": None}))
    page.route("**/runs/A/dashboard", lambda route: route.fulfill(json=snapshot))
    page.route(
        "**/runs/A/revisions", lambda route: route.fulfill(json={"items": [{"revision": 1}]})
    )
    page.goto(f"{live_browser_url}/app?project=development-project&run=A")
    page.get_by_role("button", name="Continue with development account").click()
    expect(page.locator("#dashboard-question")).to_have_text("Deep linked question")
    expect(page).to_have_url(f"{live_browser_url}/app?project=development-project&run=A")
    page.close()


def test_unrebuildable_saved_sources_disable_article_changes(
    live_browser_url: str, chromium_browser: Browser
):
    page = chromium_browser.new_page()
    snapshot = build_dashboard(
        {
            "question": "Recovered question",
            "study_matrix": {"studies": [{"publication_id": "p", "title": "Recovered study"}]},
        },
        run_id="A",
        revision=1,
    )
    page.route("**/runs?*", lambda route: route.fulfill(json={"items": [], "next_cursor": None}))
    page.route(
        "**/runs/A/dashboard",
        lambda route: route.fulfill(json={**snapshot, "role": "owner", "rebuild_available": False}),
    )
    page.route(
        "**/runs/A/revisions", lambda route: route.fulfill(json={"items": [{"revision": 1}]})
    )
    page.request.post(f"{live_browser_url}/auth/development")
    page.goto(f"{live_browser_url}/app?project=development-project&run=A")
    page.get_by_role("link", name="Studies & evidence", exact=True).click()
    expect(page.get_by_role("button", name="Exclude article", exact=True)).to_be_disabled()
    expect(
        page.get_by_text("The retained source ledger is unavailable", exact=False)
    ).to_be_visible()
    page.close()


def test_pending_direct_link_restores_run_status(live_browser_url: str, chromium_browser: Browser):
    page = chromium_browser.new_page()
    page.route("**/runs?*", lambda route: route.fulfill(json={"items": [], "next_cursor": None}))
    page.route(
        "**/runs/A/dashboard", lambda route: route.fulfill(status=404, json={"detail": "not found"})
    )
    page.route(
        "**/runs/A",
        lambda route: route.fulfill(
            json={
                "id": "A",
                "project_id": "development-project",
                "question": "Pending saved question",
                "status": "queued",
            }
        ),
    )
    page.request.post(f"{live_browser_url}/auth/development")
    page.goto(f"{live_browser_url}/app?project=development-project&run=A")
    expect(page.locator("#run-question")).to_have_text("Pending saved question")
    expect(page.locator("#run-status")).to_have_text("queued")
    page.close()


def test_history_pagination_and_delayed_selection_cannot_replace_current(
    live_browser_url: str, chromium_browser: Browser
):
    page = chromium_browser.new_page()
    delayed = []

    def history(route):
        second = "cursor=" in route.request.url
        name = "B" if second else "A"
        route.fulfill(
            json={
                "items": [
                    {
                        "id": name,
                        "question": f"Question {name}",
                        "status": "completed",
                        "project_id": "development-project",
                    }
                ],
                "next_cursor": None if second else "page-2",
            }
        )

    def dashboard(route):
        name = route.request.url.split("/runs/")[1].split("/")[0]
        if name == "A":
            delayed.append(route)
        else:
            route.fulfill(json=build_dashboard({"question": "Question B"}, run_id="B", revision=1))

    page.route("**/runs?*", history)
    page.route("**/runs/*/dashboard", dashboard)
    page.route(
        "**/runs/*/revisions", lambda route: route.fulfill(json={"items": [{"revision": 1}]})
    )
    page.request.post(f"{live_browser_url}/auth/development")
    page.goto(f"{live_browser_url}/app")
    page.get_by_role("button", name="Load more searches", exact=True).click()
    page.get_by_role("link", name="Question A", exact=True).click()
    page.get_by_role("link", name="Question B", exact=True).click()
    expect(page.locator("#dashboard-question")).to_have_text("Question B")
    for route in delayed:
        route.fulfill(json=build_dashboard({"question": "Question A"}, run_id="A", revision=1))
    expect(page.locator("#dashboard-question")).to_have_text("Question B")
    expect(page.locator("#run-question")).to_have_text("Question B")
    page.close()


def test_dashboard_leads_with_qualified_answer_and_groups_provenance(
    live_browser_url: str, chromium_browser: Browser
):
    page = chromium_browser.new_page()
    snapshot = build_dashboard(
        {
            "question": "Evidence question",
            "answer_summary": "Evidence is limited to one laboratory study.",
            "answer_adequacy": {
                "status": "partial",
                "decision": "The evidence does not support an overall answer.",
                "missing_requirements": ["Field evidence"],
                "checks": [{"required": True, "passed": False}],
            },
            "research_run": {
                "candidates": [{"id": "p1", "title": "Synthetic laboratory study"}],
                "run_directory": "/private/research/run-A",
            },
        },
        run_id="A",
        revision=1,
    )
    page.route("**/runs?*", lambda route: route.fulfill(json={"items": [], "next_cursor": None}))
    page.route("**/runs/A/dashboard", lambda route: route.fulfill(json=snapshot))
    page.route(
        "**/runs/A/revisions", lambda route: route.fulfill(json={"items": [{"revision": 1}]})
    )
    page.request.post(f"{live_browser_url}/auth/development")
    page.goto(f"{live_browser_url}/app?project=development-project&run=A")
    answer = page.locator("#dashboard-answer")
    expect(answer.locator(".answer-narrative p").first).to_have_text(
        "Evidence is limited to one laboratory study."
    )
    expect(
        answer.get_by_text("The evidence does not support an overall answer.", exact=True)
    ).to_be_visible()
    expect(answer.get_by_text("Field evidence", exact=True)).to_be_visible()
    page.get_by_role("link", name="Methods & exports", exact=True).click()
    page.locator("#dashboard-methods").get_by_text(
        "Search and screening record", exact=True
    ).click()
    expect(page.get_by_text("/private/research/run-A", exact=True)).to_have_count(0)
    page.close()


def test_saved_dashboard_finding_review_uses_runtime_identity(
    live_browser_url: str, chromium_browser: Browser
):
    page = chromium_browser.new_page()
    snapshot = build_dashboard(
        {
            "question": "Review finding",
            "evidence": [{"id": "source-e1", "passage": "Exact finding."}],
        },
        run_id="A",
        revision=1,
    )
    decision = "pending"
    edits = []

    def dashboard(route):
        route.fulfill(
            json={
                **snapshot,
                "role": "owner",
                "evidence_reviews": {
                    "source-e1": {
                        "id": "runtime-e1",
                        "version": 1 if decision == "pending" else 2,
                        "review_decision": decision,
                    }
                },
            }
        )

    def review(route):
        nonlocal decision
        edits.append(route.request.post_data_json)
        decision = route.request.post_data_json["decision"]
        route.fulfill(json={"id": "runtime-e1", "version": 2, "review_decision": decision})

    page.route("**/runs?*", lambda route: route.fulfill(json={"items": [], "next_cursor": None}))
    page.route("**/runs/A/dashboard", dashboard)
    page.route(
        "**/runs/A/revisions", lambda route: route.fulfill(json={"items": [{"revision": 1}]})
    )
    page.route("**/evidence/runtime-e1/review", review)
    page.request.post(f"{live_browser_url}/auth/development")
    page.goto(f"{live_browser_url}/app?project=development-project&run=A")
    page.get_by_role("link", name="Studies & evidence", exact=True).click()
    page.locator("#dashboard-evidence summary").click()
    page.get_by_role("button", name="Accept evidence", exact=True).click()
    expect(page.locator("#dashboard-evidence")).to_contain_text("accepted")
    assert edits == [{"decision": "accepted", "expected_version": 1}]
    page.close()


def test_real_extractive_result_renders_complete_scientific_dashboard(
    live_browser_url: str, chromium_browser: Browser
):
    from pathlib import Path

    from sci_search.corpus import load_corpus
    from sci_search.generic_research import GenericResearchEngine
    from sci_search.literature_review import build_literature_review
    from sci_search.research_landscape import build_research_landscape
    from sci_search.synthesis import build_structured_synthesis

    corpus = load_corpus(Path("fixtures/iron_air_pilot"))
    investigation = (
        GenericResearchEngine(corpus)
        .investigate("What round-trip efficiencies have been reported for iron-air batteries?")
        .to_dict()
    )
    investigation["research_run"] = {
        "candidates": [
            {
                "id": d.publication.id,
                "title": d.publication.title,
                "year": d.publication.year,
                "authors": list(d.publication.authors),
            }
            for d in corpus
        ],
        "active_publication_ids": [d.publication.id for d in corpus],
    }
    investigation["synthesis"] = build_structured_synthesis(investigation)
    investigation["research_landscape"] = build_research_landscape(investigation)
    investigation["literature_review_report"] = build_literature_review(investigation)
    snapshot = build_dashboard(investigation, run_id="A", revision=1)
    page = chromium_browser.new_page(viewport={"width": 1440, "height": 1000})
    page.route(
        "**/runs?*",
        lambda route: route.fulfill(
            json={
                "items": [
                    {
                        "id": "A",
                        "question": snapshot["question"],
                        "status": "completed",
                        "project_id": "development-project",
                    }
                ],
                "next_cursor": None,
            }
        ),
    )
    page.route("**/runs/A/dashboard", lambda route: route.fulfill(json=snapshot))
    page.route(
        "**/runs/A/revisions", lambda route: route.fulfill(json={"items": [{"revision": 1}]})
    )
    page.request.post(f"{live_browser_url}/auth/development")
    page.goto(f"{live_browser_url}/app?project=development-project&run=A")
    expect(page.locator("[data-dashboard-block]")).to_have_count(13)
    expect(page.locator("#dashboard-literature_review")).to_contain_text(
        "AI-assisted cited evidence review"
    )
    assert page.locator("#dashboard-evidence .evidence-card").count() == len(
        investigation["evidence"]
    )
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    expect(page.locator(".dashboard-stat")).to_have_count(4)
    expect(page.locator("#dashboard-navigation a")).to_have_count(5)
    expect(page.locator("#dashboard-answer")).to_be_visible()
    expect(page.locator("#dashboard-literature_review")).not_to_be_visible()
    expect(page.locator("#research")).not_to_be_visible()
    page.get_by_role("link", name="Literature review", exact=True).click()
    expect(page.locator("#dashboard-literature_review")).to_be_visible()
    page.get_by_role("link", name="Overview", exact=True).click()
    page.get_by_role("button", name="+ New search", exact=True).click()
    expect(page.locator("#research")).to_be_visible()
    page.evaluate("document.body.classList.remove('compose-open')")
    expect(
        page.locator("#dashboard-answer").get_by_text("executive_summary", exact=True)
    ).to_have_count(0)
    page.evaluate(
        "document.querySelector('#dashboard-panel').scrollIntoView({block: 'start', behavior: 'instant'})"
    )
    page.screenshot(path="/tmp/sci-search-dashboard-desktop-viewport.png")
    page.locator("#dashboard-panel").screenshot(
        path="/tmp/sci-search-dashboard-real-extractive.png"
    )
    page.close()


def test_contradiction_groups_render_and_answer_links_to_them(
    live_browser_url: str, chromium_browser: Browser
):
    page = chromium_browser.new_page(viewport={"width": 390, "height": 844})
    hostile = "<img src=x onerror=window.__xss=1>"
    group = {
        "id": "contradiction:abc123",
        "topic": f"Salinity {hostile}",
        "cause": "different_conditions",
        "severity": "high",
        "severity_basis": ["No grounded explanation for the disagreement"],
        "severity_rules_version": "contradiction_severity_v1",
        "touches_answer": True,
        "status": "model_proposed_source_verified",
        "validation_notes": [],
        "cause_explanation": None,
        "positions": [
            {
                "stance": "Reduces germination",
                "evidence_ids": ["e1"],
                "publication_ids": ["p1"],
                "quotes": [{"evidence_id": "e1", "quote": "Germination fell to 40%."}],
                "citations": [1],
            },
            {
                "stance": "No effect",
                "evidence_ids": ["e2"],
                "publication_ids": ["p2"],
                "quotes": [{"evidence_id": "e2", "quote": "Germination was unaffected."}],
                "citations": [2],
            },
        ],
    }
    low = {
        "id": "contradiction:low1",
        "topic": "Foraging on slopes",
        "cause": "different_method",
        "severity": "low",
        "severity_basis": ["Differing methods; which method is appropriate is unresolved"],
        "severity_rules_version": "contradiction_severity_v1",
        "touches_answer": False,
        "status": "model_proposed_source_verified",
        "validation_notes": [],
        "cause_explanation": {
            "text": "GPS collars versus direct observation.",
            "evidence_ids": ["e3", "e4"],
            "quotes": [
                {"evidence_id": "e3", "quote": "GPS collars recorded positions"},
                {"evidence_id": "e4", "quote": "observed by trained observers"},
            ],
            "qualification": "",
        },
        "positions": [
            {
                "stance": "Slope reduces foraging",
                "evidence_ids": ["e3"],
                "publication_ids": ["p3"],
                "quotes": [{"evidence_id": "e3", "quote": "Foraging decreased on slopes."}],
            },
            {
                "stance": "Slope has no effect",
                "evidence_ids": ["e4"],
                "publication_ids": ["p4"],
                "quotes": [{"evidence_id": "e4", "quote": "Foraging was similar on slopes."}],
            },
        ],
    }
    snapshot = build_dashboard(
        {
            "question": "Contradiction question",
            "literature_review_report": {
                "executive_summary": {"text": "Qualified answer", "evidence_ids": ["e1"]},
                "contradiction_groups": [group, low],
                "references": [
                    {
                        "number": 1,
                        "publication_id": "p1",
                        "title": "Chamber germination trial",
                        "year": 2021,
                    },
                    {
                        "number": 2,
                        "publication_id": "p2",
                        "title": "Field salinity survey",
                        "year": 2019,
                    },
                ],
                "answer_contest": {
                    "contested": True,
                    "group_ids": [group["id"]],
                    "qualifications": ["Studies disagree: Salinity (see the contradiction group)."],
                },
            },
        },
        run_id="A",
        revision=1,
    )
    page.route("**/runs?*", lambda route: route.fulfill(json={"items": [], "next_cursor": None}))
    page.route(
        "**/runs/A/dashboard**",
        lambda route: route.fulfill(json={**snapshot, "role": "owner", "current_revision": 1}),
    )
    page.route(
        "**/runs/A/revisions", lambda route: route.fulfill(json={"items": [{"revision": 1}]})
    )
    page.request.post(f"{live_browser_url}/auth/development")
    page.goto(f"{live_browser_url}/app?project=development-project&run=A&revision=1")
    expect(page.locator("#dashboard-question")).to_have_text("Contradiction question")
    link = page.locator("#dashboard-answer .contest-note a")
    expect(link).to_have_text("Studies disagree: Salinity (see the contradiction group).")
    link.click()
    card = page.locator("#contradiction-contradiction-abc123")
    expect(card).to_be_visible()
    expect(card).to_have_attribute("data-severity", "high")
    expect(card.locator(".severity-badge")).to_have_text("High severity")
    expect(card.locator("h4")).to_have_text(f"Salinity {hostile}")
    expect(card.locator(".contradiction-position")).to_have_count(2)
    studies = card.locator(".contradiction-studies")
    expect(studies.nth(0)).to_have_text("[1] Chamber germination trial (2021)")
    expect(studies.nth(1)).to_have_text("[2] Field salinity survey (2019)")
    expect(card).to_contain_text("No grounded explanation found.")
    expect(card).to_contain_text("not expert-confirmed")
    weight = card.locator(".contradiction-stance").first.evaluate(
        "node => Number(getComputedStyle(node).fontWeight)"
    )
    assert weight >= 600
    collapsed = page.locator("#contradiction-contradiction-low1")
    expect(collapsed).to_have_js_property("tagName", "DETAILS")
    expect(collapsed).not_to_have_attribute("open", "")
    summary = collapsed.locator(":scope > summary")
    expect(summary).to_contain_text("Foraging on slopes")
    expect(summary).to_contain_text("Low severity")
    expect(summary).to_contain_text("2 studies")
    expect(collapsed.locator(".contradiction-position").first).to_be_hidden()
    summary.click()
    explanation = collapsed.locator(".contradiction-explanation")
    expect(explanation).to_contain_text("GPS collars versus direct observation.")
    expect(explanation.locator("blockquote")).to_have_count(2)
    expect(explanation).not_to_contain_text("Evidence id")
    assert page.evaluate("window.__xss") is None
    width = page.evaluate("document.documentElement.scrollWidth")
    assert width <= 390


def test_v1_dashboard_has_no_disagreement_section(live_browser_url: str, chromium_browser: Browser):
    page = chromium_browser.new_page()
    snapshot = build_dashboard(
        {
            "question": "Old question",
            "literature_review_report": {"executive_summary": {"text": "A", "evidence_ids": []}},
        },
        run_id="A",
        revision=1,
    )
    page.route("**/runs?*", lambda route: route.fulfill(json={"items": [], "next_cursor": None}))
    page.route(
        "**/runs/A/dashboard**",
        lambda route: route.fulfill(json={**snapshot, "role": "owner", "current_revision": 1}),
    )
    page.route(
        "**/runs/A/revisions", lambda route: route.fulfill(json={"items": [{"revision": 1}]})
    )
    page.request.post(f"{live_browser_url}/auth/development")
    page.goto(f"{live_browser_url}/app?project=development-project&run=A&revision=1")
    expect(page.locator("#dashboard-question")).to_have_text("Old question")
    expect(page.locator(".contradiction-groups")).to_have_count(0)
    expect(page.locator(".contest-note")).to_have_count(0)
