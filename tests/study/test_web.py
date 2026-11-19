from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sci_search.study import __main__ as entry
from sci_search.study.service import StudyService
from sci_search.study.store import StudyStore
from sci_search.study.web import create_app
from tests.study.conftest import SCAN, make_plan
from tests.study.test_service import FakeAnalyzer


@pytest.fixture
def client(tmp_path):
    reply = make_plan(definitions=[{"term": "Storage", "definition": "Energy and power."}])
    analyzer = FakeAnalyzer(make_plan(), reply)
    service = StudyService(
        StudyStore(tmp_path),
        analyzer_factory=lambda: analyzer,
        scan=lambda q, progress: dict(SCAN),
        extend=lambda s, terms, progress: s,
        background=False,
    )
    return TestClient(create_app(service))


def test_page_and_status(client):
    assert "Make study plan" in client.get("/").text
    assert client.get("/api/status").json() == {"model": "codex · fake-model", "datasets": True}


def test_full_flow_new_revise_edit_approve(client):
    sid = client.post("/api/studies", json={"question": "How much storage?"}).json()["id"]
    detail = client.get(f"/api/studies/{sid}").json()
    assert detail["study"]["status"] == "draft"
    assert detail["plan"]["question"] == make_plan()["question"]
    assert detail["scan_items"]["publications"][0]["url"] == "https://example.org/ii3050"
    revised = client.post(
        f"/api/studies/{sid}/revise",
        json={"section": "definitions", "instruction": "Split energy and power"},
    )
    assert revised.json() == {"version": 2, "changed": ["definitions"]}
    assert client.post(
        f"/api/studies/{sid}/edit", json={"section": "scope", "value": ["Netherlands", "2050"]}
    ).json() == {"version": 3}
    assert [v["version"] for v in client.get(f"/api/studies/{sid}/versions").json()] == [1, 2, 3]
    assert client.get(f"/api/studies/{sid}/versions/1").json()["plan"]["scope"] == [
        "Netherlands only"
    ]
    assert client.post(f"/api/studies/{sid}/approve").status_code == 200
    assert client.get(f"/api/studies/{sid}").json()["study"]["status"] == "approved"
    markdown = client.get(f"/api/studies/{sid}/plan.md")
    assert (
        "How much storage?" in markdown.text
        and "attachment" in markdown.headers["content-disposition"]
    )
    assert client.get("/api/studies").json()[0]["id"] == sid


def test_empty_or_long_question_is_rejected(client, tmp_path):
    assert client.post("/api/studies", json={"question": "   "}).status_code == 400
    assert client.post("/api/studies", json={"question": "x" * 2001}).status_code == 400
    assert list(tmp_path.iterdir()) == []


def test_approved_plan_refuses_changes(client):
    sid = client.post("/api/studies", json={"question": "Q"}).json()["id"]
    client.post(f"/api/studies/{sid}/approve")
    for path, body in (
        ("revise", {"section": "scope", "instruction": "x"}),
        ("edit", {"section": "scope", "value": ["x"]}),
        ("search", {"terms": ["h2"]}),
    ):
        response = client.post(f"/api/studies/{sid}/{path}", json=body)
        assert response.status_code == 409 and "Reopen" in response.json()["detail"]
    assert client.post(f"/api/studies/{sid}/reopen").status_code == 200


def test_invalid_edit_is_a_400_with_the_reason(client):
    sid = client.post("/api/studies", json={"question": "Q"}).json()["id"]
    response = client.post(f"/api/studies/{sid}/edit", json={"section": "chapters", "value": []})
    assert response.status_code == 400 and "Q1" in response.json()["detail"]


def test_unknown_study_is_404(client):
    assert client.get("/api/studies/0123456789ab").status_code == 404
    assert client.get("/api/studies/../x").status_code == 404


def test_main_refuses_non_loopback_host():
    with pytest.raises(SystemExit):
        entry.main(["--host", "0.0.0.0"])


def test_page_never_uses_innerhtml():
    assert "innerHTML" not in Path("sci_search/study/static/study.js").read_text()


def test_hidden_controls_stay_hidden():
    # .button sets display, which would otherwise override the hidden attribute.
    css = Path("sci_search/study/static/study.css").read_text()
    assert "[hidden] { display: none !important; }" in css
