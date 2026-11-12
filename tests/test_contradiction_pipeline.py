"""A stubbed Mistral contradiction group must survive the real research pipeline end to end.

Dashboard rendering of the same groups is covered by the dashboard tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sci_search.discovery import PublicationCandidate, SearchQuery
from sci_search.fulltext_acquisition import AcquisitionOutcome
from sci_search.mistral_analysis import MistralAnalyzer
from sci_search.research_runs import ResearchLimits, ResearchRunManager
from sci_search.scientific_memory import ScientificMemory
from tests.semantic_review_fixtures import reviewed_response

QUESTION = "How does vegetation structure affect goat foraging behaviour?"
TEXTS = {
    "publication:dense": "Goat foraging behaviour increased with dense vegetation structure in a field experiment.",
    "publication:open": "Goat foraging behaviour decreased with dense vegetation structure in a field experiment.",
}


class Provider:
    name = "fake"

    def search(self, query: SearchQuery, *, limit: int):
        return tuple(
            PublicationCandidate(
                id=publication_id,
                title=f"Vegetation structure and goat foraging behaviour ({publication_id})",
                abstract=text,
                year=2024,
                doi=f"10.1/{publication_id.split(':')[1]}",
                authors=("A. Author",),
                publication_type="article",
                source_url="https://example.org",
                is_open_access=True,
                has_structured_fulltext=True,
                providers=("fake",),
                matched_query_ids=(query.id,),
            )
            for publication_id, text in TEXTS.items()
        )


def acquire(item, corpus: Path) -> AcquisitionOutcome:
    papers = corpus / "papers"
    papers.mkdir(parents=True, exist_ok=True)
    name = item.id.split(":")[1] + ".txt"
    text = f"## Results\n\n{TEXTS[item.id]}\n" * 12
    (papers / name).write_text(text)
    return AcquisitionOutcome(
        item.id, "acquired", "fake", f"papers/{name}", "text/plain", len(text), len(text)
    )


def complete_json(body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    if body["response_format"]["json_schema"]["name"] == "scientific_claim_support":
        return reviewed_response(body, {})
    evidence = json.loads(body["messages"][1]["content"])["evidence"]
    by_publication: dict[str, dict[str, Any]] = {}
    for item in evidence:
        by_publication.setdefault(item["publication_id"], item)
    first, second = list(by_publication.values())[:2]

    def assertion(item: dict[str, Any], text: str) -> dict[str, Any]:
        return {
            "text": text,
            "evidence_ids": [item["id"]],
            "quotes": [{"evidence_id": item["id"], "quote": item["selected_statement"]}],
        }

    answer = assertion(
        first, "Vegetation structure changed goat foraging behaviour in a field experiment."
    )
    payload = {
        "answer": answer,
        "claims": [answer],
        "agreements": [],
        "contradictions": [],
        "method_differences": [],
        "limitations": [],
        "uncertainties": [],
        "assumptions": [],
        "knowledge_gaps": [],
        "entities": [],
        "measurements": [],
        "contradiction_groups": [
            {
                "topic": "Direction of the vegetation-structure effect",
                "positions": [
                    assertion(first, "Dense vegetation increases foraging"),
                    assertion(second, "Dense vegetation decreases foraging"),
                ],
                "cause": "unexplained",
            }
        ],
    }
    return {"choices": [{"message": {"content": json.dumps(payload)}}], "usage": {}}


def test_stubbed_group_reaches_review_and_memory(tmp_path: Path) -> None:
    memory = ScientificMemory(tmp_path / "memory")
    manager = ResearchRunManager(
        tmp_path / "runs",
        providers=(Provider(),),
        acquirer=acquire,
        openalex_api_key="test",
        memory=memory,
        analyzer=MistralAnalyzer("test", model="stub", complete_json=complete_json),
    )
    limits = ResearchLimits(
        per_query=2,
        max_selected=2,
        max_full_texts=2,
        max_acquisition_attempts=2,
        citation_seed_count=0,
        citation_neighbors_per_seed=0,
        citation_depth=0,
    )
    run = manager.run_sync(QUESTION, limits=limits)
    assert run["status"] == "complete"
    result = run["result"]

    [group] = result["ai_analysis"]["contradiction_groups"]
    assert group["cause"] == "unexplained"
    assert sorted(p for position in group["positions"] for p in position["publication_ids"]) == [
        "publication:dense",
        "publication:open",
    ]

    [reviewed] = result["literature_review_report"]["contradiction_groups"]
    assert reviewed["id"] == group["id"]
    assert reviewed["severity"] == "high"
    assert reviewed["touches_answer"] is True

    snapshot = memory.graph_snapshot(limit=5000)
    assert group["id"] in {
        node["id"] for node in snapshot["nodes"] if node["type"] == "ContradictionGroup"
    }
