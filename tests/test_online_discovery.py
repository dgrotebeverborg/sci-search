from __future__ import annotations

import base64
import gzip
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from sci_search.configuration import load_env_file, load_legacy_mistral_key
from sci_search.discovery import (
    PublicationCandidate,
    SearchQuery,
    merge_candidates,
    plan_search_queries,
    screen_candidates,
)
from sci_search.fulltext_acquisition import (
    AcquisitionOutcome,
    _fetch_bytes,
    acquire_full_text,
    tei_xml_to_text,
)
from sci_search.research_runs import ResearchLimits, ResearchRunManager
from sci_search.scholarly_providers import (
    OpenAlexProvider,
    _crossref_candidate,
    discover_with_providers,
    expand_citation_network,
)

QUESTION = "How does vegetation structure affect goat foraging behaviour?"


def candidate(
    identifier: str, title: str, abstract: str, *, doi: str | None = None
) -> PublicationCandidate:
    return PublicationCandidate(
        id=identifier,
        title=title,
        abstract=abstract,
        year=2024,
        doi=doi,
        authors=("A. Researcher",),
        publication_type="article",
        source_url="https://example.org/paper",
        openalex_id="https://openalex.org/W123",
        cited_by_count=12,
        is_open_access=True,
        license="cc-by",
        has_structured_fulltext=True,
        providers=("fake",),
        matched_query_ids=("query:one",),
    )


class FakeProvider:
    name = "fake"

    def search(self, query: SearchQuery, *, limit: int) -> tuple[PublicationCandidate, ...]:
        relevant = candidate(
            "publication:relevant",
            "Vegetation structure and goat foraging behaviour",
            "A field study of goats found that vegetation height and plant species affected browsing and diet selection.",
            doi="10.1234/relevant",
        )
        return (
            PublicationCandidate(
                **{
                    **{field: getattr(relevant, field) for field in relevant.__dataclass_fields__},
                    "matched_query_ids": (query.id,),
                }
            ),
        )


