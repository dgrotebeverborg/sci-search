from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sci_search.discovery import PublicationCandidate
from sci_search.fulltext_acquisition import AcquisitionOutcome
from sci_search.mistral_analysis import MistralAnalyzer
from sci_search.question_planning import plan_question
from sci_search.study_matrix import (
    adjudicate_uncertain_studies,
    apply_adjudication,
    build_study_matrix,
)


class StudyMatrixTests(unittest.TestCase):
    question = "What round-trip efficiencies have been reported for iron-air batteries?"

    def _candidate(self) -> PublicationCandidate:
        return PublicationCandidate(
            id="paper-1",
            title="Round-trip efficiency of an iron-air battery",
            abstract="",
            year=2025,
            doi="10.1/example",
            authors=("A. Author",),
            publication_type="article",
            source_url=None,
        )

    def _matrix(self, root: Path):
        text = (
            "Methods\n\nWe tested an iron-air battery cell at room temperature using a galvanostatic protocol.\n\n"
            "Results\n\nThe measured round-trip efficiency was 70% at a current density of 20 mA cm-2."
        )
        papers = root / "papers"
        papers.mkdir()
        (papers / "paper.txt").write_text(text, encoding="utf-8")
        outcome = AcquisitionOutcome(
            "paper-1",
            "acquired",
            "test",
            "papers/paper.txt",
            "text/plain",
            len(text),
            len(text),
            None,
        )
        screening = [
            {
                "publication_id": "paper-1",
                "decision": "uncertain",
                "reason": "review",
                "content_sha256": "hash",
            }
        ]
        matrix = build_study_matrix(
            self.question,
            plan_question(self.question),
            root,
            [(self._candidate(), outcome)],
            screening,
        )
        return text, matrix

    def test_cards_retain_exact_passage_offsets_and_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            text, matrix = self._matrix(Path(directory))
            card = matrix["studies"][0]
            self.assertTrue(card["selected_passages"])
            for passage in card["selected_passages"]:
                self.assertEqual(
                    text[passage["start_char"] : passage["end_char"]], passage["passage"]
                )
            self.assertTrue(
                any(item["status"] == "supported" for item in card["dimension_coverage"])
            )
            self.assertTrue(card["extractive_fields"]["results"])

    def test_quote_validated_adjudication_can_include_complete_study(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, matrix = self._matrix(Path(directory))
            card = matrix["studies"][0]
            findings = []
            for dimension in card["dimension_coverage"]:
                passage = next(
                    (
                        item
                        for item in card["selected_passages"]
                        if dimension["dimension_id"] in item["matched_dimension_ids"]
                    ),
                    card["selected_passages"][0],
                )
                findings.append(
                    {
                        "dimension_id": dimension["dimension_id"],
                        "status": "supported",
                        "passage_id": passage["id"],
                        "quote": passage["passage"][:40],
                    }
                )
            response = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "decisions": [
                                        {
                                            "publication_id": "paper-1",
                                            "decision": "include",
                                            "reason": "all dimensions quoted",
                                            "dimension_findings": findings,
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            }
            analyzer = MistralAnalyzer("secret", complete_json=lambda body, headers: response)
            adjudication = adjudicate_uncertain_studies(self.question, matrix, analyzer)
            self.assertEqual(adjudication["decisions"][0]["decision"], "include")
            screened = apply_adjudication([card["screening"]], adjudication)
            self.assertEqual(screened[0]["decision"], "included")

    def test_hallucinated_quote_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, matrix = self._matrix(Path(directory))
            card = matrix["studies"][0]
            dimension = card["dimension_coverage"][0]
            response = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "decisions": [
                                        {
                                            "publication_id": "paper-1",
                                            "decision": "include",
                                            "reason": "claimed support",
                                            "dimension_findings": [
                                                {
                                                    "dimension_id": dimension["dimension_id"],
                                                    "status": "supported",
                                                    "passage_id": card["selected_passages"][0][
                                                        "id"
                                                    ],
                                                    "quote": "This sentence was invented by the model.",
                                                }
                                            ],
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            }
            analyzer = MistralAnalyzer("secret", complete_json=lambda body, headers: response)
            result = adjudicate_uncertain_studies(self.question, matrix, analyzer)
            self.assertFalse(result["decisions"])
            self.assertIn("not found", result["rejected_records"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
