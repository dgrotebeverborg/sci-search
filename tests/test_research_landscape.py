from __future__ import annotations

import unittest

from sci_search.research_landscape import build_research_landscape


class ResearchLandscapeTests(unittest.TestCase):
    def test_landscape_counts_publications_once_and_keeps_coverage_visible(self) -> None:
        candidates = []
        for index, year in enumerate((2020, 2023, 2023, 2024, 2024, 2025, 2025)):
            candidates.append(
                {
                    "id": f"work:{index}",
                    "title": f"Iron storage performance experiment {index}",
                    "year": year,
                    "authors": ["Ada Author", "Ada Author"],
                    "author_ids": ["https://openalex.org/A123", "https://openalex.org/A123"],
                    "institutions": ["Utrecht University", "Utrecht University"],
                    "institution_ids": ["https://ror.org/04pp8hn57", "https://ror.org/04pp8hn57"],
                    "affiliations": ["Department of X, Utrecht University, Utrecht, Netherlands"],
                    "publication_type": "article",
                    "providers": ["openalex"],
                    "screening_status": "selected",
                    "cited_by_count": index,
                }
            )
        candidates.append(
            {
                "id": "raw-only",
                "title": "Unresolved raw affiliation",
                "year": 2026,
                "authors": ["B. Researcher"],
                "institutions": [],
                "affiliations": ["Lab, Example University, Example City"],
                "publication_type": "article",
                "providers": ["crossref"],
                "screening_status": "unavailable",
                "cited_by_count": 0,
            }
        )
        payload = {
            "question": "How is iron storage changing?",
            "evidence": [],
            "research_run": {"candidates": candidates, "active_publication_ids": ["work:0"]},
        }

        landscape = build_research_landscape(payload)

        self.assertEqual(landscape["coverage"]["records"], 8)
        self.assertEqual(landscape["coverage"]["with_canonical_organizations"], 7)
        self.assertEqual(
            landscape["top_organizations"][0],
            {
                "organization_id": "https://ror.org/04pp8hn57",
                "name": "Utrecht University",
                "publications": 7,
            },
        )
        self.assertEqual(
            landscape["top_authors"][0],
            {
                "author_id": "https://openalex.org/A123",
                "name": "Ada Author",
                "publications": 7,
            },
        )
        self.assertEqual(landscape["trend_method"]["baseline_from"], 2020)
        self.assertEqual(landscape["trend_method"]["recent_to"], 2025)
        self.assertTrue(
            any(item["classification"] == "emerging" for item in landscape["title_term_signals"])
        )
        self.assertIn(2026, {item["year"] for item in landscape["publication_timeline"]})
        self.assertTrue(any("incomplete 2026" in item for item in landscape["limitations"]))

    def test_local_corpus_gets_an_honest_metadata_only_landscape(self) -> None:
        landscape = build_research_landscape(
            {
                "question": "A question",
                "publications": [
                    {
                        "id": "p1",
                        "title": "One paper",
                        "year": 2021,
                        "authors": ["One Author"],
                        "document_type": "article",
                    }
                ],
            }
        )
        self.assertEqual(landscape["population_definition"], "configured_full_text_corpus")
        self.assertEqual(landscape["coverage"]["full_texts_acquired"], 1)
        self.assertEqual(landscape["top_organizations"], [])
        self.assertTrue(
            any("organization rankings are omitted" in item for item in landscape["limitations"])
        )


if __name__ == "__main__":
    unittest.main()
