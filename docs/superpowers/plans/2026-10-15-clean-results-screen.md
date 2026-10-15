# Clean Results Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the five-tab, thirteen-block results screen with one clean page: the answer and
its certainty first, then why, with the rest collapsed.

**Architecture:**
- A pure Python function `summarize(snapshot)` turns a saved dashboard snapshot into
  display-ready text: answer, certainty label and sentence, key sources, data and literature
  parts, studies counted and left out, missing items, and a landscape line.
- `build_dashboard` stores it, and the dashboard route recomputes it on every read, so saved runs
  get it too.
- `dashboard.js` renders the single page from it and reuses the existing renderers inside
  collapsed sections.

**Tech Stack:** Python 3.11, FastAPI, vanilla ES modules, Playwright browser tests, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-15-clean-results-screen-design.md`

## Global Constraints

- Screen text stays English, like the rest of the app.
- `summarize` makes no model calls, never mutates the snapshot, and never raises on a saved
  snapshot; missing parts give empty fields.
- Certainty labels:
  - "Strong evidence";
  - "Moderate evidence";
  - "Weak evidence";
  - "Not enough evidence";
  - "Not assessed".
- No internal identifiers (`coverage:…`, snake_case keys) outside "More details".
- Element ids that other code and tests use stay:
  - `dashboard-answer`;
  - `dashboard-landscape`;
  - `dashboard-literature_review`;
  - `dashboard-scope`;
  - `dashboard-methods`;
  - `dashboard-studies`;
  - `dashboard-evidence`;
  - `dashboard-validation`;
  - `dashboard-references`;
  - `dashboard-downloads`.
- Use `.venv/bin/python`. Tests:
  ```
  .venv/bin/python -m pytest -q --no-header -p no:cacheprovider --ignore=tests/integration --ignore=tests/system
  ```
  Lint and format: `.venv/bin/ruff check sci_search tests` and `.venv/bin/ruff format sci_search tests`.

## Review Focus

1. **A saved snapshot from before this change** (no `summary`, no `research_scope`, no adequacy)
   must open without errors and show "Not assessed".
2. **A data-only run** (insects) has no studies. It must show a Data part and no Literature or
   "Why" part with empty lists.
3. **Evidence links in the answer** must open the collapsed "More details" and the evidence
   passage, instead of switching to a tab that no longer exists.
4. **Article feedback and evidence review buttons** (accept, reject, exclude article) must keep
   working inside "More details".
5. **The landscape** renders when it is opened, including on a saved revision.

---

### Task 1: The result summary

**Files:**
- Create: `sci_search/result_summary.py`
- Test: `tests/test_result_summary.py`

**Interfaces:**
- Produces: `summarize(snapshot: dict) -> dict` with the keys:
  - `answer`
  - `certainty`
  - `key_sources`
  - `data`
  - `literature`
  - `included`
  - `left_out`
  - `missing`
  - `landscape_line`

- [ ] **Step 1: Write the failing tests**

```python
"""The results screen summary: answer, certainty and why, in plain language."""

import re

from sci_search.dashboard import build_dashboard
from sci_search.result_summary import summarize

HPV = "Did HPV vaccination lower cervical cancer incidence among young women in the Netherlands, Sweden and the United Kingdom?"


def check(identifier, label, kind, passed, count, minimum=1):
    return {
        "id": f"coverage:{identifier}",
        "label": label,
        "kind": kind,
        "passed": passed,
        "publication_count": count,
        "required": True,
        "minimum": minimum,
    }


def study(identifier, title, decision, reason, year=2020):
    return {
        "id": identifier,
        "title": title,
        "year": year,
        "doi": f"10.1/{identifier}",
        "screening": {"decision": decision, "reason": reason},
    }


def hpv_snapshot():
    investigation = {
        "question": HPV,
        "answer_summary": "Vaccination programmes lowered incidence in the Netherlands and Sweden.",
        "summary_evidence_ids": ["e1"],
        "research_scope": {"requirements": {"alternative_driver_dimensions": ["topic:0"], "minimum_independent_publications": 2}},
        "answer_adequacy": {
            "status": "partial",
            "can_answer_overall_question": False,
            "qualifying_evidence_ids": ["e1"],
            "qualifying_publications": 1,
            "checks": [
                check("subject:primary", "cervical cancer", "subject", True, 3),
                check("geography:netherlands", "netherlands", "geography", True, 2),
                check("geography:sweden", "sweden", "geography", True, 1),
                check("geography:united_kingdom", "united kingdom", "geography", False, 0),
                check("topic:0", "hpv vaccination", "topic", False, 0),
                check("independent_publications", "independent contributing publications", "evidence_base", False, 1, 2),
            ],
        },
        "evidence": [
            {"id": "e1", "publication_id": "p1", "statement": "Incidence fell.", "passage": "Incidence fell."},
            {"id": "e2", "publication_id": "p2", "statement": "Coverage rose.", "passage": "Coverage rose."},
        ],
        "research_run": {
            "candidates": [
                study("p1", "Cervical cancer after HPV vaccination in Sweden", "included", "Covers the subject."),
                study("p2", "HPV vaccination in the Netherlands", "included", "Covers the subject."),
                study("p3", "Cervical screening in Brazil", "excluded", "The full text is outside required scope: netherlands, sweden, united kingdom."),
                study("p4", "Vaccine attitudes", "uncertain", "Needs relevance review."),
                study("p5", "Never downloaded", "candidate", "not screened"),
            ],
            "full_text_screening": [],
        },
        "literature_review_report": {
            "references": [
                {"number": 1, "publication_id": "p2", "title": "HPV vaccination in the Netherlands", "year": 2019, "source_url": "https://example.org/p2"},
                {"number": 2, "publication_id": "p1", "title": "Cervical cancer after HPV vaccination in Sweden", "year": 2020, "doi": "10.1/p1"},
            ],
        },
        "research_landscape": {"coverage": {"records": 431, "full_texts_acquired": 4}, "publication_timeline": [{"year": 1990, "publications": 1}, {"year": 2025, "publications": 4}]},
    }
    for paper in investigation["research_run"]["candidates"]:
        investigation["research_run"]["full_text_screening"].append({"publication_id": paper["id"], **paper["screening"]})
    return build_dashboard(investigation, run_id="hpv", revision=1)


