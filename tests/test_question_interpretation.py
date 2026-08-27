from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from sci_search.mistral_analysis import MistralAnalyzer
from sci_search.question_interpretation import interpret_question


class QuestionInterpretationTests(unittest.TestCase):
    def test_deterministic_fallback_exposes_scope_without_answering(self) -> None:
        with patch.dict("os.environ", {"MISTRAL_API_KEY": ""}):
            brief = interpret_question(
                "How does vegetation structure affect goat foraging behaviour?"
            )
        self.assertEqual(brief["profile_id"], "ecology")
        self.assertIn("goat", brief["concepts"])
        self.assertIn(brief["ambiguity"], {"clear", "minor"})
        self.assertEqual(brief["method"], "deterministic_question_interpretation_v1")

    def test_model_interpretation_is_structured_and_keeps_plan_provenance(self) -> None:
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "interpreted_question": "How does vegetation structure influence goat diet selection and movement?",
                                "objective": "Synthesize evidence relating vegetation structure to goat foraging outcomes.",
                                "evidence_scope": ["field experiments", "observational studies"],
                                "assumptions": ["Foraging includes diet selection and movement."],
                                "exclusions": ["Studies without goats."],
                                "ambiguity": "minor",
                                "clarification_question": "Should diet selection or movement receive priority?",
                            }
                        )
                    }
                }
            ]
        }
        analyzer = MistralAnalyzer(
            "secret", model="brief-model", complete_json=lambda body, headers: response
        )
        brief = interpret_question(
            "How does vegetation structure affect goat foraging behaviour?",
            analyzer=analyzer,
        )
        self.assertEqual(brief["provider"], "mistral")
        self.assertEqual(brief["model"], "brief-model")
        self.assertEqual(brief["profile_id"], "ecology")
        self.assertEqual(brief["ambiguity"], "minor")
        self.assertNotIn("secret", json.dumps(brief))


if __name__ == "__main__":
    unittest.main()