class OnlineDiscoveryTests(unittest.TestCase):
    def test_unreadable_pdf_is_recorded_and_replaced_without_failing_the_run(self) -> None:
        class MixedProvider:
            name = "mixed"

            def search(self, query: SearchQuery, *, limit: int) -> tuple[PublicationCandidate, ...]:
                return tuple(
                    PublicationCandidate(
                        id=f"publication:mixed-{index}",
                        title=f"Vegetation structure affects goat foraging behaviour {index}",
                        abstract="Field evidence about vegetation structure and goat foraging behaviour.",
                        year=2024,
                        doi=f"10.1234/mixed.{index}",
                        authors=(f"Researcher {index}",),
                        publication_type="article",
                        source_url=f"https://example.org/mixed-{index}",
                        openalex_id=f"https://openalex.org/W{3000 + index}",
                        cited_by_count=100 if index == 0 else 10 - index,
                        is_open_access=True,
                        license="cc-by",
                        has_structured_fulltext=True,
                        providers=(self.name,),
                        matched_query_ids=(query.id,),
                    )
                    for index in range(3)
                )

        def acquire(item: PublicationCandidate, corpus: Path) -> AcquisitionOutcome:
            papers = corpus / "papers"
            papers.mkdir(parents=True, exist_ok=True)
            if item.id.endswith("-0"):
                path = papers / "scanned.pdf"
                body = b"%PDF-1.4\n" + (b"0" * 600)
            else:
                path = papers / f"{item.id.rsplit(':', 1)[-1]}.txt"
                body = (
                    b"Results\nVegetation structure affected goat foraging behaviour in field observations. "
                    b"Goats selected taller shrubs and changed browsing as plant height increased."
                )
            path.write_bytes(body)
            return AcquisitionOutcome(
                item.id,
                "acquired",
                "fixture",
                path.relative_to(corpus).as_posix(),
                "application/pdf" if path.suffix == ".pdf" else "text/plain",
                len(body),
                0,
            )

        from sci_search import corpus as corpus_module

        real_document_text = corpus_module._document_text

        def parse_document(path: Path) -> str:
            if path.name == "scanned.pdf":
                raise ValueError(
                    f"PDF contains too little extractable text (OCR may be required): {path}"
                )
            return real_document_text(path)

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "sci_search.corpus._document_text",
                side_effect=parse_document,
            ),
        ):
            manager = ResearchRunManager(
                Path(temporary),
                providers=(MixedProvider(),),
                acquirer=acquire,
                openalex_api_key="fixture",
            )
            state = manager.run_sync(
                QUESTION,
                limits=ResearchLimits(
                    per_query=10,
                    max_selected=10,
                    initial_full_texts=2,
                    max_full_texts=2,
                    max_acquisition_attempts=3,
                    citation_seed_count=0,
                    citation_neighbors_per_seed=0,
                    citation_depth=0,
                ),
            )
        self.assertEqual(state["status"], "complete")
        self.assertEqual(state["progress"]["full_texts_acquired"], 2)
        self.assertEqual(state["progress"]["full_texts_unreadable"], 1)
        unreadable = next(item for item in state["acquisitions"] if item["status"] == "unreadable")
        self.assertIn("OCR may be required", unreadable["error"])
        self.assertNotIn(str(Path(temporary)), unreadable["error"])
        diagnostics = state["result"]["pipeline_diagnostics"]["acquisition"]
        self.assertEqual(diagnostics["unreadable"], 1)

    def test_research_mode_defaults_to_an_adaptive_25_to_50_review(self) -> None:
        limits = ResearchLimits()
        self.assertEqual(limits.review_mode, "research")
        self.assertEqual(limits.initial_full_texts, 25)
        self.assertEqual(limits.max_full_texts, 50)
        self.assertEqual(limits.acquisition_batch_size, 10)

    def test_adaptive_review_stops_when_initial_evidence_coverage_is_adequate(self) -> None:
        class AdaptiveProvider:
            name = "adaptive"

            def search(self, query: SearchQuery, *, limit: int) -> tuple[PublicationCandidate, ...]:
                return tuple(
                    PublicationCandidate(
                        id=f"publication:adaptive-{index}",
                        title=f"Vegetation structure affects goat foraging behaviour in field study {index}",
                        abstract="Field evidence shows vegetation structure affects goat browsing and diet selection.",
                        year=2020 + index,
                        doi=f"10.1234/adaptive.{index}",
                        authors=(f"Researcher {index}",),
                        publication_type="article",
                        source_url=f"https://example.org/adaptive-{index}",
                        openalex_id=f"https://openalex.org/W{1000 + index}",
                        cited_by_count=10 - index,
                        is_open_access=True,
                        license="cc-by",
                        has_structured_fulltext=True,
                        providers=(self.name,),
                        matched_query_ids=(query.id,),
                    )
                    for index in range(6)
                )

        def acquire(item: PublicationCandidate, corpus: Path) -> AcquisitionOutcome:
            papers = corpus / "papers"
            papers.mkdir(parents=True, exist_ok=True)
            path = papers / f"{item.id.rsplit(':', 1)[-1]}.txt"
            text = (
                "Results\nVegetation structure affected goat foraging behaviour in field observations. "
                "Goats selected taller shrubs and changed browsing as plant height increased."
            )
            path.write_text(text, encoding="utf-8")
            return AcquisitionOutcome(
                item.id,
                "acquired",
                "fixture",
                path.relative_to(corpus).as_posix(),
                "text/plain",
                len(text),
                len(text),
            )

        with tempfile.TemporaryDirectory() as temporary:
            manager = ResearchRunManager(
                Path(temporary),
                providers=(AdaptiveProvider(),),
                acquirer=acquire,
                openalex_api_key="fixture",
            )
            state = manager.run_sync(
                QUESTION,
                limits=ResearchLimits(
                    per_query=10,
                    max_selected=10,
                    initial_full_texts=2,
                    max_full_texts=6,
                    acquisition_batch_size=2,
                    max_acquisition_attempts=10,
                    citation_seed_count=0,
                    citation_neighbors_per_seed=0,
                    citation_depth=0,
                ),
            )
        stopping = state["result"]["research_run"]["adaptive_stopping"]
        self.assertEqual(stopping["reason"], "coverage_achieved")
        self.assertLess(state["progress"]["full_texts_acquired"], stopping["hard_cap"])
        self.assertTrue(state["result"]["answer_adequacy"]["can_answer_overall_question"])

    def test_adaptive_review_reports_cap_or_saturation_when_question_remains_unanswered(
        self,
    ) -> None:
        question = QUESTION

        class BoundaryProvider:
            name = "boundary"

            def search(self, query: SearchQuery, *, limit: int) -> tuple[PublicationCandidate, ...]:
                return tuple(
                    PublicationCandidate(
                        id=f"publication:boundary-{index}",
                        title=f"Vegetation structure and goat foraging behaviour {index}",
                        abstract="Goat foraging behaviour and vegetation structure are studied in field ecology.",
                        year=2020 + index,
                        doi=f"10.1234/boundary.{index}",
                        authors=(f"Researcher {index}",),
                        publication_type="article",
                        source_url=f"https://example.org/boundary-{index}",
                        openalex_id=f"https://openalex.org/W{2000 + index}",
                        cited_by_count=10 - index,
                        is_open_access=True,
                        license="cc-by",
                        has_structured_fulltext=True,
                        providers=(self.name,),
                        matched_query_ids=(query.id,),
                    )
                    for index in range(6)
                )

        def acquire(item: PublicationCandidate, corpus: Path) -> AcquisitionOutcome:
            papers = corpus / "papers"
            papers.mkdir(parents=True, exist_ok=True)
            path = papers / f"{item.id.rsplit(':', 1)[-1]}.txt"
            text = "Discussion\nGreenland ice-sheet mass balance and polar snowfall were evaluated with satellite observations."
            path.write_text(text, encoding="utf-8")
            return AcquisitionOutcome(
                item.id,
                "acquired",
                "fixture",
                path.relative_to(corpus).as_posix(),
                "text/plain",
                len(text),
                len(text),
            )

        with tempfile.TemporaryDirectory() as temporary:
            scenarios = (
                ("cap", 4, 5, "full_text_cap_reached", 4),
                ("saturation", 6, 2, "evidence_saturation", 4),
            )
            for folder, maximum, patience, expected_reason, expected_acquired in scenarios:
                with self.subTest(expected_reason):
                    manager = ResearchRunManager(
                        Path(temporary) / folder,
                        providers=(BoundaryProvider(),),
                        acquirer=acquire,
                        openalex_api_key="fixture",
                    )
                    state = manager.run_sync(
                        question,
                        limits=ResearchLimits(
                            per_query=10,
                            max_selected=10,
                            initial_full_texts=2,
                            max_full_texts=maximum,
                            acquisition_batch_size=1,
                            saturation_patience=patience,
                            max_acquisition_attempts=10,
                            citation_seed_count=0,
                            citation_neighbors_per_seed=0,
                            citation_depth=0,
                        ),
                    )
                    stopping = state["result"]["research_run"]["adaptive_stopping"]
                    self.assertEqual(stopping["reason"], expected_reason)
                    self.assertEqual(state["progress"]["full_texts_acquired"], expected_acquired)
                    self.assertFalse(
                        state["result"]["answer_adequacy"]["can_answer_overall_question"]
                    )

    def test_acquisition_does_not_imply_fulltext_inclusion(self) -> None:
        class TwoPaperProvider:
            name = "two-paper"

            def search(self, query: SearchQuery, *, limit: int) -> tuple[PublicationCandidate, ...]:
                good = candidate(
                    "publication:good",
                    "Vegetation structure and goat foraging behaviour",
                    "Goat foraging changes with vegetation structure.",
                )
                mismatch = candidate(
                    "publication:mismatch",
                    "Goat foraging responses to vegetation structure",
                    "A study of goat browsing and vegetation structure.",
                )
                return tuple(
                    PublicationCandidate(
                        **{
                            **{field: getattr(item, field) for field in item.__dataclass_fields__},
                            "matched_query_ids": (query.id,),
                        }
                    )
                    for item in (good, mismatch)
                )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def acquire(item: PublicationCandidate, corpus: Path) -> AcquisitionOutcome:
                papers = corpus / "papers"
                papers.mkdir(parents=True, exist_ok=True)
                path = papers / f"{item.id.rsplit(':', 1)[-1]}.txt"
                text = (
                    "Goats forage across vegetation structure. Goat foraging behaviour responds to vegetation height."
                    if item.id.endswith("good")
                    else "Greenland ice-sheet mass balance and polar snowfall are evaluated with satellite observations."
                )
                path.write_text(text, encoding="utf-8")
                return AcquisitionOutcome(
                    item.id,
                    "acquired",
                    "fake",
                    path.relative_to(corpus).as_posix(),
                    "text/plain",
                    len(text),
                    len(text),
                )

            manager = ResearchRunManager(
                root,
                providers=(TwoPaperProvider(),),
                acquirer=acquire,
                openalex_api_key="test-key",
            )
            state = manager.run_sync(
                QUESTION,
                limits=ResearchLimits(
                    per_query=5, max_selected=5, max_full_texts=2, max_acquisition_attempts=2
                ),
            )
            self.assertEqual(state["progress"]["full_texts_acquired"], 2)
            self.assertEqual(state["progress"]["full_texts_included"], 1)
            decisions = {
                item["publication_id"]: item["decision"] for item in state["full_text_screening"]
            }
            self.assertEqual(decisions["publication:good"], "included")
            self.assertIn(decisions["publication:mismatch"], {"excluded", "uncertain"})
            manifest = json.loads((root / state["run_id"] / "corpus" / "manifest.json").read_text())
            self.assertEqual([item["id"] for item in manifest["documents"]], ["publication:good"])
            package = manager.download_research_package(state["run_id"])
            with zipfile.ZipFile(io.BytesIO(package.body)) as archive:
                papers = [name for name in archive.namelist() if name.startswith("publications/")]
                self.assertEqual(len(papers), 1)

    def test_default_fulltext_fetch_has_bounded_timeout_and_retries(self) -> None:
        calls = []

        def unavailable(request, timeout):
            calls.append(timeout)
            raise TimeoutError("unresponsive publisher")

        with (
            patch("sci_search.fulltext_acquisition.urlopen", side_effect=unavailable),
            patch(
                "sci_search.fulltext_acquisition.time.sleep",
                return_value=None,
            ),
            self.assertRaises(TimeoutError),
        ):
            _fetch_bytes("https://publisher.example/paper.pdf", {})
        self.assertEqual(calls, [30.0, 30.0])

    def test_greenland_change_question_is_planned_as_temporal_compound_subject(self) -> None:
        plan, queries = plan_search_queries(
            "What has been the change in precipitation over the Greenland Ice Sheet during the 21st century?"
        )
        self.assertEqual(plan.intent, "temporal_trend")
        self.assertEqual(plan.concepts, ("greenland ice sheet", "precipitation"))
        self.assertNotIn("over", plan.concepts)
        self.assertTrue(any("greenland ice sheet precipitation" in item.text for item in queries))
        self.assertTrue(
            any(
                item.purpose == "observed temporal evidence"
                and "observed trend time series" in item.text
                for item in queries
            )
        )

    def test_diagnostic_strategy_is_not_displaced_by_sensitivity_queries(self) -> None:
        _, queries = plan_search_queries(
            "How accurately do wearable devices detect atrial fibrillation compared with clinical ECG measurements?"
        )
        diagnostic = [item for item in queries if item.purpose == "diagnostic accuracy evidence"]
        self.assertEqual(len(diagnostic), 1)
        self.assertIn("sensitivity specificity reference standard validation", diagnostic[0].text)

    def test_explanatory_strategy_searches_for_moderators_and_meta_analysis(self) -> None:
        _, queries = plan_search_queries(
            "Why do studies report different effects of biochar application on crop yield?"
        )
        self.assertTrue(
            any(
                item.purpose == "explanatory synthesis evidence"
                and "heterogeneity moderators meta-analysis" in item.text
                for item in queries
            )
        )

    def test_crossref_retains_open_publisher_pdf_even_when_content_type_is_unspecified(
        self,
    ) -> None:
        item = {
            "title": ["Greenland Ice Sheet precipitation"],
            "DOI": "10.5194/tc-14-2253-2020",
            "URL": "https://doi.org/10.5194/tc-14-2253-2020",
            "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/"}],
            "link": [
                {
                    "URL": "https://tc.copernicus.org/articles/14/2253/2020/tc-14-2253-2020.pdf",
                    "content-type": "unspecified",
                }
            ],
        }
        result = _crossref_candidate(item, "query:test")
        self.assertTrue(result.is_open_access)
        self.assertTrue(result.has_pdf)
        self.assertEqual(result.full_text_url, item["link"][0]["URL"])

    def test_crossref_derives_copernicus_discussion_pdf(self) -> None:
        item = {
            "title": ["Greenland Ice Sheet precipitation"],
            "DOI": "10.5194/tc-2020-31",
            "URL": "https://doi.org/10.5194/tc-2020-31",
            "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/"}],
            "resource": {
                "primary": {
                    "URL": "https://tc.copernicus.org/articles/14/2253/2020/tc-14-2253-2020-discussion.html"
                }
            },
        }
        result = _crossref_candidate(item, "query:test")
        self.assertEqual(
            result.full_text_url,
            "https://tc.copernicus.org/articles/14/2253/2020/tc-14-2253-2020.pdf",
        )

    def test_rate_limited_provider_is_disabled_for_remaining_queries(self) -> None:
        class RateLimitedProvider:
            name = "rate_limited"

            def __init__(self) -> None:
                self.calls = 0

            def search(self, query: SearchQuery, *, limit: int) -> tuple[PublicationCandidate, ...]:
                self.calls += 1
                raise HTTPError("https://example.org", 429, "too many requests", {}, None)

        provider = RateLimitedProvider()
        queries = (
            SearchQuery("q1", "goat foraging", "subject"),
            SearchQuery("q2", "goat vegetation", "outcome"),
            SearchQuery("q3", "goat browsing", "synonym"),
        )
        found, logs = discover_with_providers(queries, (provider,), per_query=5)
        self.assertFalse(found)
        self.assertEqual(provider.calls, 1)
        self.assertEqual([entry["status"] for entry in logs], ["error", "skipped", "skipped"])
        self.assertTrue(all("HTTP 429" in str(entry["error"]) for entry in logs[1:]))

    def test_query_plan_uses_domain_aliases_and_multiple_strategies(self) -> None:
        plan, queries = plan_search_queries(QUESTION)
        self.assertEqual(plan.profile_id, "ecology")
        self.assertGreaterEqual(len(queries), 3)
        self.assertTrue(
            any(
                "sward structure" in item.text or "feeding behavior" in item.text
                for item in queries
            )
        )

    def test_deduplication_and_screening_require_domain_concept_coverage(self) -> None:
        plan, _ = plan_search_queries(QUESTION)
        first = candidate(
            "one",
            "Goat foraging across vegetation structures",
            "Goats browse different plant species.",
            doi="10.1/same",
        )
        duplicate = candidate(
            "two",
            "A duplicate",
            "A longer abstract about goat foraging and vegetation structure.",
            doi="https://doi.org/10.1/same",
        )
        irrelevant = candidate(
            "three",
            "Vegetation structure and elephant foraging",
            "Elephants browse woody vegetation.",
        )
        merged = merge_candidates((first, duplicate, irrelevant))
        self.assertEqual(len(merged), 2)
        screened = screen_candidates(merged, plan, limit=10)
        by_id = {item.id: item for item in screened}
        self.assertEqual(by_id["one"].screening_status, "selected")
        self.assertEqual(by_id["three"].screening_status, "excluded")

    def test_direct_title_with_processable_fulltext_is_not_blocked_by_missing_abstract(
        self,
    ) -> None:
        plan, _ = plan_search_queries(
            "Why do studies report different effects of biochar application on crop yield?"
        )
        direct = candidate(
            "meta",
            "Heterogeneous global crop yield response to biochar: a meta-regression analysis",
            "",
            doi="10.1/meta",
        )
        screened = screen_candidates((direct,), plan, limit=10)
        self.assertEqual(screened[0].screening_status, "selected")
        self.assertIn("abstract unavailable", screened[0].screening_reason)

    def test_preprint_and_final_article_sharing_a_pdf_count_once(self) -> None:
        cached_preprint = candidate(
            "preprint", "A preprint", "Greenland precipitation", doi="10.1/preprint"
        )
        cached_final = candidate(
            "final", "The final article", "Greenland precipitation", doi="10.1/final"
        )
        pdf = "https://publisher.example/articles/final.pdf"
        first = PublicationCandidate(
            **{
                field: (pdf if field == "full_text_url" else getattr(cached_preprint, field))
                for field in cached_preprint.__dataclass_fields__
            }
        )
        final = PublicationCandidate(
            **{
                field: (pdf if field == "full_text_url" else getattr(cached_final, field))
                for field in cached_final.__dataclass_fields__
            }
        )
        self.assertEqual(len(merge_candidates((cached_preprint, cached_final, first, final))), 1)

    def test_cached_preprint_and_final_sharing_document_fingerprint_count_once(self) -> None:
        first = candidate("preprint", "A preprint", "Greenland precipitation", doi="10.1/preprint")
        final = candidate("final", "The final article", "Greenland precipitation", doi="10.1/final")
        fingerprint = "documents/sha256-same-paper.pdf"
        records = tuple(
            PublicationCandidate(
                **{
                    field: (
                        fingerprint if field == "document_fingerprint" else getattr(item, field)
                    )
                    for field in item.__dataclass_fields__
                }
            )
            for item in (first, final)
        )
        self.assertEqual(len(merge_candidates(records)), 1)

    def test_relationship_screening_requires_the_primary_causal_subject(self) -> None:
        plan, _ = plan_search_queries(
            "What is the influence of El Niño on weather patterns in Europe?"
        )
        irrelevant = candidate(
            "weather-only",
            "European fire weather patterns",
            "Weather extremes and heatwaves occur across Europe.",
        )
        relevant = candidate(
            "enso-europe",
            "El Niño influence on European weather",
            "ENSO is associated with seasonal weather patterns in Europe.",
        )
        screened = {
            item.id: item for item in screen_candidates((irrelevant, relevant), plan, limit=10)
        }
        self.assertEqual(screened["weather-only"].screening_status, "excluded")
        self.assertIn("primary relationship subject", screened["weather-only"].screening_reason)
        self.assertEqual(screened["enso-europe"].screening_status, "selected")

    def test_openalex_mapping_reconstructs_abstract_and_never_exposes_key(self) -> None:
        captured: dict[str, str] = {}

        def fetch(base: str, params: dict[str, str]) -> dict[str, object]:
            captured.update(params)
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "doi": "https://doi.org/10.1000/example",
                        "display_name": "A study",
                        "publication_year": 2024,
                        "authorships": [
                            {
                                "author": {
                                    "id": "https://openalex.org/A123",
                                    "display_name": "Ada Author",
                                },
                                "institutions": [
                                    {
                                        "id": "https://openalex.org/I123",
                                        "display_name": "Utrecht University",
                                        "ror": "https://ror.org/04pp8hn57",
                                        "country_code": "NL",
                                    }
                                ],
                            }
                        ],
                        "ids": {"pmcid": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC123"},
                        "best_oa_location": {
                            "license": "cc-by",
                            "pdf_url": "https://example.org/a.pdf",
                        },
                        "open_access": {"is_oa": True},
                        "has_content": {"pdf": True, "grobid_xml": True},
                        "type": "article",
                        "is_retracted": False,
                        "cited_by_count": 3,
                        "abstract_inverted_index": {"Goats": [0], "browse": [1]},
                    }
                ]
            }

        result = OpenAlexProvider("secret-key", fetch_json=fetch).search(
            SearchQuery("q", "goats", "test"), limit=1
        )
        self.assertEqual(result[0].abstract, "Goats browse")
        self.assertEqual(result[0].pmcid, "PMC123")
        self.assertEqual(result[0].author_ids, ("https://openalex.org/A123",))
        self.assertEqual(result[0].institutions, ("Utrecht University",))
        self.assertEqual(result[0].institution_ids, ("https://ror.org/04pp8hn57",))
        self.assertEqual(captured["api_key"], "secret-key")
        self.assertNotIn("secret-key", repr(result[0]))

    def test_openalex_citation_expansion_records_edge_provenance(self) -> None:
        def fetch(base: str, params: dict[str, str]) -> dict[str, object]:
            if base.endswith("/W123"):
                return {"referenced_works": ["https://openalex.org/W10"]}
            title = "Vegetation structure and goat foraging evidence"
            item = {
                "id": "https://openalex.org/W10"
                if "openalex_id" in params.get("filter", "")
                else "https://openalex.org/W11",
                "doi": "https://doi.org/10.1000/ref"
                if "openalex_id" in params.get("filter", "")
                else "https://doi.org/10.1000/citing",
                "display_name": title,
                "publication_year": 2020,
                "authorships": [],
                "ids": {},
                "best_oa_location": {"pdf_url": "https://example.org/a.pdf"},
                "open_access": {"is_oa": True},
                "has_content": {"pdf": True},
                "type": "article",
                "is_retracted": False,
                "cited_by_count": 2,
                "abstract_inverted_index": {"Goat": [0], "foraging": [1]},
            }
            return {"results": [item]}

        provider = OpenAlexProvider("secret-key", fetch_json=fetch)
        seed = candidate("seed", "Seed", "Goat foraging", doi="10.1000/seed")
        found, log = expand_citation_network((seed,), (provider,), per_seed=4)
        self.assertEqual(len(found), 2)
        self.assertTrue(all(item.citation_relations for item in found))
        self.assertEqual(log[0]["kind"], "citation_expansion")

    def test_tei_conversion_preserves_sections_and_paragraphs(self) -> None:
        xml = b"""<TEI xmlns='http://www.tei-c.org/ns/1.0'><text><body><div><head>Results</head><p>Goats selected taller vegetation during the dry season.</p></div></body></text></TEI>"""
        text = tei_xml_to_text(xml)
        self.assertIn("## Results", text)
        self.assertIn("Goats selected taller vegetation", text)

    def test_acquisition_decompresses_openalex_tei_and_preserves_result_section(self) -> None:
        source = candidate(
            "publication:xml",
            "Vegetation and goat foraging",
            "Goat foraging changes with vegetation structure.",
        )
        paragraph = "Goats selected taller woody vegetation during the dry season. " * 25
        xml = f"<html><text xmlns='http://www.tei-c.org/ns/1.0'><div>Results<p>{paragraph}</p></div></text></html>".encode()

        def fetch(url: str, params: dict[str, str]) -> tuple[bytes, str]:
            self.assertNotIn("test-key", url)
            self.assertEqual(params["api_key"], "test-key")
            return gzip.compress(xml), "application/gzip"

        with tempfile.TemporaryDirectory() as temporary:
            outcome = acquire_full_text(
                source, Path(temporary), openalex_api_key="test-key", fetch_bytes=fetch
            )
            self.assertEqual(outcome.status, "acquired")
            self.assertEqual(outcome.source, "openalex_grobid")
            saved = (Path(temporary) / str(outcome.relative_path)).read_text(encoding="utf-8")
            self.assertIn("<html>", saved)
            self.assertEqual(Path(str(outcome.relative_path)).suffix, ".xml")
            self.assertIn("Goats selected taller woody vegetation", saved)

    def test_structured_acquisition_preserves_pdf_as_download_artifact(self) -> None:
        base = candidate(
            "publication:dual",
            "Vegetation and goat foraging",
            "Goat foraging changes with vegetation structure.",
        )
        source = PublicationCandidate(
            **{
                field: (True if field == "has_pdf" else getattr(base, field))
                for field in base.__dataclass_fields__
            }
        )
        paragraph = "Goats selected taller woody vegetation during the dry season. " * 25
        xml = f"<html><text xmlns='http://www.tei-c.org/ns/1.0'><div><head>Results</head><p>{paragraph}</p></div></text></html>".encode()

        def fetch(url: str, params: dict[str, str]) -> tuple[bytes, str]:
            if url.endswith(".pdf"):
                return b"%PDF-1.7\noriginal-open-access-pdf", "application/pdf"
            return xml, "application/xml"

        with tempfile.TemporaryDirectory() as temporary:
            outcome = acquire_full_text(
                source, Path(temporary), openalex_api_key="test-key", fetch_bytes=fetch
            )
            self.assertEqual(Path(str(outcome.relative_path)).suffix, ".xml")
            self.assertEqual(Path(str(outcome.download_relative_path)).suffix, ".pdf")
            self.assertEqual(outcome.download_source, "openalex_pdf")
            self.assertTrue(
                (Path(temporary) / str(outcome.download_relative_path))
                .read_bytes()
                .startswith(b"%PDF-")
            )

    def test_acquisition_uses_explicit_open_publisher_pdf(self) -> None:
        base = candidate(
            "publication:publisher-pdf",
            "Greenland precipitation",
            "Greenland precipitation trends.",
        )
        source = PublicationCandidate(
            **{
                field: (
                    "https://tc.copernicus.org/example.pdf"
                    if field == "full_text_url"
                    else False
                    if field == "has_structured_fulltext"
                    else None
                    if field == "pmcid"
                    else getattr(base, field)
                )
                for field in base.__dataclass_fields__
            }
        )

        def fetch(url: str, params: dict[str, str]) -> tuple[bytes, str]:
            self.assertEqual(url, source.full_text_url)
            self.assertFalse(params)
            return b"%PDF-1.7\nopen-access-paper", "application/pdf"

        with tempfile.TemporaryDirectory() as temporary:
            outcome = acquire_full_text(
                source, Path(temporary), openalex_api_key="test-key", fetch_bytes=fetch
            )
            self.assertEqual(outcome.status, "acquired")
            self.assertEqual(outcome.source, "publisher_oa_pdf")
            self.assertEqual(outcome.download_source, "publisher_oa_pdf")

    def test_complete_run_persists_candidate_ledger_and_grounded_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def acquire(item: PublicationCandidate, corpus: Path) -> AcquisitionOutcome:
                papers = corpus / "papers"
                papers.mkdir(parents=True, exist_ok=True)
                path = papers / "relevant.txt"
                text = "## Results\n\nGoat foraging behaviour changed with vegetation structure: goats selected taller woody plant species during the dry season.\n"
                path.write_text(text, encoding="utf-8")
                return AcquisitionOutcome(
                    item.id,
                    "acquired",
                    "fake",
                    "papers/relevant.txt",
                    "text/plain",
                    len(text),
                    len(text),
                )

            manager = ResearchRunManager(
                root, providers=(FakeProvider(),), acquirer=acquire, openalex_api_key="test-key"
            )
            state = manager.run_sync(
                QUESTION,
                limits=ResearchLimits(
                    per_query=2, max_selected=3, max_full_texts=1, max_acquisition_attempts=1
                ),
            )
            self.assertEqual(state["status"], "complete")
            self.assertEqual(state["progress"]["full_texts_acquired"], 1)
            self.assertEqual(state["progress"]["full_texts_included"], 1)
            self.assertEqual(state["full_text_screening"][0]["decision"], "included")
            self.assertTrue(state["result"]["evidence"])
            self.assertTrue(
                state["result"]["synthesis"]["validation"]["all_claims_are_exact_source_text"]
            )
            diagnostics = state["result"]["pipeline_diagnostics"]
            self.assertEqual(diagnostics["schema_version"], "sci_search_pipeline_diagnostics_v1")
            self.assertEqual(diagnostics["acquisition"]["acquired"], 1)
            self.assertEqual(diagnostics["analysis"]["contributing_publications"], 1)
            self.assertEqual(state["pipeline_stages"][-1]["stage"], "complete")
            self.assertTrue(all(item["completed_at"] for item in state["pipeline_stages"]))
            evidence = state["result"]["evidence"][0]
            full_text = manager.full_text(state["run_id"], evidence["publication_id"])
            self.assertIn(evidence["passage"], full_text["content"])
            follow_up = manager.investigate(state["run_id"], "What limitations are reported?")
            self.assertEqual(follow_up["corpus_id"], f"research:{state['run_id']}")
            self.assertIn(QUESTION, follow_up["contextualized_question"])
            self.assertTrue(follow_up["evidence"])
            artifact = (root / state["run_id"] / "discovery.json").read_text(encoding="utf-8")
            self.assertNotIn("test-key", artifact)

            single = manager.download_publication(state["run_id"], "publication:relevant")
            self.assertEqual(single.content_type, "text/plain")
            self.assertIn(b"Goat foraging behaviour", single.body)
            bundle = manager.download_publications(state["run_id"])
            with zipfile.ZipFile(io.BytesIO(bundle.body)) as archive:
                self.assertIn("manifest.json", archive.namelist())
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(manifest["publication_count"], 1)
                self.assertEqual(manifest["documents"][0]["doi"], "10.1234/relevant")
            review_html = manager.download_literature_review(state["run_id"], "html")
            self.assertIn(b"Cited literature review", review_html.body)
            self.assertEqual(review_html.content_type, "text/html; charset=utf-8")
            review_json = manager.download_literature_review(state["run_id"], "json")
            self.assertIn(b"cited_literature_review_v1", review_json.body)
            review_pdf = manager.download_literature_review(state["run_id"], "pdf")
            self.assertEqual(review_pdf.content_type, "application/pdf")
            self.assertTrue(review_pdf.body.startswith(b"%PDF-"))
            package = manager.download_research_package(state["run_id"])
            self.assertTrue(package.filename.endswith("complete-research-package.zip"))
            with zipfile.ZipFile(io.BytesIO(package.body)) as archive:
                names = set(archive.namelist())
                self.assertIn("literature-review.pdf", names)
                self.assertIn("literature-review.html", names)
                self.assertIn("data/literature-review.json", names)
                self.assertIn("data/research-landscape.json", names)
                self.assertIn("data/full-text-screening.json", names)
                self.assertIn("data/study-matrix.json", names)
                self.assertIn("data/publications-manifest.json", names)
                self.assertTrue(any(name.startswith("publications/") for name in names))
                self.assertTrue(archive.read("literature-review.pdf").startswith(b"%PDF-"))
                screening = json.loads(archive.read("data/full-text-screening.json"))
                self.assertEqual(screening[0]["decision"], "included")
                matrix = json.loads(archive.read("data/study-matrix.json"))
                self.assertEqual(matrix["studies"][0]["publication_id"], "publication:relevant")

            excluded = manager.review_candidate(
                state["run_id"], "publication:relevant", "exclude", "wrong population"
            )
            self.assertFalse(excluded["result"]["evidence"])
            empty_package = manager.download_research_package(state["run_id"])
            with zipfile.ZipFile(io.BytesIO(empty_package.body)) as archive:
                self.assertEqual(
                    json.loads(archive.read("data/publications-manifest.json"))[
                        "publication_count"
                    ],
                    0,
                )
            with self.assertRaises(KeyError):
                manager.download_publication(state["run_id"], "publication:relevant")
            supplied = (
                "## Results\n\nGoat foraging behaviour changed with vegetation structure. " * 20
            ).encode()
            restored = manager.add_authorized_full_text(
                state["run_id"],
                "publication:relevant",
                filename="paper.txt",
                content_base64=base64.b64encode(supplied).decode(),
                authorization_confirmed=True,
            )
            self.assertTrue(restored["result"]["evidence"])
            self.assertEqual(
                restored["review_decisions"]["publication:relevant"]["decision"], "include"
            )
            self.assertEqual(restored["authorized_uploads"][0]["authorization_confirmed"], True)
            restored_bundle = manager.download_publications(
                state["run_id"], ["publication:relevant"]
            )
            self.assertTrue(restored_bundle.filename.endswith("1-publications.zip"))

    def test_local_env_loader_does_not_override_process_values_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".env.local"
            path.write_text("SCI_SEARCH_TEST_VALUE=from-file\n", encoding="utf-8")
            import os

            original = os.environ.get("SCI_SEARCH_TEST_VALUE")
            try:
                os.environ["SCI_SEARCH_TEST_VALUE"] = "from-process"
                configured = load_env_file(path)
                self.assertIn("SCI_SEARCH_TEST_VALUE", configured)
                self.assertEqual(os.environ["SCI_SEARCH_TEST_VALUE"], "from-process")
            finally:
                if original is None:
                    os.environ.pop("SCI_SEARCH_TEST_VALUE", None)
                else:
                    os.environ["SCI_SEARCH_TEST_VALUE"] = original

    def test_legacy_loader_imports_only_mistral_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "sci-search"
            legacy = root / "sci-graph"
            project.mkdir()
            legacy.mkdir()
            (legacy / ".env.local").write_text(
                "MISTRAL_API_KEY=test-mistral\nOPENAI_API_KEY=must-not-load\ngraphdb_password=must-not-load\n",
                encoding="utf-8",
            )
            import os

            originals = {
                key: os.environ.get(key)
                for key in ("MISTRAL_API_KEY", "OPENAI_API_KEY", "graphdb_password")
            }
            try:
                for key in originals:
                    os.environ.pop(key, None)
                self.assertTrue(load_legacy_mistral_key(project))
                self.assertEqual(os.environ["MISTRAL_API_KEY"], "test-mistral")
                self.assertNotIn("OPENAI_API_KEY", os.environ)
                self.assertNotIn("graphdb_password", os.environ)
            finally:
                for key, value in originals.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
