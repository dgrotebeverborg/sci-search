from __future__ import annotations

from sci_search.research.model_evidence import EvidenceSelectionLimits, select_model_evidence


def _record(
    evidence_id: str,
    publication_id: str,
    *,
    statement: str | None = None,
    evidence_type: str = "laboratory_experiment",
    study_design: str = "laboratory experiment",
    direction: str | None = "positive",
    score: float = 1.0,
    passage: str | None = None,
) -> dict[str, object]:
    text = statement or f"Result reported by {publication_id} for {evidence_id}."
    return {
        "id": evidence_id,
        "publication_id": publication_id,
        "publication_title": publication_id,
        "statement": text,
        "passage": passage or text,
        "evidence_type": evidence_type,
        "study_design": study_design,
        "direction": direction,
        "retrieval_score": score,
    }


def test_late_counterevidence_and_method_diversity_survive_leading_record_bias() -> None:
    evidence = [
        _record(f"lead-{index:02d}", "publication-a", score=50 - index)
        for index in range(12)
    ]
    evidence.extend(
        (
            _record(
                "contradiction",
                "publication-b",
                statement="Contrary to earlier reports, efficiency decreased under cycling.",
                direction="negative",
                score=3,
            ),
            _record(
                "limitation",
                "publication-c",
                statement="A limitation is that the system boundary excluded balance-of-plant losses.",
                evidence_type="techno_economic_model",
                study_design="techno-economic model",
                direction=None,
                score=2,
            ),
            _record(
                "different-method",
                "publication-d",
                statement="A pilot demonstration measured AC-to-AC performance at system scale.",
                evidence_type="pilot_demonstration",
                study_design="pilot demonstration",
                score=1,
            ),
        )
    )

    packet = select_model_evidence(
        evidence,
        {"can_answer_overall_question": True},
        EvidenceSelectionLimits(max_records=6, max_tokens=1000),
    )

    selected = set(packet.selected_ids)
    assert {"contradiction", "limitation", "different-method"} <= selected
    assert len({record["publication_id"] for record in packet.selected_records}) >= 4
    assert len({record["evidence_type"] for record in packet.selected_records}) >= 3
    assert len(packet.selected_records) <= 6
    assert packet.estimated_tokens <= 1000
    assert packet.policy_version == "diverse_model_evidence_v1"
    assert set(packet.excluded_ids) >= {f"lead-{index:02d}" for index in range(12)} - selected


def test_selection_is_deterministic_under_input_reordering() -> None:
    evidence = [
        _record("e3", "p2", evidence_type="simulation"),
        _record("e1", "p1"),
        _record("e2", "p1"),
        _record("e4", "p3", direction="negative"),
    ]
    limits = EvidenceSelectionLimits(max_records=3, max_tokens=500)

    first = select_model_evidence(evidence, {}, limits)
    second = select_model_evidence(list(reversed(evidence)), {}, limits)

    assert first.selected_ids == second.selected_ids
    assert first.selection_reasons == second.selection_reasons


def test_empty_and_one_publication_packets_are_explicit() -> None:
    empty = select_model_evidence([], {}, EvidenceSelectionLimits())
    single = select_model_evidence(
        [_record("e2", "only"), _record("e1", "only")],
        {"can_answer_overall_question": False, "missing_requirements": ["independence"]},
        EvidenceSelectionLimits(max_records=2),
    )

    assert empty.selected_records == ()
    assert empty.coverage_complete is False
    assert single.selected_ids == ("e1", "e2")
    assert single.publication_count == 1
    assert single.coverage_complete is False
    assert "independence" in single.missing_requirements


def test_oversized_passage_is_bounded_without_losing_selected_statement() -> None:
    statement = "The measured round-trip efficiency was 70% at system scale."
    oversized = "Background context. " * 1000 + statement + " More context." * 1000

    packet = select_model_evidence(
        [_record("large", "p1", statement=statement, passage=oversized)],
        {},
        EvidenceSelectionLimits(max_records=1, max_tokens=180, max_passage_chars=500),
    )

    selected = packet.selected_records[0]
    assert statement in selected["passage"]
    assert len(selected["passage"]) <= 500
    assert packet.estimated_tokens <= 180
    assert "passage_truncated" in packet.selection_reasons["large"]


def test_token_budget_exclusions_are_recorded() -> None:
    evidence = [
        _record(f"e{index}", f"p{index}", passage="Evidence text. " * 80)
        for index in range(5)
    ]

    packet = select_model_evidence(
        evidence,
        {},
        EvidenceSelectionLimits(max_records=5, max_tokens=120, max_passage_chars=300),
    )

    assert len(packet.selected_records) < 5
    assert any(exclusion.reason == "token_budget" for exclusion in packet.exclusions)