def test_partial_evidence_names_what_supports_it_and_what_is_missing():
    summary = summarize(hpv_snapshot())
    certainty = summary["certainty"]
    assert certainty["level"] == "weak"
    assert certainty["label"] == "Weak evidence"
    assert certainty["sentence"].startswith("2 studies count as evidence, covering the Netherlands and Sweden;")
    assert "the United Kingdom" in certainty["sentence"] or "United Kingdom" in certainty["sentence"]
    assert summary["missing"][:2] == [
        "No included study covers the United Kingdom.",
        "No included study links HPV vaccination to the outcome.",
    ]
    assert "1 of 2 required studies answer the whole question." in summary["missing"]


def test_answer_key_sources_and_studies():
    summary = summarize(hpv_snapshot())
    assert summary["answer"]["text"].startswith("Vaccination programmes lowered")
    assert summary["answer"]["evidence_ids"] == ["e1"]
    # The publication cited by the answer comes first.
    assert [s["title"] for s in summary["key_sources"]] == [
        "Cervical cancer after HPV vaccination in Sweden",
        "HPV vaccination in the Netherlands",
    ]
    assert summary["key_sources"][0]["url"] == "https://doi.org/10.1/p1"
    assert summary["key_sources"][1]["url"] == "https://example.org/p2"
    assert [s["title"] for s in summary["included"]] == [
        "Cervical cancer after HPV vaccination in Sweden",
        "HPV vaccination in the Netherlands",
    ]
    assert [(s["title"], s["decision"]) for s in summary["left_out"]] == [
        ("Cervical screening in Brazil", "Excluded"),
        ("Vaccine attitudes", "Needs review"),
    ]
    assert summary["literature"] == {"found": 431, "full_texts": 4, "included": 2, "uncertain": 1, "background": 0, "excluded": 1}
    assert summary["landscape_line"] == "431 studies found, 1990–2025; 2 count as evidence."


def test_adequate_evidence_is_strong():
    snapshot = hpv_snapshot()
    snapshot["result_quality"] = {**snapshot["result_quality"], "status": "adequate"}
    assert summarize(snapshot)["certainty"]["label"] == "Strong evidence"


def data_snapshot():
    investigation = {
        "question": "Is the decline in insect biomass in Germany since 1989 also seen in Dutch monitoring data?",
        "answer_summary": "Analysed 1 downloaded dataset(s).",
        "data_analysis": {
            "kind": "discovered",
            "status": "partial",
            "strategy": {"route": "data"},
            "analyses": [
                {
                    "source": {"title": "Krefeld S1 Dataset", "publisher": "PLOS ONE", "url": "https://example.org/s1.csv"},
                    "components": [
                        {"series": [
                            {"entity": "Germany: plot ORB1", "label": "insect biomass", "unit": "g/day", "annual": [{"year": 1989, "value": 1}, {"year": 2016, "value": 0.2}]},
                            {"entity": "Germany: plot WAH1", "label": "insect biomass", "unit": "g/day", "annual": [{"year": 1990, "value": 1}, {"year": 2015, "value": 0.3}]},
                        ]}
                    ],
                }
            ],
            "assessments": [{"decision": "analysed"}, {"decision": "blocked"}, {"decision": "blocked"}],
        },
    }
    return build_dashboard(investigation, run_id="insects", revision=1)


def test_a_data_answer_lists_its_dataset_and_has_no_literature_part():
    summary = summarize(data_snapshot())
    assert summary["data"] == {
        "datasets": [
            {"title": "Krefeld S1 Dataset", "publisher": "PLOS ONE", "url": "https://example.org/s1.csv", "kind": "dataset", "year": None,
             "entities": ["Germany"], "first_year": 1989, "last_year": 2016, "unit": "g/day"}
        ],
        "not_used": 2,
    }
    assert summary["literature"] is None
    assert summary["key_sources"][0]["title"] == "Krefeld S1 Dataset"
    assert summary["certainty"]["sentence"].startswith("1 dataset analysed (Germany, 1989–2016)")


def test_a_saved_snapshot_without_adequacy_is_not_assessed():
    snapshot = build_dashboard({"question": "Old question"}, run_id="old", revision=1)
    snapshot.pop("result_quality")
    summary = summarize(snapshot)
    assert summary["certainty"] == {"level": "not_assessed", "label": "Not assessed", "sentence": "The evidence for this saved result was not assessed."}
    assert summary["answer"] is None and summary["data"] is None and summary["literature"] is None
    assert summary["included"] == [] and summary["missing"] == [] and summary["landscape_line"] is None


def test_summarize_survives_broken_parts():
    snapshot = {"question": "Q", "blocks": [{"id": "answer", "data": None}, {"id": "studies", "data": {"studies": [None, "x"]}}]}
    assert summarize(snapshot)["certainty"]["level"] == "not_assessed"


def test_screen_text_has_no_internal_identifiers():
    summary = summarize(hpv_snapshot())
    texts = [summary["certainty"]["sentence"], summary["landscape_line"], *summary["missing"]]
    for text in texts:
        assert not re.search(r"coverage:|[a-z]+_[a-z]+", text), text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest -q --no-header -p no:cacheprovider tests/test_result_summary.py`
Expected: ERROR, `ModuleNotFoundError: No module named 'sci_search.result_summary'`.

- [ ] **Step 3: Write the implementation**

```python
"""Plain-language summary of a saved result: the answer, how certain it is, and why.

A pure function over a dashboard snapshot. It makes no model calls and never changes evidence.
"""

from __future__ import annotations

import re
from typing import Any

MAX_SOURCES = 5
MAX_LEFT_OUT = 10
LABELS = {
    "strong": "Strong evidence",
    "moderate": "Moderate evidence",
    "weak": "Weak evidence",
    "insufficient": "Not enough evidence",
    "not_assessed": "Not assessed",
}
DECISIONS = {"excluded": "Excluded", "uncertain": "Needs review", "background": "Background only"}
COVERAGE_KINDS = {"geography", "subject", "subject_part", "population", "time", "outcome", "topic"}
TREND_CHECKS = {"temporal_nature", "directional_trend", "multi_period_trend"}


