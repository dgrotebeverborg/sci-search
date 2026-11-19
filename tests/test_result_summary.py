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
    assert (
        certainty["sentence"] == "2 studies count as evidence, covering the Netherlands and Sweden."
    )
    assert summary["missing"][:2] == [
        "No included study covers the United Kingdom.",
        "No included study links HPV vaccination to the outcome.",
    ]
    # How many studies answer it is the certainty's job, not a missing item.
    assert len(summary["missing"]) == 2
    assert summary["headline"] == {
        "kind": "literature",
        "text": "Vaccination programmes lowered incidence in the Netherlands and Sweden.",
    }


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
        "findings": [
            {
                "text": "Germany: plot ORB1: 1 → 0.2 g/day (1989–2016)",
                "measurement": "insect biomass",
            },
            {
                "text": "Germany: plot WAH1: 1 → 0.3 g/day (1990–2015)",
                "measurement": "insect biomass",
            },
        ],
        "more_findings": 0,
    }
    assert summary["literature"] is None
    # The dataset is named with its chart, not repeated as a key source.
    assert summary["key_sources"] == []
    assert summary["certainty"]["sentence"] == "1 dataset from PLOS ONE, 1989–2016."
    assert summary["headline"]["text"] == (
        "Insect biomass fell in Germany: plot ORB1 and Germany: plot WAH1 (1989–2016)."
    )


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


def adequacy_of(snapshot):
    return next(b for b in snapshot["blocks"] if b["id"] == "answer")["data"]["answer_adequacy"]


def test_malformed_numbers_never_raise():
    snapshot = hpv_snapshot()
    for item in adequacy_of(snapshot)["checks"]:
        item["publication_count"] = "n/a"
        item["minimum"] = "n/a"
    adequacy_of(snapshot)["qualifying_publications"] = "n/a"
    next(b for b in snapshot["blocks"] if b["id"] == "landscape")["data"]["coverage"]["records"] = (
        "n/a"
    )
    summarize(snapshot)
    build_dashboard(
        {"question": "Q", "research_landscape": {"coverage": {"records": "n/a"}}},
        run_id="x",
        revision=1,
    )


def test_moderate_evidence_counts_failed_required_checks():
    snapshot = hpv_snapshot()
    adequacy = adequacy_of(snapshot)
    adequacy["qualifying_publications"] = 2
    for item in adequacy["checks"]:
        if item["id"] != "coverage:geography:united_kingdom":
            item["passed"] = True
    # Duplicate wording or extra recorded requirements must not change the count of failed checks.
    adequacy["missing_requirements"] = ["united kingdom", "another recorded requirement"]
    assert summarize(snapshot)["certainty"]["level"] == "moderate"


def test_the_sentence_uses_contributing_publications_without_screening_decisions():
    snapshot = hpv_snapshot()
    studies = next(b for b in snapshot["blocks"] if b["id"] == "studies")["data"]["studies"]
    for study in studies:
        study["screening"] = {}
    adequacy_of(snapshot)["qualifying_publications"] = 3
    sentence = summarize(snapshot)["certainty"]["sentence"]
    assert sentence.startswith("3 publications contribute to the answer"), sentence


def test_data_headlines_gaps_and_no_navigation_phrases():
    investigation = {
        "question": "How did burnt area change in Spain and Portugal?",
        "answer_summary": "Analysed 1 downloaded dataset(s) for burnt area. "
        "Inspect the measurements, coverage and source decisions below.",
        "data_analysis": {
            "kind": "discovered",
            "strategy": {"route": "data"},
            "coverage": {
                "cells": [
                    {"measurement": "burnt area", "entity": "Spain", "status": "complete"},
                    {"measurement": "burnt area", "entity": "Portugal", "status": "missing"},
                    {"measurement": "fire count", "entity": "", "status": "partial"},
                ]
            },
            "analyses": [
                {
                    "source": {"title": "EFFIS"},
                    "series": [
                        {
                            "entity": "Spain",
                            "label": "burnt area",
                            "unit": "ha",
                            "change_percent": -48.86,
                            "annual": [
                                {"year": 2001, "value": 93297.0},
                                {"year": 2002, "value": None},
                                {"year": 2024, "value": 47711.13},
                            ],
                        }
                    ],
                }
            ],
        },
    }
    summary = summarize(build_dashboard(investigation, run_id="fires", revision=1))
    assert summary["answer"]["text"] == "Analysed 1 downloaded dataset(s) for burnt area."
    assert summary["data"]["findings"] == [
        {"text": "Spain: 93,297 → 47,711 ha (2001–2024), -48.9%", "measurement": "burnt area"}
    ]
    assert "No usable data were found for burnt area (Portugal)." in summary["missing"]
    assert "Data are incomplete for fire count." in summary["missing"]


