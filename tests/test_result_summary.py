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
        "research_scope": {
            "requirements": {
                "alternative_driver_dimensions": ["topic:0"],
                "minimum_independent_publications": 2,
            }
        },
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
                check(
                    "independent_publications",
                    "independent contributing publications",
                    "evidence_base",
                    False,
                    1,
                    2,
                ),
            ],
        },
        "evidence": [
            {
                "id": "e1",
                "publication_id": "p1",
                "statement": "Incidence fell.",
                "passage": "Incidence fell.",
            },
            {
                "id": "e2",
                "publication_id": "p2",
                "statement": "Coverage rose.",
                "passage": "Coverage rose.",
            },
        ],
        "research_run": {
            "candidates": [
                study(
                    "p1",
                    "Cervical cancer after HPV vaccination in Sweden",
                    "included",
                    "Covers the subject.",
                ),
                study(
                    "p2", "HPV vaccination in the Netherlands", "included", "Covers the subject."
                ),
                study(
                    "p3",
                    "Cervical screening in Brazil",
                    "excluded",
                    "The full text is outside required scope: netherlands, sweden, united kingdom.",
                ),
                study("p4", "Vaccine attitudes", "uncertain", "Needs relevance review."),
                study("p5", "Never downloaded", "candidate", "not screened"),
            ],
            "full_text_screening": [],
        },
        "literature_review_report": {
            "references": [
                {
                    "number": 1,
                    "publication_id": "p2",
                    "title": "HPV vaccination in the Netherlands",
                    "year": 2019,
                    "source_url": "https://example.org/p2",
                },
                {
                    "number": 2,
                    "publication_id": "p1",
                    "title": "Cervical cancer after HPV vaccination in Sweden",
                    "year": 2020,
                    "doi": "10.1/p1",
                },
            ],
        },
        "research_landscape": {
            "coverage": {"records": 431, "full_texts_acquired": 4},
            "publication_timeline": [
                {"year": 1990, "publications": 1},
                {"year": 2025, "publications": 4},
            ],
        },
    }
    for paper in investigation["research_run"]["candidates"]:
        investigation["research_run"]["full_text_screening"].append(
            {"publication_id": paper["id"], **paper["screening"]}
        )
    return build_dashboard(investigation, run_id="hpv", revision=1)


def test_partial_evidence_names_what_supports_it_and_what_is_missing():
    summary = summarize(hpv_snapshot())
    certainty = summary["certainty"]
    assert certainty["level"] == "weak"
    assert certainty["label"] == "Weak evidence"
    assert certainty["sentence"].startswith(
        "2 studies count as evidence, covering the Netherlands and Sweden;"
    )
    assert (
        "the United Kingdom" in certainty["sentence"] or "United Kingdom" in certainty["sentence"]
    )
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
    assert summary["literature"] == {
        "found": 431,
        "full_texts": 4,
        "included": 2,
        "uncertain": 1,
        "background": 0,
        "excluded": 1,
    }
    assert summary["landscape_line"] == "431 studies found, 1990–2025; 2 count as evidence."


def test_adequate_evidence_is_strong():
    snapshot = hpv_snapshot()
    snapshot["result_quality"] = {**snapshot["result_quality"], "status": "adequate"}
    assert summarize(snapshot)["certainty"]["label"] == "Strong evidence"


def data_snapshot():
    series = [
        {
            "entity": "Germany: plot ORB1",
            "label": "insect biomass",
            "unit": "g/day",
            "annual": [{"year": 1989, "value": 1}, {"year": 2016, "value": 0.2}],
        },
        {
            "entity": "Germany: plot WAH1",
            "label": "insect biomass",
            "unit": "g/day",
            "annual": [{"year": 1990, "value": 1}, {"year": 2015, "value": 0.3}],
        },
    ]
    investigation = {
        "question": "Is the decline in insect biomass in Germany since 1989 also seen in Dutch monitoring data?",
        "answer_summary": "Analysed 1 downloaded dataset(s).",
        "data_analysis": {
            "kind": "discovered",
            "status": "partial",
            "strategy": {"route": "data"},
            "analyses": [
                {
                    "source": {
                        "title": "Krefeld S1 Dataset",
                        "publisher": "PLOS ONE",
                        "url": "https://example.org/s1.csv",
                    },
                    # Real analyses carry the series both at the top and per component.
                    "series": series,
                    "components": [{"series": series}],
                }
            ],
            "assessments": [
                {"decision": "analysed"},
                {"decision": "blocked"},
                {"decision": "blocked"},
            ],
        },
    }
    return build_dashboard(investigation, run_id="insects", revision=1)


def test_a_data_answer_lists_its_dataset_and_has_no_literature_part():
    summary = summarize(data_snapshot())
    assert summary["data"] == {
        "datasets": [
            {
                "title": "Krefeld S1 Dataset",
                "publisher": "PLOS ONE",
                "url": "https://example.org/s1.csv",
                "kind": "dataset",
                "year": None,
                "entities": ["Germany"],
                "first_year": 1989,
                "last_year": 2016,
                "unit": "g/day",
            }
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
    assert summary["certainty"] == {
        "level": "not_assessed",
        "label": "Not assessed",
        "sentence": "The evidence for this saved result was not assessed.",
    }
    assert summary["answer"] is None and summary["data"] is None and summary["literature"] is None
    assert (
        summary["included"] == [] and summary["missing"] == [] and summary["landscape_line"] is None
    )


def test_summarize_survives_broken_parts():
    snapshot = {
        "question": "Q",
        "blocks": [
            {"id": "answer", "data": None},
            {"id": "studies", "data": {"studies": [None, "x"]}},
        ],
    }
    assert summarize(snapshot)["certainty"]["level"] == "not_assessed"


def test_screen_text_has_no_internal_identifiers():
    summary = summarize(hpv_snapshot())
    texts = [summary["certainty"]["sentence"], summary["landscape_line"], *summary["missing"]]
    for text in texts:
        assert not re.search(r"coverage:|[a-z]+_[a-z]+", text), text


def test_periods_and_zero_counts_read_naturally():
    snapshot = hpv_snapshot()
    answer = next(b for b in snapshot["blocks"] if b["id"] == "answer")
    answer["data"]["answer_adequacy"]["checks"].append(
        check("time:requested_period", "since 2009", "time", False, 0)
    )
    assert (
        "No included study covers the requested period (since 2009)."
        in summarize(snapshot)["missing"]
    )
    landscape = {"coverage": {"records": 12}, "publication_timeline": []}
    from sci_search.result_summary import _landscape_line

    assert _landscape_line(landscape, 0) == "12 studies found; none count as evidence."


def test_new_snapshots_carry_their_summary():
    snapshot = hpv_snapshot()
    assert snapshot["summary"] == summarize(snapshot)


def test_unlabelled_checks_fall_back_to_the_recorded_missing_requirements():
    snapshot = hpv_snapshot()
    answer = next(b for b in snapshot["blocks"] if b["id"] == "answer")
    answer["data"]["answer_adequacy"]["checks"].append({"required": True, "passed": False})
    answer["data"]["answer_adequacy"]["missing_requirements"] = [
        "hpv vaccination",
        "Field evidence",
    ]
    missing = summarize(snapshot)["missing"]
    assert "." not in missing
    assert "Field evidence is missing." in missing
    # A requirement already explained by its check is not repeated.
    assert not any(m.startswith("Hpv vaccination") for m in missing)