def summarize(snapshot: dict[str, Any]) -> dict[str, Any]:
    blocks = {
        b.get("id"): b.get("data") if isinstance(b.get("data"), (dict, list)) else {}
        for b in snapshot.get("blocks") or []
        if isinstance(b, dict)
    }
    question = str(snapshot.get("question") or "")
    answer = _dict(blocks.get("answer"))
    adequacy = _dict(answer.get("answer_adequacy"))
    data = _dict(answer.get("data_analysis"))
    scope = _dict(_dict(blocks.get("scope")).get("research_scope"))
    landscape = _dict(blocks.get("landscape"))
    studies = [s for s in _dict(blocks.get("studies")).get("studies") or [] if isinstance(s, dict)]
    references = [r for r in blocks.get("references") or [] if isinstance(r, dict)]
    evidence = [e for e in blocks.get("evidence") or [] if isinstance(e, dict)]
    documents = _dict(snapshot.get("documents"))

    included = [_study(s, documents) for s in studies if _decision(s) == "included"]
    missing = _missing(adequacy, scope, question)
    data_part = _data(data) if data else None
    return {
        "answer": _answer(answer),
        "certainty": _certainty(
            _dict(snapshot.get("result_quality")), adequacy, scope, data_part, included, missing, question
        ),
        "key_sources": _key_sources(answer, evidence, references, data_part, documents),
        "data": data_part,
        "literature": _literature(studies, landscape) if any(_decision(s) for s in studies) else None,
        "included": included,
        "left_out": _left_out(studies, documents),
        "missing": missing,
        "landscape_line": _landscape_line(landscape, len(included)),
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _decision(study: dict[str, Any]) -> str:
    return str(_dict(study.get("screening")).get("decision") or "")


def _as_written(label: str, question: str) -> str:
    """The label as the researcher wrote it ("united kingdom" -> "United Kingdom")."""
    match = re.search(re.escape(label), question, re.IGNORECASE) if label else None
    return match.group(0) if match else label


def _place(label: str, question: str) -> str:
    written = _as_written(label, question)
    article = re.search(rf"\b(the)\s+{re.escape(written)}", question, re.IGNORECASE)
    return f"the {written}" if article else written


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _answer(answer: dict[str, Any]) -> dict[str, Any] | None:
    summary = _dict(answer.get("executive_summary"))
    if not summary.get("text"):
        return None
    return {"text": str(summary["text"]), "evidence_ids": list(summary.get("evidence_ids") or [])}


def _url(item: dict[str, Any], documents: dict[str, Any]) -> str | None:
    if item.get("source_url"):
        return str(item["source_url"])
    if item.get("doi"):
        return "https://doi.org/" + str(item["doi"])
    publication = str(item.get("publication_id") or item.get("id") or "")
    return _dict(documents.get(publication)).get("url")


def _study(study: dict[str, Any], documents: dict[str, Any]) -> dict[str, Any]:
    decision = _decision(study)
    return {
        "title": str(study.get("title") or "Untitled publication"),
        "year": study.get("year"),
        "url": _url(study, documents),
        "decision": DECISIONS.get(decision, "Counted as evidence"),
        "reason": str(_dict(study.get("screening")).get("reason") or ""),
    }


def _left_out(studies: list[dict[str, Any]], documents: dict[str, Any]) -> list[dict[str, Any]]:
    order = {"excluded": 0, "uncertain": 0, "background": 1}
    read = [s for s in studies if _decision(s) in order]
    read.sort(key=lambda s: order[_decision(s)])
    return [_study(s, documents) for s in read[:MAX_LEFT_OUT]]


def _missing(adequacy: dict[str, Any], scope: dict[str, Any], question: str) -> list[str]:
    drivers = set(_dict(scope.get("requirements")).get("alternative_driver_dimensions") or [])
    sentences: list[str] = []
    for check in adequacy.get("checks") or []:
        if not isinstance(check, dict) or check.get("passed") or not check.get("required", True):
            continue
        identifier = str(check.get("id") or "").removeprefix("coverage:")
        label = str(check.get("label") or "")
        kind = check.get("kind")
        if identifier in drivers:
            text = f"No included study links {_as_written(label, question)} to the outcome."
        elif kind == "geography":
            text = f"No included study covers {_place(label, question)}."
        elif kind in COVERAGE_KINDS:
            text = f"No included study covers {_as_written(label, question)}."
        elif identifier == "independent_publications":
            count, minimum = int(check.get("publication_count") or 0), int(check.get("minimum") or 1)
            text = (
                "No single passage answers the whole question."
                if not count
                else f"{count} of {minimum} required studies answer the whole question."
            )
        elif identifier in TREND_CHECKS:
            text = "No study reports a change over time for the requested period."
        else:
            text = (label[:1].upper() + label[1:]).rstrip(".") + "."
        if text not in sentences:
            sentences.append(text)
    return sentences


def _certainty(quality, adequacy, scope, data_part, included, missing, question) -> dict[str, Any]:
    status = quality.get("status")
    if status == "adequate":
        level = "strong"
    elif status == "insufficient":
        level = "insufficient"
    elif status == "partial":
        contributing = int(adequacy.get("qualifying_publications") or 0)
        minimum = int(_dict(scope.get("requirements")).get("minimum_independent_publications") or 1)
        level = "moderate" if contributing >= minimum and len(missing) <= 1 else "weak"
    else:
        level = "not_assessed"
    if level == "not_assessed":
        sentence = "The evidence for this saved result was not assessed."
    else:
        sentence = _sentence(adequacy, data_part, included, missing, question)
    return {"level": level, "label": LABELS[level], "sentence": sentence}


def _sentence(adequacy, data_part, included, missing, question) -> str:
    leads = []
    datasets = (data_part or {}).get("datasets") or []
    if datasets:
        first = datasets[0]
        detail = ", ".join(
            p
            for p in (
                ", ".join(first.get("entities") or []),
                f"{first['first_year']}–{first['last_year']}" if first.get("first_year") else "",
            )
            if p
        )
        leads.append(_plural(len(datasets), "dataset") + " analysed" + (f" ({detail})" if detail else ""))
    if included:
        covered = [
            _place(str(c.get("label") or ""), question)
            for c in adequacy.get("checks") or []
            if isinstance(c, dict) and c.get("kind") == "geography" and c.get("publication_count")
        ]
        one = len(included) == 1
        leads.append(
            f"{len(included)} {'study counts' if one else 'studies count'} as evidence"
            + (f", covering {_join(covered)}" if covered else "")
        )
    lead = " and ".join(leads) or "No study or dataset answers the question directly"
    gaps = [m[:1].lower() + m[1:-1] for m in missing[:2]]
    return "; ".join([lead, *gaps]) + "."


def _series(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    series = list(analysis.get("series") or [])
    for component in analysis.get("components") or []:
        series += _dict(component).get("series") or []
    return [s for s in series if isinstance(s, dict)]


def _data(data: dict[str, Any]) -> dict[str, Any]:
    datasets = []
    for analysis in data.get("analyses") or []:
        if not isinstance(analysis, dict):
            continue
        source = _dict(analysis.get("source"))
        series = _series(analysis)
        years = [
            int(row["year"])
            for s in series
            for row in s.get("annual") or []
            if isinstance(row, dict) and isinstance(row.get("year"), int)
        ]
        entities = list(dict.fromkeys(str(s.get("entity") or "").split(":")[0].strip() for s in series))
        datasets.append(
            {
                "title": str(source.get("title") or "Dataset"),
                "publisher": source.get("publisher"),
                "url": source.get("url"),
                "kind": "dataset",
                "year": None,
                "entities": [e for e in entities if e][:8],
                "first_year": min(years) if years else None,
                "last_year": max(years) if years else None,
                "unit": next((s.get("unit") for s in series if s.get("unit")), None),
            }
        )
    not_used = sum(
        1
        for a in data.get("assessments") or []
        if isinstance(a, dict) and a.get("decision") != "analysed"
    )
    return {"datasets": datasets, "not_used": not_used}


def _key_sources(answer, evidence, references, data_part, documents) -> list[dict[str, Any]]:
    sources = list((data_part or {}).get("datasets") or [])
    publication_of = {str(e.get("id")): str(e.get("publication_id")) for e in evidence}
    cited = [publication_of.get(str(i)) for i in _dict(answer.get("executive_summary")).get("evidence_ids") or []]
    passages = [str(e.get("publication_id")) for e in evidence]
    ranked = sorted(
        references,
        key=lambda r: (
            -cited.count(str(r.get("publication_id"))),
            -passages.count(str(r.get("publication_id"))),
            r.get("number") or 0,
        ),
    )
    for reference in ranked:
        sources.append(
            {
                "title": str(reference.get("title") or "Untitled publication"),
                "year": reference.get("year"),
                "publisher": None,
                "url": _url(reference, documents),
                "kind": "publication",
            }
        )
    return sources[:MAX_SOURCES]


def _literature(studies: list[dict[str, Any]], landscape: dict[str, Any]) -> dict[str, int]:
    coverage = _dict(landscape.get("coverage"))
    decisions = [_decision(s) for s in studies]
    read = [d for d in decisions if d in {"included", "excluded", "uncertain", "background"}]
    return {
        "found": int(coverage.get("records") or len(studies)),
        "full_texts": int(coverage.get("full_texts_acquired") or len(read)),
        "included": decisions.count("included"),
        "uncertain": decisions.count("uncertain"),
        "background": decisions.count("background"),
        "excluded": decisions.count("excluded"),
    }


def _landscape_line(landscape: dict[str, Any], included: int) -> str | None:
    records = int(_dict(landscape.get("coverage")).get("records") or 0)
    if not records:
        return None
    years = [
        int(row["year"])
        for row in landscape.get("publication_timeline") or []
        if isinstance(row, dict) and str(row.get("year", "")).isdigit()
    ]
    span = f", {min(years)}–{max(years)}" if years else ""
    found = f"{records} {'study' if records == 1 else 'studies'}"
    counted = f"{included} {'counts' if included == 1 else 'count'}"
    return f"{found} found{span}; {counted} as evidence."
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest -q --no-header -p no:cacheprovider tests/test_result_summary.py`
Expected: all pass.

When a sentence differs in wording (for example "covering the Netherlands and Sweden"), fix
the implementation rather than the test. The test wording is the screen text.

- [ ] **Step 5: Check it against the five saved snapshots**

Run the summary over the five exported snapshots, and confirm it raises nothing and that every
sentence is readable:

```bash
for f in /tmp/claude-1000/-home-david-PycharmProjects-sci-search/5c56c2c9-f718-4034-84fe-3f25fcc70761/scratchpad/snapshots/*.json; do
  .venv/bin/python -c "import json,sys; from sci_search.result_summary import summarize; s=summarize(json.load(open(sys.argv[1]))); print(sys.argv[1].rsplit('/',1)[1], s['certainty'], s['missing'][:3], s['landscape_line'])" "$f"
done
```

- [ ] **Step 6: Lint and commit**

```bash
.venv/bin/ruff format sci_search tests && .venv/bin/ruff check sci_search tests
git add sci_search/result_summary.py tests/test_result_summary.py
git commit -m "Summarize a saved result as answer, certainty and why"
```

### Task 2: Serve the summary

**Files:**
- Modify: `sci_search/dashboard.py`: add `"summary"` to the returned snapshot.
- Modify: `sci_search/api/routes/dashboards.py:39-47`: recompute on read.
- Test: `tests/test_result_summary.py` (built snapshot) and
  `tests/api/test_saved_local_dashboards.py` (route).

**Interfaces:**
- Consumes: `summarize(snapshot)` from Task 1.
- Produces: every `GET /api/v1/projects/{p}/runs/{r}/dashboard` response has a `summary` key
  (a dict, or `None` when summarizing failed).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_result_summary.py`:

```python
def test_new_snapshots_carry_their_summary():
    snapshot = hpv_snapshot()
    assert snapshot["summary"] == summarize(snapshot)
```

Append to `tests/api/test_saved_local_dashboards.py`:

```python
def test_dashboard_route_adds_a_summary_to_snapshots_saved_without_one(monkeypatch, tmp_path):
    import sqlite3

    app = application(monkeypatch, tmp_path)
    with TestClient(app) as client:
        headers = login(client)
        project = client.get("/api/v1/projects").json()["items"][0]["id"]
        base = f"/api/v1/projects/{project}/runs"
        run_id = client.post(
            base,
            headers=headers,
            json={"question": "Question summary", "review_depth": "focused", "idempotency_key": "summary"},
        ).json()["id"]
        wait_completed(client, f"{base}/{run_id}")
        with sqlite3.connect(tmp_path / "workspace.sqlite3") as db:
            (raw,) = db.execute("SELECT snapshot FROM dashboard_revisions WHERE run_id=?", (run_id,)).fetchone()
            saved = json.loads(raw)
            saved.pop("summary", None)
            db.execute("UPDATE dashboard_revisions SET snapshot=? WHERE run_id=?", (json.dumps(saved), run_id))
        summary = client.get(f"{base}/{run_id}/dashboard").json()["summary"]
    assert summary["answer"]["text"] == "Supported answer"
    assert summary["certainty"]["label"] in {"Not assessed", "Not enough evidence", "Weak evidence"}
```

- [ ] **Step 2: Run the tests to verify they fail**

```
.venv/bin/python -m pytest -q --no-header -p no:cacheprovider tests/test_result_summary.py tests/api/test_saved_local_dashboards.py -k summary
```

Expected: FAIL. The first test raises `KeyError: 'summary'`, and the route test fails because
`summary` is missing from the response.

- [ ] **Step 3: Implement**

In `sci_search/dashboard.py`, replace the final `return {...}` with:

```python
    snapshot = {
        "result_quality": result_quality(source),
        "analysis": {
            "selection": source.get("analysis_selection"),
            "provider": ai.get("provider") or retained_model.get("provider"),
            "model": ai.get("model") or retained_model.get("name"),
            "status": ai.get("status") or retained_model.get("status"),
            "method": ai.get("method") or retained_model.get("method"),
            "fallback_reason": ai.get("fallback_reason") or ai.get("reason"),
        },
        "schema_version": "research_dashboard_v1",
        "layout_version": 1,
        "run_id": run_id,
        "revision": revision,
        "question": source.get("question", ""),
        "blocks": blocks,
    }
    snapshot["summary"] = summarize(snapshot)
    return snapshot
```

Add the import `from sci_search.result_summary import summarize` next to the `result_quality`
import.

In `sci_search/api/routes/dashboards.py`, change the `dashboard` handler to:

```python
@router.get("/{run_id}/dashboard")
def dashboard(
    project_id: str,
    run_id: str,
    principal: Principal,
    service: ResearchService,
    revision: int | None = Query(default=None, ge=1),
) -> dict:
    snapshot = service.get_dashboard(principal.user_id, project_id, run_id, revision=revision)
    # Recomputed on every read, so saved runs get the current wording without a rebuild.
    try:
        snapshot["summary"] = summarize(snapshot)
    except Exception:  # a summary must never block opening a saved result
        logger.exception("Result summary failed for run %s", run_id)
        snapshot["summary"] = None
    return snapshot
```

Add `import logging`, `logger = logging.getLogger(__name__)` and
`from sci_search.result_summary import summarize` at the top of the module, following its
existing import order.

- [ ] **Step 4: Run the tests to verify they pass, then the API and dashboard suites**

```
.venv/bin/python -m pytest -q --no-header -p no:cacheprovider tests/test_result_summary.py tests/api tests/test_dashboard.py
```

Expected: all pass. `test_saved_searches_projects_and_exports_survive_restart` compares two
reads and still passes, because the summary is deterministic.

- [ ] **Step 5: Commit**

```bash
.venv/bin/ruff format sci_search tests && .venv/bin/ruff check sci_search tests
git add sci_search/dashboard.py sci_search/api/routes/dashboards.py tests/test_result_summary.py tests/api/test_saved_local_dashboards.py
git commit -m "Serve the result summary with every dashboard, including saved ones"
```

### Task 3: The single-page screen

**Files:**
- Modify: `sci_search/frontend/static/dashboard.js`:
  - remove `views`, `showView`, `overview` and the block loop;
  - add the section renderers.
- Modify: `sci_search/frontend/templates/app.html:147`: remove
  `<nav id="dashboard-navigation" …></nav>`.
- Modify: `sci_search/frontend/static/app.css`:
  - remove the `#dashboard-navigation` and `.dashboard-overview` / `.dashboard-stat` rules;
  - add the result styles.
- Modify: `tests/browser/test_saved_dashboards.py`: replace the tab clicks.
- Create: `tests/browser/test_results_screen.py`.

**Interfaces:**
- Consumes: `snapshot.summary` from Task 2, and the existing renderers:
  - `renderDataResearch`
  - `renderLandscape`
  - `reviewBlock`
  - `contradictionGroups`
  - `studyBlock`
  - `evidenceBlock`
  - `fields`
  - `dataTable`
- Produces: the DOM ids listed in Global Constraints. Each top-level section carries
  `data-result-section="answer|data|literature|why|landscape|details"`.

- [ ] **Step 1: Write the failing browser test** (`tests/browser/test_results_screen.py`)

```python
from playwright.sync_api import Browser, expect

from sci_search.dashboard import build_dashboard
from tests.test_result_summary import hpv_snapshot


def open_snapshot(page, url, snapshot):
    page.route("**/runs/A/dashboard", lambda route: route.fulfill(json=snapshot))
    page.route("**/runs/A/revisions", lambda route: route.fulfill(json={"items": [{"revision": 1}]}))
    page.request.post(f"{url}/auth/development")
    page.goto(f"{url}/app?project=development-project&run=A")


def test_one_clean_page_with_the_answer_first(live_browser_url: str, chromium_browser: Browser):
    page = chromium_browser.new_page()
    open_snapshot(page, live_browser_url, {**hpv_snapshot(), "role": "owner"})
    sections = page.locator("[data-result-section]")
    expect(sections.first).to_have_attribute("data-result-section", "answer")
    order = sections.evaluate_all("nodes => nodes.map(n => n.dataset.resultSection)")
    assert order == ["answer", "literature", "why", "landscape", "details"]
    answer = page.locator("#dashboard-answer")
    expect(answer.locator(".certainty-pill")).to_have_text("Weak evidence")
    expect(answer).to_contain_text("covering the Netherlands and Sweden")
    expect(page.locator("#dashboard-why")).to_contain_text("No included study covers the United Kingdom.")
    expect(page.locator("#dashboard-why")).to_contain_text("Cervical screening in Brazil")
    # Collapsed by default; the landscape renders when opened.
    assert not page.locator("#dashboard-landscape").evaluate("n => n.open")
    assert not page.locator("#dashboard-details").evaluate("n => n.open")
    page.locator("#dashboard-landscape > summary").click()
    expect(page.locator("#dashboard-landscape")).to_contain_text("Discovered studies")
    # Evidence links open the collapsed details and the passage.
    answer.get_by_role("link", name="Evidence e1", exact=True).click()
    assert page.locator("#dashboard-details").evaluate("n => n.open")
    expect(page.locator("#evidence-e1")).to_be_visible()
    # No tabs and no internal identifiers above "More details".
    expect(page.locator("#dashboard-navigation")).to_have_count(0)
    visible = page.locator("#dashboard-blocks > :not(#dashboard-details)").all_inner_texts()
    assert not any("coverage:" in t or "executive_summary" in t for t in visible)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.screenshot(path="/tmp/sci-search-results-screen.png", full_page=True)
    page.close()


def test_a_data_answer_shows_the_data_part_only(live_browser_url: str, chromium_browser: Browser):
    from tests.test_result_summary import data_snapshot

    page = chromium_browser.new_page()
    open_snapshot(page, live_browser_url, data_snapshot())
    order = page.locator("[data-result-section]").evaluate_all("nodes => nodes.map(n => n.dataset.resultSection)")
    assert order == ["answer", "data", "details"]
    expect(page.locator("#dashboard-data")).to_contain_text("Krefeld S1 Dataset")
    expect(page.locator("#dashboard-data")).to_contain_text("Germany · 1989–2016 · g/day")
    page.close()


def test_a_saved_snapshot_without_summary_still_opens(live_browser_url: str, chromium_browser: Browser):
    snapshot = build_dashboard({"question": "Old question", "answer_summary": "Old answer"}, run_id="A", revision=1)
    snapshot.pop("summary")
    page = chromium_browser.new_page()
    open_snapshot(page, live_browser_url, snapshot)
    expect(page.locator("#dashboard-answer")).to_contain_text("Old answer")
    expect(page.locator(".certainty-pill")).to_have_text("Not assessed")
    page.close()
```

Routing `/dashboard` directly bypasses the server's read-time summary. The first two tests
therefore rely on `build_dashboard` storing it (Task 2), and the third covers a missing summary.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest -q --no-header -p no:cacheprovider tests/browser/test_results_screen.py`
Expected: FAIL, because `data-result-section` is not found.

- [ ] **Step 3: Implement the screen in `dashboard.js`**

Delete these from `dashboard.js`:
- the `views` constant and `showView`;
- `overview`;
- `evidenceQuality`;
- the `nav` loop;
- the `titles`/`order`/`for (const block …)` loop;
- `showView(selectedView)`;
- the `selectedView` computation.

Keep `element`, `safeLink`, `fields`, `dataTable`, `expandable`, `contradictionGroups`,
`contestNote`, `reviewBlock`, `evidenceBlock` and `studyBlock`, plus the header code in
`renderDashboard` (question, model line, Download all).

Replace the two `showView(...)` calls in `evidenceLinks` and `contestNote` with
`reveal(target)` and `reveal(document.getElementById(anchor))`, and add:

```js
// Open every collapsed section around a target, so links into "More details" work.
function reveal(target) {
  for (let node = target; node; node = node.parentElement) if (node.tagName === 'DETAILS') node.open = true;
  target?.scrollIntoView({block: 'start'});
  target?.focus?.();
}
function resultSection(id, title, {collapsed = false, line = ''} = {}) {
  const node = element(collapsed ? 'details' : 'section', '', collapsed ? 'result-section result-collapsed' : 'result-section');
  node.id = `dashboard-${id}`;
  node.dataset.resultSection = id;
  const heading = element('h2', title);
  if (collapsed) {
    const summary = element('summary'); summary.append(heading);
    if (line) summary.append(element('span', line, 'result-line'));
    node.append(summary);
  } else node.append(heading);
  return node;
}
function sourceItem(item, note = '') {
  const li = element('li');
  const text = `${item.title}${item.year ? ` (${item.year})` : ''}`;
  li.append(item.url ? safeLink(text, item.url) : element('span', text));
  const extra = [item.publisher, note].filter(Boolean).join(' · ');
  if (extra) li.append(element('span', ` · ${extra}`, 'help'));
  return li;
}
function list(items, render) { const ul = element('ul', '', 'result-list'); for (const item of items) ul.append(render(item)); return ul; }
function answerSection(summary, answer) {
  const node = resultSection('answer', 'Answer');
  const text = summary.answer?.text || answer.executive_summary?.text;
  if (text) node.append(element('p', text, 'result-answer'));
  const ids = summary.answer?.evidence_ids || answer.executive_summary?.evidence_ids || [];
  if (ids.length) node.append(evidenceLinks(ids));
  const certainty = summary.certainty || {level: 'not_assessed', label: 'Not assessed', sentence: ''};
  const line = element('p', '', 'certainty');
  line.append(element('span', certainty.label, `certainty-pill certainty-${certainty.level}`));
  if (certainty.sentence) line.append(document.createTextNode(` ${certainty.sentence}`));
  node.append(line);
  contestNote(answer.answer_contest, node);
  if (summary.key_sources?.length) node.append(element('h3', 'Key sources'), list(summary.key_sources, item => sourceItem(item)));
  return node;
}
function dataSection(summary, analysis) {
  const node = resultSection('data', 'What the data show');
  const datasets = summary.data.datasets || [];
  if (datasets.length) node.append(list(datasets, d => sourceItem(d, [d.entities?.join(', '), d.first_year ? `${d.first_year}–${d.last_year}` : '', d.unit].filter(Boolean).join(' · '))));
  else node.append(element('p', 'No dataset gave a supported numerical answer.', 'help'));
  const more = element('details', '', 'result-more');
  more.append(element('summary', `Charts, values and sources${summary.data.not_used ? ` · ${summary.data.not_used} sources not used` : ''}`));
  renderDataResearch(analysis, more);
  node.append(more);
  return node;
}
function literatureSection(summary, blocks, snapshot) {
  const node = resultSection('literature', 'What the literature says');
  const l = summary.literature;
  node.append(element('p', `${l.found} studies found · ${l.full_texts} full texts read · ${l.included} counted as evidence`, 'help'));
  if (blocks.findings?.claims?.length) fields(blocks.findings.claims, node);
  if (blocks.comparisons?.contradiction_groups?.length) contradictionGroups(blocks.comparisons.contradiction_groups, node, snapshot);
  if (blocks.literature_review && Object.keys(blocks.literature_review).length) {
    const review = element('details', '', 'result-more'); review.id = 'dashboard-literature_review';
    review.append(element('summary', 'Read the full review')); reviewBlock(blocks.literature_review, review); node.append(review);
  }
  return node;
}
function studyItem(study, withDecision) {
  const li = sourceItem(study, withDecision ? study.decision : '');
  if (study.reason) li.append(element('p', study.reason, 'help'));
  return li;
}
function whySection(summary) {
  if (!summary.missing?.length && !summary.included?.length && !summary.left_out?.length) return null;
  const node = resultSection('why', 'Why this certainty');
  if (summary.missing?.length) node.append(element('h3', 'What is missing'), list(summary.missing, text => element('li', text)));
  if (summary.included?.length) node.append(element('h3', `Counted as evidence (${summary.included.length})`), list(summary.included, s => studyItem(s, false)));
  if (summary.left_out?.length) node.append(element('h3', 'Read but not counted'), list(summary.left_out, s => studyItem(s, true)));
  return node;
}
function landscapeSection(summary, landscape) {
  const node = resultSection('landscape', 'Research landscape', {collapsed: true, line: summary.landscape_line || ''});
  // Drawn on first opening: the timeline and study browser are large and usually not needed.
  node.addEventListener('toggle', () => { if (node.open && !node.dataset.drawn) { node.dataset.drawn = 'yes'; renderLandscape(landscape, node); } });
  return node;
}
function detailPart(parent, id, title, draw) {
  const part = element('details', '', 'result-part'); part.id = `dashboard-${id}`;
  part.append(element('summary', title)); draw(part); parent.append(part);
}
function detailsSection(blocks, snapshot, context) {
  const node = resultSection('details', 'More details', {collapsed: true, line: 'Question interpretation, methods, all studies and passages, validation, references and downloads'});
  if (blocks.scope) detailPart(node, 'scope', 'Question and scope', part => {
    fields(blocks.scope.question_brief, part);
    const scope = blocks.scope.research_scope || {};
    if (scope.dimensions?.length) part.append(dataTable(scope.dimensions, [['label', 'Part of the question'], ['kind', 'Type'], ['required', 'Required']]));
    part.append(expandable('Full question interpretation and search plan', {research_scope: scope, plan: blocks.scope.plan}));
  });
  if (blocks.methods) detailPart(node, 'methods', 'Search and methods', part => {
    part.append(expandable('Search methods and selection flow', {methodology: blocks.methods.methodology, selection_flow: blocks.methods.selection_flow}));
    const run = blocks.methods.research_run || {};
    part.append(expandable('Search and screening record', Object.fromEntries(Object.entries(run).filter(([key]) => !['candidates', 'full_text_screening', 'study_matrix', 'acquisitions', 'acquired', 'evidence', 'authorized_uploads'].includes(key)))));
  });
  if (blocks.studies?.studies?.length) detailPart(node, 'studies', 'All studies and article decisions', part => studyBlock(blocks.studies, part, snapshot, context));
  if (blocks.evidence?.length) detailPart(node, 'evidence', `Evidence passages (${blocks.evidence.length})`, part => evidenceBlock(blocks.evidence, part, snapshot, context));
  if (blocks.validation) detailPart(node, 'validation', 'Validation', part => part.append(expandable('Validation checks and review states', blocks.validation)));
  if (blocks.references?.length) detailPart(node, 'references', 'References', part => {
    for (const reference of blocks.references) {
      const p = element('p', `${reference.number ? `[${reference.number}] ` : ''}${reference.title || reference.publication_id}`);
      const doc = snapshot.documents?.[reference.publication_id];
      if (doc?.url || reference.source_url) p.append(document.createTextNode(' · '), safeLink('Open publication', doc?.url || reference.source_url));
      part.append(p);
    }
  });
  const artifacts = snapshot.artifacts || blocks.downloads || [];
  if (artifacts.length) detailPart(node, 'downloads', 'Downloads', part => { for (const a of artifacts) if (a.url) part.append(safeLink(a.filename || a.id || 'Download', a.url)); });
  return node;
}
```

At the end of `renderDashboard`, after the Download-all code, render the sections:

```js
  const blocks = Object.fromEntries((snapshot.blocks || []).filter(b => b.status === 'ready').map(b => [b.id, b.data]));
  const summary = snapshot.summary || {};
  root.append(answerSection(summary, blocks.answer || {}));
  if (summary.data && blocks.answer?.data_analysis) root.append(dataSection(summary, blocks.answer.data_analysis));
  if (summary.literature) root.append(literatureSection(summary, blocks, snapshot));
  const why = whySection(summary); if (why) root.append(why);
  if (blocks.landscape) root.append(landscapeSection(summary, blocks.landscape));
  root.append(detailsSection(blocks, snapshot, context));
```

Remove `overview(snapshot, root);` and all references to `#dashboard-navigation` in
`renderDashboard`.

- [ ] **Step 4: Styles in `app.css`**

Delete the `#dashboard-navigation …` rules (lines 125–126, 175–177, 249–252 and 282) and the
`.dashboard-overview` / `.dashboard-stat` rules (lines 179, 207, 254, 275 and 401, and any
`.dashboard-stat` rule). Append:

```css
/* Results: one calm column; the certainty pill is the only colour in the answer. */
#dashboard-blocks { max-width: 760px; margin: 0 auto; display: grid; gap: 2.25rem; }
.result-section { border: 0; padding: 0; }
.result-section h2 { font-size: 1.15rem; margin: 0 0 .75rem; }
.result-section h3 { font-size: .95rem; margin: 1.25rem 0 .4rem; color: var(--muted); font-weight: 600; }
.result-answer { font-size: 1.15rem; line-height: 1.6; margin: 0 0 1rem; }
.certainty { margin: 0 0 1rem; color: var(--ink); }
.certainty-pill { display: inline-block; padding: .15rem .6rem; border-radius: 999px; font-size: .85rem; font-weight: 700; margin-right: .4rem; }
.certainty-strong { background: #e3f1e8; color: #1f5a35; }
.certainty-moderate, .certainty-weak { background: #fdf0d5; color: #7a4b00; }
.certainty-insufficient, .certainty-not_assessed { background: var(--surface); color: var(--muted); }
.result-list { list-style: none; margin: 0; padding: 0; display: grid; gap: .55rem; }
.result-list li { line-height: 1.45; }
.result-list .help { margin: .15rem 0 0; }
.result-collapsed { border-top: 1px solid var(--line); padding-top: .9rem; }
.result-collapsed > summary { list-style: none; display: flex; flex-wrap: wrap; align-items: baseline; gap: .25rem 1rem; }
.result-collapsed > summary::-webkit-details-marker { display: none; }
.result-collapsed > summary h2 { margin: 0; }
.result-collapsed > summary::after { content: "Show"; margin-left: auto; font-size: .85rem; color: var(--muted); }
.result-collapsed[open] > summary::after { content: "Hide"; }
.result-line { color: var(--muted); font-size: .9rem; }
.result-more, .result-part { margin-top: .9rem; }
.result-more > summary, .result-part > summary { color: var(--muted); font-size: .9rem; }
.result-part { border-top: 1px solid var(--line); padding-top: .6rem; }
```

- [ ] **Step 5: Template**

In `sci_search/frontend/templates/app.html`, delete the line
`<nav id="dashboard-navigation" aria-label="Dashboard sections"></nav>`.

- [ ] **Step 6: Update `tests/browser/test_saved_dashboards.py`**

Add this helper at the top of the module, after the imports:

```python
def open_section(page, section_id):
    """Open a collapsed results section and the sections around it."""
    page.evaluate(
        "id => { for (let n = document.getElementById(id); n; n = n.parentElement) if (n.tagName === 'DETAILS') n.open = true; }",
        section_id,
    )
```

Replace the tab clicks:

| Old line | New line |
|---|---|
| `page.get_by_role("link", name="Studies & evidence", exact=True).click()` before article or exclude buttons | `open_section(page, "dashboard-studies")` |
| the same click before `#dashboard-evidence` | `open_section(page, "dashboard-evidence")` |
| `page.get_by_role("link", name="Research landscape", exact=True).click()` | `open_section(page, "dashboard-landscape")` |
| `page.get_by_role("link", name="Methods & exports", exact=True).click()` | `open_section(page, "dashboard-methods")` |

In the evidence-review test, delete `page.locator("#dashboard-evidence summary").click()`,
because `open_section` already opens it. Then expand the first evidence card with
`page.locator("#dashboard-evidence .evidence-card summary").first.click()`.

In the real-extractive layout test (lines 529–544), replace the tab assertions:

```python
    expect(page.locator("[data-result-section]").first).to_have_attribute("data-result-section", "answer")
    expect(page.locator("#dashboard-navigation")).to_have_count(0)
    open_section(page, "dashboard-literature_review")
    expect(page.locator("#dashboard-literature_review")).to_contain_text("AI-assisted cited evidence review")
    open_section(page, "dashboard-evidence")
    assert page.locator("#dashboard-evidence .evidence-card").count() == len(investigation["evidence"])
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    expect(page.locator("#dashboard-answer")).to_be_visible()
    expect(page.locator("#research")).not_to_be_visible()
```

Keep the "+ New search", `go_back` and screenshot lines that follow.

- [ ] **Step 7: Run the browser tests and the full suite**

```
.venv/bin/python -m pytest -q --no-header -p no:cacheprovider tests/browser
.venv/bin/python -m pytest -q --no-header -p no:cacheprovider --ignore=tests/integration --ignore=tests/system
```

Expected: all pass. Look at `/tmp/sci-search-results-screen.png`: one column, the pill as the
only colour, and nothing below "More details" open.

- [ ] **Step 8: Commit**

```bash
.venv/bin/ruff format sci_search tests && .venv/bin/ruff check sci_search tests
git add sci_search/frontend/static/dashboard.js sci_search/frontend/static/app.css sci_search/frontend/templates/app.html tests/browser/test_results_screen.py tests/browser/test_saved_dashboards.py
git commit -m "Show results as one clean page: answer and certainty first, details collapsed"
```

### Task 4: Check with the real runs and document

**Files:**
- Modify: `README.md` (the "Researcher web interface" section): one paragraph describing the
  results page.

- [ ] **Step 1:** Restart the local app (`serve --unsafe-development --local-research`) on this
  branch. Open the five reruns in My Research, and check that:
  - each opens;
  - the certainty sentence reads naturally;
  - the insect run shows a Data part and no empty Literature part;
  - the evidence links open their passage.
- [ ] **Step 2:** Add the README paragraph: the page shows the answer with a certainty label and
  one sentence, the data and literature parts, why the certainty is what it is, a collapsed
  research landscape, and "More details".
- [ ] **Step 3:** Commit: `git add README.md && git commit -m "Describe the results page"`.