# The overhauled answer: a real headline, honest closest matches, short gaps.


def series(entity, label, unit, points, **extra):
    return {
        "entity": entity,
        "label": label,
        "unit": unit,
        "annual": [{"year": y, "value": v} for y, v in points],
        **extra,
    }


def data_result(
    question, analyses, *, cells=(), assessments=(), answer="Analysed 1 downloaded dataset(s)."
):
    investigation = {
        "question": question,
        "answer_summary": answer,
        "answer_adequacy": {
            "status": "partial",
            "checks": [
                check("geography:netherlands", "netherlands", "geography", False, 0),
                check(
                    "independent_publications",
                    "independent contributing publications",
                    "evidence_base",
                    False,
                    0,
                ),
            ],
        },
        "data_analysis": {
            "kind": "discovered",
            "strategy": {"route": "data"},
            "coverage": {"cells": list(cells)},
            "analyses": analyses,
            "assessments": list(assessments),
        },
    }
    return summarize(build_dashboard(investigation, run_id="d", revision=1))


PV = series(
    "Netherlands",
    "installed solar photovoltaic capacity",
    "gigawatts",
    [(2001, 0.021), (2010, 0.09), (2025, 25.878)],
    change_percent=123128.6,
)


def test_a_data_answer_leads_with_the_numbers():
    summary = data_result(
        "how much did pv increase in holland in this century?",
        [
            {
                "source": {
                    "title": "Solar panels cumulative capacity",
                    "publisher": "Our World in Data",
                },
                "series": [PV],
            }
        ],
        cells=[
            {
                "measurement": "installed solar photovoltaic capacity",
                "entity": "Netherlands",
                "status": "complete",
            }
        ],
    )
    assert summary["headline"] == {
        "kind": "data",
        "text": "Installed solar photovoltaic capacity in the Netherlands rose from 0.021 gigawatts "
        "in 2001 to 25.9 gigawatts in 2025.",
    }
    # A huge percentage from a tiny start says nothing; the ratio does.
    assert summary["data"]["findings"][0]["text"] == (
        "Netherlands: 0.021 → 25.9 gigawatts (2001–2025), 1,232 times as high"
    )
    assert summary["certainty"]["label"] == "Measured data"
    assert summary["certainty"]["sentence"] == "1 dataset from Our World in Data, 2001–2025."
    # Literature gaps do not contradict a measured answer.
    assert summary["missing"] == []
    assert summary["key_sources"] == [] and summary["closest"] == []


def test_several_series_say_where_it_rose_and_fell():
    rows = [
        series("Netherlands", "renewable electricity share", "%", [(2000, 3.4), (2025, 51.2)]),
        series("Germany", "renewable electricity share", "%", [(2000, 6.2), (2025, 58.5)]),
        series("Poland", "renewable electricity share", "%", [(2000, 20.0), (2025, 10.0)]),
    ]
    summary = data_result(
        "How have renewable shares changed?", [{"source": {"title": "Ember"}, "series": rows}]
    )
    assert summary["headline"]["text"] == (
        "Renewable electricity share rose in the Netherlands and Germany and fell in Poland (2000–2025)."
    )
    assert summary["data"]["findings"][0]["text"] == (
        "Netherlands: 3.4 → 51.2 % (2000–2025), +47.8 percentage points"
    )


def test_many_series_are_counted_and_codes_are_cleaned():
    rows = [
        series(
            f"geo={code} ({name}) | sex=F (Females)",
            "life expectancy by country and sex",
            "YR",
            [(1970, 70), (2024, 80 + i)],
        )
        for i, (code, name) in enumerate(
            [
                ("AL", "Albania"),
                ("AT", "Austria"),
                ("BE", "Belgium"),
                ("BG", "Bulgaria"),
                ("CH", "Switzerland"),
            ]
        )
    ]
    rows.append(
        series(
            "geo=XK (Kosovo) | sex=F (Females)",
            "life expectancy by country and sex",
            "YR",
            [(1970, 80), (2024, 75)],
        )
    )
    summary = data_result(
        "Life expectancy in Europe?",
        [
            {
                "source": {"title": "Eurostat"},
                "series": rows,
                "preparation": {"selection": {"code_labels": {"unit": {"YR": "Year"}}}},
            }
        ],
    )
    assert (
        summary["headline"]["text"]
        == "Life expectancy rose in 5 of 6 series and fell in 1 (1970–2024)."
    )
    assert summary["data"]["findings"][0]["text"].startswith("Albania, Females: 70 → 80 years")


