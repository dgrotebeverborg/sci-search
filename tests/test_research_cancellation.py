from threading import Event

from sci_search.discovery import PublicationCandidate
from sci_search.fulltext_acquisition import AcquisitionOutcome
from sci_search.research_runs import ResearchLimits, ResearchRunManager

QUESTION = "How does rainfall affect crop yield?"
BRIEF = {"original_question": QUESTION}


def test_cancel_after_provider_call_stops_next_query_and_provider(tmp_path):
    cancelled = Event()
    calls = []

    class Provider:
        def __init__(self, name):
            self.name = name

        def search(self, query, *, limit):
            calls.append(self.name)
            cancelled.set()
            return ()

    manager = ResearchRunManager(
        tmp_path, providers=(Provider("first"), Provider("second")), openalex_api_key="test"
    )
    manager.set_cancellation_check(cancelled.is_set)
    state = manager.run_sync(QUESTION, question_brief=BRIEF)
    assert calls == ["first"]
    assert state["status"] == "cancelled"
    assert state.get("result") is None
    assert not (tmp_path / state["run_id"] / "failure.txt").exists()


def test_cancel_after_acquisition_stops_next_download(tmp_path):
    cancelled = Event()
    downloads = []
    papers = tuple(
        PublicationCandidate(
            id=f"p{i}",
            title=f"Rainfall affects crop yield {i}",
            abstract="Rainfall affects crop yield.",
            year=2024,
            doi=None,
            authors=(),
            publication_type="article",
            source_url=None,
            has_local_fulltext=True,
        )
        for i in range(2)
    )

    class Provider:
        name = "test"

        def search(self, query, *, limit):
            return papers

    def acquire(candidate, corpus):
        downloads.append(candidate.id)
        cancelled.set()
        return AcquisitionOutcome(candidate.id, "failed", "test", None, None, 0, 0)

    manager = ResearchRunManager(
        tmp_path, providers=(Provider(),), acquirer=acquire, openalex_api_key="test"
    )
    manager.set_cancellation_check(cancelled.is_set)
    state = manager.run_sync(
        QUESTION,
        question_brief=BRIEF,
        limits=ResearchLimits(
            max_selected=2, max_full_texts=2, max_acquisition_attempts=2, citation_seed_count=0
        ),
    )
    assert len(downloads) == 1
    assert state["status"] == "cancelled"
