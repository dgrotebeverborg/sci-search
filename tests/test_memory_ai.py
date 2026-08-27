from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sci_search.corpus import load_corpus
from sci_search.discovery import PublicationCandidate, SearchQuery
from sci_search.fulltext_acquisition import AcquisitionOutcome
from sci_search.generic_research import GenericResearchEngine
from sci_search.mistral_analysis import MistralAnalyzer, _validate_answer_responsiveness
from sci_search.question_planning import plan_question
from sci_search.research_runs import ResearchLimits, ResearchRunManager
from sci_search.scientific_memory import ScientificMemory

ROOT = Path(__file__).resolve().parents[1]


class ScientificMemoryTests(unittest.TestCase):
    def test_publication_provider_aliases_merge_on_canonical_key(self) -> None:
        corpus = ROOT / "fixtures" / "iron_air_pilot"
        report = (
            GenericResearchEngine(load_corpus(corpus))
            .investigate("What round-trip efficiency is reported?")
            .to_dict()
        )
        first = report["evidence"][0]

        def candidate(alias: str) -> dict[str, object]:
            return {
                "id": alias,
                "title": first["publication_title"],
                "doi": first.get("doi"),
                "abstract": "The same publication under another provider identifier.",
                "year": 2024,
                "authors": [],
                "publication_type": "article",
                "source_url": first.get("source_url"),
                "openalex_id": None,
                "pmcid": None,
                "cited_by_count": 0,
                "license": "cc-by",
                "is_open_access": True,
                "screening_status": "selected",
                "relevance_score": 1.0,
                "screening_reason": "test alias",
                "citation_relations": [],
            }

        with tempfile.TemporaryDirectory() as temporary:
            memory = ScientificMemory(Path(temporary) / "memory")
            report["research_run"] = {
                "candidates": [candidate("provider:alias-one")],
                "review_decisions": {},
            }
            memory.ingest_run("alias-run-one", "Question", corpus, report)
            report["research_run"] = {
                "candidates": [candidate("provider:alias-two")],
                "review_decisions": {},
            }
            memory.ingest_run("alias-run-two", "Question", corpus, report)
            stats = memory.stats()
            self.assertEqual(stats["publications"], 3)
            self.assertEqual(stats["publication_aliases"], 2)
            reusable = PublicationCandidate(
                id="provider:alias-two",
                title=str(first["publication_title"]),
                abstract="",
                year=2024,
                doi=first.get("doi"),
                authors=(),
                publication_type="article",
                source_url=first.get("source_url"),
            )
            self.assertIsNotNone(memory.reuse_document(reusable, Path(temporary) / "reused"))

    def test_run_builds_reusable_cumulative_graph_and_document_cache(self) -> None:
        corpus = ROOT / "fixtures" / "iron_air_pilot"
        report = (
            GenericResearchEngine(load_corpus(corpus))
            .investigate("What round-trip efficiency is reported?")
            .to_dict()
        )
        report["corpus_id"] = "research:test-run"
        first = report["evidence"][0]
        report["ai_analysis"] = {
            "claims": [
                {"id": "ai-claim:test", "text": first["statement"], "evidence_ids": [first["id"]]}
            ]
        }
        report["research_run"] = {
            "candidates": [
                {
                    "id": first["publication_id"],
                    "title": first["publication_title"],
                    "doi": first.get("doi"),
                    "abstract": "Iron-air round-trip efficiency evidence.",
                    "year": 2024,
                    "authors": [],
                    "publication_type": "article",
                    "source_url": first.get("source_url"),
                    "openalex_id": None,
                    "pmcid": None,
                    "cited_by_count": 0,
                    "license": "cc-by",
                    "is_open_access": True,
                    "screening_status": "selected",
                    "relevance_score": 1.0,
                    "screening_reason": "test",
                    "citation_relations": [],
                }
            ],
            "review_decisions": {},
        }
        with tempfile.TemporaryDirectory() as temporary:
            memory = ScientificMemory(Path(temporary) / "memory")
            update = memory.ingest_run(
                "test-run", "What round-trip efficiency is reported?", corpus, report
            )
            self.assertGreaterEqual(update["publications_added"], 2)
            stats = memory.stats()
            self.assertEqual(stats["publications"], 3)
            self.assertEqual(stats["runs"], 1)
            self.assertGreater(stats["passages"], 0)
            self.assertGreater(stats["edges"], 0)
            snapshot = memory.graph_snapshot(limit=20)
            self.assertEqual(snapshot["schema_version"], "scientific_memory_v2")
            self.assertLessEqual(len(snapshot["nodes"]), 20)
            self.assertLessEqual(len(snapshot["edges"]), 20)
            self.assertTrue(any(node["type"] == "Publication" for node in snapshot["nodes"]))
            self.assertTrue(all("properties" in edge for edge in snapshot["edges"]))
            plan = plan_question("What round-trip efficiency is reported for iron-air batteries?")
            assessment = memory.assess(plan)
            self.assertGreaterEqual(assessment.cached_full_texts, 1)
            candidates = memory.candidates(plan)
            cached = next(item for item in candidates if item.has_local_fulltext)
            reuse = memory.reuse_document(cached, Path(temporary) / "new-corpus")
            self.assertIsNotNone(reuse)
            self.assertTrue((Path(temporary) / "new-corpus" / reuse[0]).is_file())
            memory.cache_analysis(
                "analysis-key", {"status": "complete", "model": "test", "claims": []}
            )
            cached = memory.cached_analysis("analysis-key")
            self.assertTrue(cached["cache_hit"])
            self.assertEqual(memory.stats()["analyses"], 1)

    def test_silver_evidence_lifecycle_is_persistent_and_auditable(self) -> None:
        corpus = ROOT / "fixtures" / "iron_air_pilot"
        documents = load_corpus(corpus)
        report = (
            GenericResearchEngine(documents)
            .investigate("What round-trip efficiency is reported?")
            .to_dict()
        )
        record = report["evidence"][0]
        self.assertEqual(record["validation_status"], "silver_source_verified")
        self.assertEqual(record["review_state"], "unreviewed")
        self.assertTrue(record["evidence_fingerprint"].startswith("evidence-fingerprint:"))
        self.assertTrue(
            all(
                check["passed"]
                for check in record["validation_checks"]
                if check["severity"] == "error"
            )
        )

        with tempfile.TemporaryDirectory() as temporary:
            memory = ScientificMemory(Path(temporary) / "memory")
            memory.ingest_run("lifecycle-run", "What efficiency is reported?", corpus, report)
            stored = memory.evidence_record(record["id"])
            self.assertEqual(stored["validation_status"], "silver_source_verified")
            self.assertEqual(stored["review_state"], "unreviewed")
            reviewed = memory.review_evidence(
                record["id"], "accept", reason="Passage and interpretation inspected."
            )
            self.assertEqual(reviewed["review_state"], "researcher_verified")
            self.assertEqual(len(reviewed["revisions"]), 1)

            repeated = (
                GenericResearchEngine(
                    documents,
                    lifecycle_lookup=memory.evidence_states,
                )
                .investigate("What round-trip efficiency is reported?")
                .to_dict()
            )
            matching = next(item for item in repeated["evidence"] if item["id"] == record["id"])
            self.assertEqual(matching["review_state"], "researcher_verified")

            memory.review_evidence(record["id"], "reject", reason="Wrong metric association.")
            filtered = (
                GenericResearchEngine(
                    documents,
                    lifecycle_lookup=memory.evidence_states,
                )
                .investigate("What round-trip efficiency is reported?")
                .to_dict()
            )
            self.assertNotIn(record["id"], {item["id"] for item in filtered["evidence"]})

    def test_second_related_run_reuses_cached_full_text(self) -> None:
        class Provider:
            name = "fake"

            def search(self, query: SearchQuery, *, limit: int):
                return (
                    PublicationCandidate(
                        id="publication:memory-paper",
                        title="Vegetation structure and goat foraging behaviour",
                        abstract="Goat foraging behaviour changed with vegetation structure in a field experiment.",
                        year=2024,
                        doi="10.1/memory",
                        authors=("A. Author",),
                        publication_type="article",
                        source_url="https://example.org",
                        is_open_access=True,
                        has_structured_fulltext=True,
                        providers=("fake",),
                        matched_query_ids=(query.id,),
                    ),
                )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            memory = ScientificMemory(root / "memory")
            calls = []

            def acquire(item, corpus):
                calls.append(item.id)
                papers = corpus / "papers"
                papers.mkdir(parents=True, exist_ok=True)
                path = papers / "paper.txt"
                text = (
                    "## Results\n\nGoat foraging behaviour changed with vegetation structure in a field experiment.\n"
                    * 12
                )
                path.write_text(text)
                return AcquisitionOutcome(
                    item.id,
                    "acquired",
                    "fake",
                    "papers/paper.txt",
                    "text/plain",
                    len(text),
                    len(text),
                )

            manager = ResearchRunManager(
                root / "runs",
                providers=(Provider(),),
                acquirer=acquire,
                openalex_api_key="test",
                memory=memory,
            )
            limits = ResearchLimits(
                per_query=2,
                max_selected=2,
                max_full_texts=1,
                max_acquisition_attempts=1,
                citation_seed_count=0,
                citation_neighbors_per_seed=0,
                citation_depth=0,
            )
            first = manager.run_sync(
                "How does vegetation structure affect goat foraging behaviour?", limits=limits
            )
            second = manager.run_sync(
                "How does vegetation structure affect goat foraging behaviour?", limits=limits
            )
            self.assertEqual(first["status"], "complete")
            self.assertEqual(second["status"], "complete")
            self.assertEqual(len(calls), 1)
            self.assertEqual(second["result"]["research_run"]["full_texts_reused"], 1)
            followup = manager.investigate(first["run_id"], "What methods were used?")
            self.assertEqual(followup["question"], "What methods were used?")
            self.assertGreaterEqual(memory.stats()["runs"], 3)
            self.assertGreater(memory.stats()["evidence_records"], 0)


class MistralAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evidence = [
            {
                "id": "e1",
                "publication_id": "p1",
                "publication_title": "Study",
                "section": "results",
                "page": 2,
                "evidence_type": "field_experiment",
                "study_design": "field experiment",
                "passage": "Goat foraging increased by 20% when vegetation height increased during the dry season.",
            }
        ]

    def test_rejects_grounded_answer_that_does_not_explain_a_why_question(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not explain"):
            _validate_answer_responsiveness(
                "Why do studies report different effects of biochar on crop yield?",
                {"answer": {"text": "Biochar increased crop yield by 10 percent."}},
            )
        _validate_answer_responsiveness(
            "Why do studies report different effects of biochar on crop yield?",
            {"answer": {"text": "Effects vary by soil type, application rate, and feedstock."}},
        )

    def test_rejects_method_answer_that_omits_requested_limitations(self) -> None:
        with self.assertRaisesRegex(ValueError, "limitations"):
            _validate_answer_responsiveness(
                "What methods measure goat diet selection, and how do their limitations differ?",
                {"answer": {"text": "Researchers use GPS tracking and direct observation."}},
            )

    def test_rejects_single_result_as_an_answer_to_comparability_question(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not compare multiple"):
            _validate_answer_responsiveness(
                "What efficiencies are reported, and are these values comparable?",
                {"answer": {"text": "One cell reported 91.5% efficiency.", "evidence_ids": ["e1"]}},
            )
        _validate_answer_responsiveness(
            "What efficiencies are reported, and are these values comparable?",
            {
                "answer": {
                    "text": "The values differ across cell and system boundaries and are not directly comparable.",
                    "evidence_ids": ["e1", "e2"],
                }
            },
        )

    def test_accepts_only_cited_assertions_with_exact_source_quotes(self) -> None:
        assertion = {
            "text": "Vegetation height was associated with greater goat foraging.",
            "evidence_ids": ["e1"],
            "quotes": [
                {
                    "evidence_id": "e1",
                    "quote": "Goat foraging increased by 20% when vegetation height increased",
                }
            ],
            "qualification": "One field study.",
        }
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "answer": assertion,
                                "claims": [assertion],
                                "agreements": [],
                                "contradictions": [],
                                "method_differences": [],
                                "limitations": [],
                                "uncertainties": [],
                                "assumptions": [],
                                "knowledge_gaps": [],
                                "entities": [
                                    {
                                        "label": "vegetation height",
                                        "kind": "variable",
                                        "evidence_id": "e1",
                                        "quote": "when vegetation height increased during the dry season",
                                    }
                                ],
                                "measurements": [
                                    {
                                        "metric": "goat foraging change",
                                        "value": 20,
                                        "unit": "%",
                                        "original_text": "20%",
                                        "evidence_id": "e1",
                                        "quote": "Goat foraging increased by 20% when vegetation height increased during the dry season",
                                        "context": {
                                            "evidence_nature": "measured",
                                            "method": "unknown",
                                            "scale": "unknown",
                                            "conditions": [
                                                {
                                                    "name": "season",
                                                    "value": "dry",
                                                    "unit": "",
                                                    "original_text": "dry season",
                                                }
                                            ],
                                            "assumptions": [],
                                        },
                                    }
                                ],
                            }
                        )
                    }
                }
            ],
            "usage": {"total_tokens": 123},
        }
        analyzer = MistralAnalyzer(
            "secret", model="test-model", complete_json=lambda body, headers: response
        )
        result = analyzer.analyze("How does vegetation affect goat foraging?", self.evidence)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["model"], "test-model")
        self.assertTrue(result["validation"]["all_quotes_found_in_source"])
        self.assertEqual(result["measurements"][0]["value"], 20.0)
        self.assertEqual(
            result["measurements"][0]["context"]["conditions"][0]["original_text"], "dry season"
        )
        self.assertNotIn("secret", json.dumps(result))

    def test_rejects_a_quote_not_found_in_the_source(self) -> None:
        assertion = {
            "text": "Invented",
            "evidence_ids": ["e1"],
            "quotes": [{"evidence_id": "e1", "quote": "This quote was never in the paper"}],
        }
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "answer": assertion,
                                "claims": [],
                                "agreements": [],
                                "contradictions": [],
                                "method_differences": [],
                                "limitations": [],
                                "uncertainties": [],
                                "assumptions": [],
                                "knowledge_gaps": [],
                                "entities": [],
                                "measurements": [],
                            }
                        )
                    }
                }
            ]
        }
        analyzer = MistralAnalyzer("secret", complete_json=lambda body, headers: response)
        with self.assertRaises(ValueError):
            analyzer.analyze("Question", self.evidence)

    def test_rejects_a_passage_quote_outside_the_selected_result_statement(self) -> None:
        evidence = [
            {
                **self.evidence[0],
                "statement": "Present-day goat foraging was measured during the dry season.",
                "passage": (
                    "Present-day goat foraging was measured during the dry season. "
                    "A future simulation projects that goat foraging will triple."
                ),
            }
        ]
        assertion = {
            "text": "Observed goat foraging tripled.",
            "evidence_ids": ["e1"],
            "quotes": [
                {
                    "evidence_id": "e1",
                    "quote": "A future simulation projects that goat foraging will triple.",
                }
            ],
        }
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "answer": assertion,
                                "claims": [],
                                "agreements": [],
                                "contradictions": [],
                                "method_differences": [],
                                "limitations": [],
                                "uncertainties": [],
                                "assumptions": [],
                                "knowledge_gaps": [],
                                "entities": [],
                                "measurements": [],
                            }
                        )
                    }
                }
            ]
        }
        analyzer = MistralAnalyzer("secret", complete_json=lambda body, headers: response)
        with self.assertRaisesRegex(ValueError, "selected result statement"):
            analyzer.analyze("Question", evidence)

    def test_uses_first_grounded_claim_when_summary_declines_to_answer(self) -> None:
        grounded = {
            "text": "Vegetation height was associated with greater goat foraging.",
            "evidence_ids": ["e1"],
            "quotes": [
                {
                    "evidence_id": "e1",
                    "quote": "Goat foraging increased by 20% when vegetation height increased",
                }
            ],
        }
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "answer": {
                                    "text": "Insufficient evidence.",
                                    "evidence_ids": [],
                                    "quotes": [],
                                },
                                "claims": [grounded],
                                "agreements": [],
                                "contradictions": [],
                                "method_differences": [],
                                "limitations": [],
                                "uncertainties": [],
                                "assumptions": [],
                                "knowledge_gaps": [],
                                "entities": [],
                                "measurements": [],
                            }
                        )
                    }
                }
            ]
        }
        analyzer = MistralAnalyzer("secret", complete_json=lambda body, headers: response)
        result = analyzer.analyze("Question", self.evidence)
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["answer"]["derived_from_grounded_claim"])
        self.assertEqual(result["answer"]["evidence_ids"], ["e1"])

    def test_does_not_promote_an_uncertainty_to_the_overall_answer(self) -> None:
        uncertainty = {
            "text": "The magnitude remains uncertain.",
            "evidence_ids": ["e1"],
            "quotes": [
                {
                    "evidence_id": "e1",
                    "quote": "Goat foraging increased by 20% when vegetation height increased",
                }
            ],
        }
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "answer": {
                                    "text": "Insufficient evidence.",
                                    "evidence_ids": [],
                                    "quotes": [],
                                },
                                "claims": [],
                                "agreements": [],
                                "contradictions": [],
                                "method_differences": [],
                                "limitations": [],
                                "uncertainties": [uncertainty],
                                "assumptions": [],
                                "knowledge_gaps": [],
                                "entities": [],
                                "measurements": [],
                            }
                        )
                    }
                }
            ]
        }
        analyzer = MistralAnalyzer("secret", complete_json=lambda body, headers: response)
        with self.assertRaisesRegex(ValueError, "answer-level claim"):
            analyzer.analyze("Question", self.evidence)

    def test_rejects_one_bad_record_without_losing_grounded_claims(self) -> None:
        grounded = {
            "text": "Vegetation height was associated with greater goat foraging.",
            "evidence_ids": ["e1"],
            "quotes": [
                {
                    "evidence_id": "e1",
                    "quote": "Goat foraging increased by 20% when vegetation height increased",
                }
            ],
        }
        invalid = {
            "text": "Unsupported uncertainty.",
            "evidence_ids": ["e1"],
            "quotes": [{"evidence_id": "e1", "quote": "words absent from the supplied evidence"}],
        }
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "answer": grounded,
                                "claims": [grounded],
                                "agreements": [],
                                "contradictions": [],
                                "method_differences": [],
                                "limitations": [],
                                "uncertainties": [invalid],
                                "assumptions": [],
                                "knowledge_gaps": [],
                                "entities": [],
                                "measurements": [],
                            }
                        )
                    }
                }
            ]
        }
        result = MistralAnalyzer("secret", complete_json=lambda body, headers: response).analyze(
            "Question", self.evidence
        )
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(result["claims"]), 1)
        self.assertEqual(result["validation"]["rejected_model_records"], 1)
        self.assertEqual(result["rejected_records"][0]["category"], "uncertainties")


if __name__ == "__main__":
    unittest.main()