def test_missing_data_is_grouped_and_short():
    cells = [
        {"measurement": "number of wildfires", "entity": c, "status": "missing"}
        for c in "ABCDEFGHIJ"
    ]
    cells += [{"measurement": "number of wildfires", "entity": "Europe", "status": "complete"}]
    summary = data_result(
        "Wildfires in Europe?",
        [
            {
                "source": {"title": "OWID"},
                "series": [
                    series("Europe", "number of wildfires", "wildfires", [(2012, 5), (2025, 3)])
                ],
            }
        ],
        cells=cells,
    )
    assert summary["missing"] == [
        "10 of 11 requested places have no usable data for number of wildfires."
    ]
    assert (
        summary["headline"]["text"]
        == "Number of wildfires in Europe fell from 5 in 2012 to 3 in 2025."
    )
    assert summary["certainty"]["label"] == "Partial data"


BLOCKED = [
    {
        "decision": "blocked",
        "title": "Batteries power capacities and energy storage",
        "url": "https://ec.europa.eu/x",
        "reason": "Measurement meaning not confirmed: battery energy capacity/definition: The selected field is total "
        "battery storage capacity per country. It is not capacity per battery.",
    },
    {
        "decision": "blocked",
        "title": "Batteries power capacities and energy storage",
        "url": "https://ec.europa.eu/x",
        "reason": "Measurement meaning not confirmed: battery energy capacity/definition: Duplicate.",
    },
    {
        "decision": "blocked",
        "title": "Data on lithium-ion batteries",
        "reason": "Dataset server returned HTTP 202",
    },
]


def test_no_answer_says_so_and_shows_what_came_closest():
    investigation = {
        "question": "How much has battery capacity increased this century?",
        "answer_summary": "The retrieved evidence is relevant but does not support an overall answer to the complete question.",
        "answer_adequacy": {
            "status": "insufficient",
            "checks": [
                check(
                    "independent_publications",
                    "independent contributing publications",
                    "evidence_base",
                    False,
                    0,
                ),
                check("temporal_nature", "change over time", "trend", False, 0),
            ],
        },
        "evidence": [
            {"id": "e1", "publication_id": "p1", "statement": "s", "passage": "Ferry batteries."}
        ],
        "literature_review_report": {
            "references": [{"number": 1, "publication_id": "p1", "title": "Hybrid ferry"}]
        },
        "data_analysis": {
            "kind": "discovered",
            "strategy": {"route": "data"},
            "analyses": [],
            "assessments": BLOCKED,
        },
    }
    summary = summarize(build_dashboard(investigation, run_id="b", revision=1))
    assert summary["headline"] == {"kind": "none", "text": "No direct answer was found."}
    assert summary["closest"] == [
        {
            "title": "Batteries power capacities and energy storage",
            "url": "https://ec.europa.eu/x",
            "note": "Found, but not used: the selected field is total battery storage capacity per country.",
            "quote": None,
        }
    ]
    # Studies that answer nothing are not shown as key sources.
    assert summary["key_sources"] == []
    assert "No single passage answers the whole question." not in summary["missing"]
    assert summary["missing"] == ["No study reports a change over time for the requested period."]
    assert summary["certainty"]["sentence"] == "No study or dataset answers the question directly."


def test_partial_findings_are_the_closest_evidence_when_there_is_no_answer():
    snapshot = hpv_snapshot()
    snapshot["result_quality"] = {**snapshot["result_quality"], "status": "insufficient"}
    answer = next(b for b in snapshot["blocks"] if b["id"] == "answer")["data"]
    answer["investigation_review"] = {
        "partial_findings": [
            {
                "subject": "cervical cancer",
                "title": "Swedish registry",
                "quote": "Incidence fell 88%.",
                "qualification": "Covers Sweden only.",
                "doi": "10.1/x",
            },
        ]
    }
    summary = summarize(snapshot)
    assert summary["headline"] == {
        "kind": "none",
        "text": "No study answers the whole question; the closest findings are below.",
    }
    assert summary["closest"] == [
        {
            "title": "Swedish registry",
            "url": "https://doi.org/10.1/x",
            "note": "Covers Sweden only.",
            "quote": "Incidence fell 88%.",
        }
    ]
