from sci_search.feedback_ranking import score_feedback
from sci_search.question_planning import plan_question


def event(decision="include", **extra):
    return dict(
        id="1",
        publication_id="paper:1",
        user_id="alice",
        run_id="run:1",
        question="iron air battery efficiency",
        decision=decision,
        created_at="2026-01-01",
        **extra,
    )


def test_related_bounded_and_unrelated_unchanged():
    assert (
        0
        < score_feedback(plan_question("iron air battery efficiency"), [event()])["paper:1"][
            "adjustment"
        ]
        <= 0.25
    )
    assert score_feedback(plan_question("whale population migration"), [event()]) == {}


def test_latest_reset_withdraws_and_votes_do_not_accumulate():
    first = event()
    reset = {**first, "id": "2", "decision": "reset", "created_at": "2026-01-02"}
    plan = plan_question(first["question"])
    assert score_feedback(plan, [first, reset]) == {}
    assert score_feedback(plan, [first, first]) == score_feedback(plan, [first])


def test_conflicting_researchers_cancel_and_explain():
    first = event()
    second = {**first, "id": "2", "user_id": "bob", "decision": "exclude"}
    result = score_feedback(plan_question(first["question"]), [first, second])["paper:1"]
    assert result["adjustment"] == 0
    assert len(result["explanations"]) == 2
    assert result["conflicting"] is True


def test_explicit_population_mismatch_cannot_transfer():
    first = event(population="children")
    assert score_feedback(plan_question("iron air battery efficiency in adults"), [first]) == {}


def test_questions_with_conflicting_populations_do_not_transfer_implicit_votes():
    first = {**event(), "question": "iron air battery efficiency in children"}
    assert score_feedback(plan_question("iron air battery efficiency in adults"), [first]) == {}


def test_bounded_suggestion_preserves_explicit_selection(tmp_path):
    from sci_search.application.memory import MemoryContext
    from sci_search.discovery import PublicationCandidate
    from sci_search.infrastructure.local_memory import LocalScientificMemory

    memory = LocalScientificMemory(
        tmp_path, MemoryContext("alice", "project"), feedback_ranking_enabled=True
    )
    memory.record_feedback(event("exclude"))
    candidate = PublicationCandidate(
        id="paper:1",
        title="iron air battery efficiency",
        abstract="",
        year=None,
        doi=None,
        authors=(),
        publication_type="article",
        source_url=None,
        screening_status="selected",
        relevance_score=0.8,
    )
    ranked = memory.rank_for_acquisition(plan_question(candidate.title), (candidate,))
    assert ranked[0].screening_status == "selected"
    assert ranked[0].relevance_score == 0.8
    assert "Previously exclude" in ranked[0].screening_reason


def test_authoritative_sequence_resolves_same_timestamp_events():
    first = {**event(), "id": "event:9", "sequence": 9}
    reset = {**first, "id": "event:10", "sequence": 10, "decision": "reset"}
    assert score_feedback(plan_question(first["question"]), [reset, first]) == {}


def test_feedback_follows_canonical_paper_when_provider_id_changes(tmp_path):
    import json

    from sci_search.application.memory import MemoryContext
    from sci_search.discovery import PublicationCandidate
    from sci_search.infrastructure.local_memory import LocalScientificMemory

    memory = LocalScientificMemory(
        tmp_path, MemoryContext("alice", "project"), feedback_ranking_enabled=True
    )
    with memory._connect() as connection:
        connection.execute(
            "INSERT INTO publications VALUES (?,?,?,?,?,?,?,?)",
            (
                "paper:1",
                "doi:10.1/same",
                json.dumps({"title": "iron air battery efficiency", "doi": "10.1/same"}),
                "iron air battery efficiency",
                None,
                None,
                None,
                "now",
            ),
        )
    memory.record_feedback(event())
    candidate = PublicationCandidate(
        id="new-provider:1",
        title="iron air battery efficiency",
        doi="10.1/same",
        abstract="",
        year=None,
        authors=(),
        publication_type="article",
        source_url=None,
        screening_status="selected",
    )
    ranked = memory.rank_for_acquisition(plan_question(candidate.title), (candidate,))
    assert "Previously include" in ranked[0].screening_reason
