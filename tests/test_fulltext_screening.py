from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sci_search.discovery import PublicationCandidate
from sci_search.fulltext_acquisition import AcquisitionOutcome
from sci_search.fulltext_screening import screen_acquired_documents, screen_full_text
from sci_search.question_planning import plan_question


def candidate(identifier: str, title: str, abstract: str = "") -> PublicationCandidate:
    return PublicationCandidate(
        id=identifier,
        title=title,
        abstract=abstract,
        year=2024,
        doi=None,
        authors=(),
        publication_type="article",
        source_url=None,
    )


class FullTextScreeningTests(unittest.TestCase):
    def test_qualified_wearable_alias_preserves_the_requested_body_location(self) -> None:
        question = (
            "How accurately do wrist-worn wearable devices detect atrial fibrillation "
            "compared with clinical ECG measurements?"
        )
        for location, expected in (("chest-patch", "excluded"), ("wrist-worn", "included")):
            with self.subTest(location=location):
                title = f"Validation of {location} wearable ECG for atrial fibrillation detection"
                text = (
                    f"We evaluated a {location} wearable ECG for atrial fibrillation detection. "
                    f"The {location} wearable ECG detected atrial fibrillation with 95% "
                    "sensitivity against clinical ECG measurements."
                )
                item = candidate("device", title, text)
                decision = screen_full_text(question, plan_question(question), item, text)
                self.assertEqual(decision.decision, expected)

    def test_wearable_ecg_synonyms_are_screened_with_all_requested_subjects(self) -> None:
        question = (
            "How accurately do wearable devices detect atrial fibrillation "
            "compared with clinical ECG measurements?"
        )
        plan = plan_question(question)
        for device in ("wearable ECG", "wearable electrocardiogram"):
            with self.subTest(device=device):
                title = f"Validation of {device} for atrial fibrillation detection"
                text = (
                    f"We evaluated a {device} for atrial fibrillation detection. "
                    f"The {device} detected atrial fibrillation with 95% sensitivity "
                    "against clinical ECG measurements."
                )
                item = candidate(
                    "device",
                    title,
                    f"We validated {device} detection of atrial fibrillation "
                    "against clinical ECG measurements.",
                )
                decision = screen_full_text(question, plan, item, text)
                self.assertEqual(decision.decision, "included")
                self.assertFalse(decision.researcher_override)

    def test_wearable_ecg_alias_does_not_replace_arrhythmia_or_reference_scope(self) -> None:
        question = (
            "How accurately do wearable devices detect atrial fibrillation "
            "compared with clinical ECG measurements?"
        )
        plan = plan_question(question)
        for title, text in (
            (
                "Wearable ECG comfort evaluation",
                "Wearable ECG comfort was measured against clinical ECG measurements. "
                "Participants found the wearable ECG comfortable.",
            ),
            (
                "Wearable ECG atrial fibrillation detection",
                "The wearable ECG detected atrial fibrillation. "
                "Wearable ECG atrial fibrillation alerts were recorded without validation.",
            ),
            (
                "Clinical ECG atrial fibrillation detection",
                "Clinical ECG measurements detected atrial fibrillation. "
                "Clinical ECG measurements confirmed atrial fibrillation in patients.",
            ),
        ):
            with self.subTest(title=title):
                decision = screen_full_text(question, plan, candidate("control", title), text)
                self.assertNotEqual(decision.decision, "included")

    def test_unreadable_document_is_a_local_screening_decision_not_a_run_failure(self) -> None:
        question = "How does vegetation structure affect goat foraging behaviour?"
        item = candidate("scanned", "Vegetation structure and goat foraging behaviour")
        with tempfile.TemporaryDirectory() as temporary:
            corpus = Path(temporary)
            path = corpus / "papers" / "scanned.pdf"
            path.parent.mkdir()
            path.write_bytes(b"%PDF-1.4\n" + b"0" * 600)
            outcome = AcquisitionOutcome(
                item.id,
                "acquired",
                "fixture",
                "papers/scanned.pdf",
                "application/pdf",
                609,
                0,
            )
            with patch(
                "sci_search.corpus._document_text", side_effect=ValueError(f"OCR required: {path}")
            ):
                active, decisions = screen_acquired_documents(
                    question,
                    plan_question(question),
                    corpus,
                    [(item, outcome)],
                )
        self.assertEqual(active, [])
        self.assertEqual(decisions[0]["decision"], "unreadable")
        self.assertNotIn(str(corpus), decisions[0]["parse_error"])

    def test_greenland_question_excludes_unrelated_goat_document(self) -> None:
        question = "What is the observed change in size of the Greenland Ice Sheet from 2001 to the present?"
        item = candidate(
            "goat",
            "Understanding natural behavior to improve dairy goat management systems",
            "We observed present-day behaviour in dairy goats.",
        )
        text = (
            "Dairy goats were observed in present housing systems. " * 8
        ) + "\nReferences\nGreenland Ice Sheet report."
        decision = screen_full_text(question, plan_question(question), item, text)
        self.assertEqual(decision.decision, "excluded")
        self.assertIn("primary subject", decision.reason)

    def test_temporal_greenland_study_is_included(self) -> None:
        question = "What is the observed change in size of the Greenland Ice Sheet from 2001 to the present?"
        item = candidate(
            "greenland",
            "Observed Greenland Ice Sheet mass changes since 2001",
            "Satellite observations quantify Greenland Ice Sheet change over time.",
        )
        text = (
            "The Greenland Ice Sheet was observed annually from 2001 to 2024. "
            "Our time series shows the Greenland ice-sheet mass has decreased over the period."
        )
        decision = screen_full_text(question, plan_question(question), item, text)
        self.assertEqual(decision.decision, "included")
        self.assertIn("greenland ice sheet", decision.matched_groups)
        self.assertIn("change across time", decision.matched_groups)

    def test_primary_subject_without_requested_relationship_is_background(self) -> None:
        question = "How does vegetation structure affect goat foraging behaviour?"
        item = candidate("goat", "General health of domestic goats", "A veterinary study of goats.")
        text = "Goats received veterinary examinations. Goat health and housing were recorded throughout the study."
        decision = screen_full_text(question, plan_question(question), item, text)
        self.assertEqual(decision.decision, "background")
        self.assertGreaterEqual(decision.supporting_groups_required, 1)

    def test_researcher_override_is_explicit_and_auditable(self) -> None:
        question = "How does vegetation structure affect goat foraging behaviour?"
        item = candidate("override", "Unclear record")
        decision = screen_full_text(
            question,
            plan_question(question),
            item,
            "No matching concepts occur here.",
            researcher_decision={
                "decision": "include",
                "reason": "Verified directly by researcher",
            },
        )
        self.assertEqual(decision.decision, "included")
        self.assertTrue(decision.researcher_override)
        self.assertIn("Verified directly", decision.reason)


if __name__ == "__main__":
    unittest.main()


def test_background_is_retained_as_context_but_not_active_evidence():
    from sci_search.study_matrix import active_from_screening

    item = candidate("context", "Background study")
    assert (
        active_from_screening(
            [(item, object())], [{"publication_id": "context", "decision": "background"}]
        )
        == []
    )
