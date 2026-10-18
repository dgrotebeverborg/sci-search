from dataclasses import replace
from pathlib import Path

from sci_search.corpus import load_corpus
from sci_search.question_planning import plan_question
from sci_search.retrieval import PassageIndex


def test_reserve_preserves_top_hits_and_includes_other_matching_publications():
    template = load_corpus(Path(__file__).parent.parent / "fixtures/iron_air_pilot")[0]
    dense = replace(
        template,
        publication=replace(template.publication, id="dense", title="Biochar crop yield"),
        text="\n\n".join(
            f"Biochar crop yield increased significantly with biochar crop yield treatment {i}."
            for i in range(20)
        ),
    )
    other = replace(
        template,
        publication=replace(template.publication, id="other", title="Field study"),
        text="Biochar crop yield varied across soil conditions and application rates in this field study.",
    )
    unrelated = replace(
        template,
        publication=replace(template.publication, id="irrelevant", title="Dolphins"),
        text="Dolphins communicate underwater using complex vocal signals over long distances.",
    )
    index = PassageIndex((dense, other, unrelated))
    plan = plan_question(
        "Why do studies report different effects of biochar application on crop yield?"
    )
    baseline = index.search(plan, limit=4)
    assert {p.publication_id for p in baseline} == {"dense"}
    result = index.search(plan, limit=4, publication_reserve=4)
    assert result[:4] == baseline
    assert "other" in {p.publication_id for p in result}
    assert "irrelevant" not in {p.publication_id for p in result}
    assert len(result) <= 8
    assert len({(p.publication_id, p.passage.start) for p in result}) == len(result)


def test_small_reserve_prioritizes_unrepresented_publications_before_second_passages():
    template = load_corpus(Path(__file__).parent.parent / "fixtures/iron_air_pilot")[0]
    documents = []
    for i in range(5):
        documents.append(
            replace(
                template,
                publication=replace(
                    template.publication, id=f"paper-{i}", title="Biochar crop yield"
                ),
                text="\n\n".join(
                    f"Biochar crop yield increased significantly after treatment {j} in field trials."
                    for j in range(5)
                ),
            )
        )
    index = PassageIndex(tuple(documents))
    plan = plan_question("How does biochar affect crop yield?")
    baseline = index.search(plan, limit=2)
    result = index.search(plan, limit=2, publication_reserve=3)
    assert result[:2] == baseline
    assert len(result) == 5
    assert len({p.publication_id for p in result}) == 4
    assert result == index.search(plan, limit=2, publication_reserve=3)


def test_evidence_reserve_cannot_evict_existing_supported_records():
    from sci_search import generic_research as research

    def record(i, publication, score):
        return research.GenericEvidenceRecord(
            id=str(i),
            publication_id=publication,
            publication_title=publication,
            source_document=publication,
            statement=f"Observed result {i}",
            passage=f"Observed result {i}",
            section="results",
            page=1,
            passage_start=i,
            passage_end=i + 1,
            evidence_type="field_experiment",
            result_nature="measured",
            study_design="field",
            matched_terms=(),
            numerical_mentions=(),
            retrieval_score=score,
        )

    primary = tuple(record(i, f"original-{i // 3}", 10) for i in range(24))
    additions = tuple(record(100 + i, f"new-{i // 3}", 100) for i in range(90))
    keys = {(r.publication_id, r.passage_start) for r in primary}
    result = research._evidence_with_publication_reserve(
        primary + additions, keys, prefer_trends=False
    )
    assert {r.id for r in result[:24]} == {r.id for r in primary}
    assert len(result) <= 48
    assert len({r.publication_id for r in result[24:]}) == 24


def test_reserve_does_not_duplicate_sparse_results_or_exceed_three_per_new_study():
    template = load_corpus(Path(__file__).parent.parent / "fixtures/iron_air_pilot")[0]
    documents = tuple(
        replace(
            template,
            publication=replace(template.publication, id=f"paper-{i}", title="Biochar crop yield"),
            text="\n\n".join(
                f"Biochar crop yield increased significantly after treatment {j} in field trials."
                for j in range(6)
            ),
        )
        for i in range(2)
    )
    index = PassageIndex(documents)
    plan = plan_question("How does biochar affect crop yield?")
    assert index.search(plan, limit=2) == index.search(plan, limit=2, publication_reserve=0)
    result = index.search(plan, limit=2, publication_reserve=20)
    assert len(result) == 6
    assert all(
        sum(p.publication_id == identifier for p in result) == 3
        for identifier in ["paper-0", "paper-1"]
    )
    assert index.search(plan, limit=30, publication_reserve=30) == index.search(plan, limit=30)


def test_engine_retains_old_evidence_and_checks_rescued_passages(monkeypatch):
    from sci_search.generic_research import GenericResearchEngine

    template = load_corpus(Path(__file__).parent.parent / "fixtures/iron_air_pilot")[0]
    dense = replace(
        template,
        publication=replace(template.publication, id="dense", title="Biochar crop yield"),
        text="\n\n".join(
            f"Biochar application increased crop yield significantly by {i} percent following biochar application crop yield treatment."
            for i in range(100)
        ),
    )
    other = replace(
        template,
        publication=replace(template.publication, id="other", title="Field study"),
        text="Biochar application increased crop yield by 12 percent across different soil conditions in field trials.",
    )
    unsuitable = replace(
        template,
        publication=replace(template.publication, id="unsuitable", title="Biochar crop yield"),
        text="Dolphins communicate underwater using complex vocal signals over long distances.",
    )
    engine = GenericResearchEngine((dense, other, unsuitable))
    search = engine.index.search
    with monkeypatch.context() as patch:
        patch.setattr(
            engine.index, "search", lambda plan, **kwargs: search(plan, limit=kwargs["limit"])
        )
        before = engine.investigate("How does biochar affect crop yield?")
    after = engine.investigate("How does biochar affect crop yield?")
    assert "other" not in {r.publication_id for r in before.evidence}
    assert "other" in {r.publication_id for r in after.evidence}
    assert "unsuitable" not in {r.publication_id for r in after.evidence}
    assert {r.id for r in before.evidence} <= {r.id for r in after.evidence}
