import pytest

SCAN = {
    "publications": [
        {"id": "P1", "title": "II3050 scenarios", "url": "https://example.org/ii3050", "year": 2023}
    ],
    "datasets": [
        {
            "id": "D1",
            "title": "Hourly load",
            "url": "https://example.org/load",
            "publisher": "ENTSO-E",
        }
    ],
    "steps": [],
}


def make_plan(**overrides):
    base = {
        "question": "How much storage is needed?",
        "definitions": [{"term": "Storage", "definition": "Energy shifted in time."}],
        "subquestions": [{"id": "Q1", "text": "How much?"}],
        "scope": ["Netherlands only"],
        "out_of_reach": [],
        "existing_work": [{"scan_id": "P1", "why": "w"}],
        "data": [{"scan_id": "D1", "provides": "p"}],
        "chapters": [
            {"title": "Model", "goal": "g", "method": "model", "answers": ["Q1"], "output": "o"}
        ],
        "limits": [],
    }
    return {**base, **overrides}


@pytest.fixture
def scan():
    return {k: [dict(i) for i in v] for k, v in SCAN.items()}


@pytest.fixture
def valid_plan():
    return make_plan()
