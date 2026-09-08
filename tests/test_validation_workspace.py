from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sci_search.validation_workspace import ValidationWorkspace


class ValidationWorkspaceTests(unittest.TestCase):
    def _annotate(
        self,
        workspace: ValidationWorkspace,
        case_id: str,
        payload: dict[str, object],
        *,
        reviewer: str = "Researcher A",
    ) -> dict[str, object]:
        return workspace.annotate(
            case_id,
            {
                **payload,
                "reviewer": reviewer,
                "independent_review": True,
                "blinded_to_system_output": True,
            },
        )

    def _workspace(self, root: Path) -> ValidationWorkspace:
        cases = [
            {
                "id": f"case-{index}",
                "domain": "test",
                "baseline_run_id": "baseline",
                "question": f"Test question {index}?",
                "required_answer_components": ["important result"],
                "silver_publications": (
                    [{"doi": "10.1/relevant", "relevance": "direct", "reason": "known relevant"}]
                    if index == 0
                    else []
                ),
            }
            for index in range(10)
        ]
        specification = {
            "schema_version": "sci_search_validation_benchmark_v1",
            "name": "test",
            "version": 1,
            "validation_status": "silver_seed_pending_researcher_validation",
            "purpose": "test",
            "minimum_samples": {
                key: 1
                for key in (
                    "relevant_paper_recall",
                    "fulltext_screening_precision",
                    "fulltext_screening_recall",
                    "evidence_result_correctness",
                    "numerical_value_correctness",
                    "unit_correctness",
                    "provenance_correctness",
                    "context_association_correctness",
                    "important_conclusion_coverage",
                    "unsupported_answer_assertions",
                    "hallucinated_values",
                    "missing_important_conclusions",
                )
            },
            "cases": cases,
        }
        spec_path = root / "benchmark.json"
        spec_path.write_text(json.dumps(specification), encoding="utf-8")
        run = root / "runs" / "baseline"
        run.mkdir(parents=True)
        papers = run / "corpus" / "papers"
        papers.mkdir(parents=True)
        (papers / "paper.txt").write_text("The measured value was 70%." * 30, encoding="utf-8")
        run_payload = {
            "run_id": "baseline",
            "status": "complete",
            "candidates": [
                {
                    "id": "publication:one",
                    "title": "Relevant paper",
                    "doi": "10.1/relevant",
                    "year": 2024,
                    "screening_status": "selected",
                    "screening_reason": "topic match",
                }
            ],
            "acquisitions": [
                {
                    "publication_id": "publication:one",
                    "status": "acquired",
                    "relative_path": "papers/paper.txt",
                }
            ],
            "full_text_screening": [
                {
                    "publication_id": "publication:one",
                    "decision": "included",
                    "reason": "full text match",
                }
            ],
            "result": {
                "answer_summary": "The supported result is reported.",
                "summary_evidence_ids": ["evidence:one"],
                "answer_adequacy": {"can_answer_overall_question": True},
                "evidence": [
                    {
                        "id": "evidence:one",
                        "publication_id": "publication:one",
                        "passage": "The measured value was 70%.",
                        "section": "Results",
                        "page": 2,
                        "evidence_type": "experiment",
                        "study_design": "laboratory",
                    }
                ],
                "research_run": {"records_retrieved": 1, "full_texts_acquired": 1},
            },
        }
        (run / "run.json").write_text(json.dumps(run_payload), encoding="utf-8")
        return ValidationWorkspace(spec_path, root / "annotations", (root / "runs",))

    def test_silver_seed_is_not_scored_as_researcher_gold(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self._workspace(Path(temporary))
            overview = workspace.overview()
            self.assertEqual(len(overview["cases"]), 10)
            self.assertEqual(overview["aggregate_scorecard"]["evaluable_cases"], 0)
            case = workspace.case("case-0")
            seeded = next(
                item for item in case["publications"] if item.get("doi") == "10.1/relevant"
            )
            self.assertEqual(
                seeded["annotation"]["review_state"], "silver_seed_pending_confirmation"
            )
            self.assertEqual(case["scorecard"]["status"], "not_evaluable")

    def test_confirmed_annotations_produce_scorecard_and_gold_eligibility(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self._workspace(Path(temporary))
            detail = workspace.case("case-0")
            assertion = detail["assertions"][0]["assertion_id"]
            conclusion = detail["important_conclusions"][0]["conclusion_id"]
            self._annotate(
                workspace,
                "case-0",
                {"kind": "publication", "id": "publication:one", "label": "relevant"},
            )
            self._annotate(
                workspace, "case-0", {"kind": "assertion", "id": assertion, "support": "supported"}
            )
            self._annotate(
                workspace,
                "case-0",
                {
                    "kind": "evidence",
                    "id": "evidence:one",
                    "result_correct": True,
                    "value_correct": True,
                    "unit_correct": True,
                    "provenance_correct": True,
                    "context_correct": True,
                },
            )
            self._annotate(
                workspace, "case-0", {"kind": "conclusion", "id": conclusion, "covered": True}
            )
            self._annotate(
                workspace,
                "case-0",
                {"kind": "answerability", "id": "overall", "answerable": True},
            )
            complete = self._annotate(
                workspace, "case-0", {"kind": "case", "status": "complete", "notes": "checked"}
            )
            self.assertEqual(complete["scorecard"]["status"], "passed")
            self.assertTrue(complete["scorecard"]["gold_eligible"])
            metrics = {item["id"]: item for item in complete["scorecard"]["metrics"]}
            self.assertEqual(metrics["provenance_correctness"]["value"], 1.0)
            self.assertEqual(metrics["unsupported_answer_assertions"]["value"], 0)
            import io
            import zipfile

            with zipfile.ZipFile(io.BytesIO(workspace.export_package())) as archive:
                gold = json.loads(archive.read("gold/case-0.json"))
            self.assertEqual(gold["schema_version"], "researcher_gold_v1")
            self.assertEqual(gold["must_retrieve_publications"], ["publication:one"])

    def test_provenance_and_unsupported_assertions_are_hard_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self._workspace(Path(temporary))
            detail = workspace.case("case-0")
            assertion = detail["assertions"][0]["assertion_id"]
            self._annotate(
                workspace,
                "case-0",
                {"kind": "publication", "id": "publication:one", "label": "relevant"},
            )
            self._annotate(
                workspace,
                "case-0",
                {
                    "kind": "assertion",
                    "id": assertion,
                    "support": "unsupported",
                    "reason": "source does not support the statement",
                },
            )
            failed = self._annotate(
                workspace,
                "case-0",
                {
                    "kind": "evidence",
                    "id": "evidence:one",
                    "provenance_correct": False,
                    "context_correct": True,
                    "reason": "offset points to the wrong passage",
                },
            )
            self.assertEqual(failed["scorecard"]["status"], "failed")
            self.assertEqual(
                set(failed["scorecard"]["hard_gate_failures"]),
                {
                    "provenance_correctness",
                    "unsupported_answer_assertions",
                },
            )

    def test_researcher_can_add_a_relevant_publication_missing_from_retrieval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self._workspace(Path(temporary))
            detail = self._annotate(
                workspace,
                "case-0",
                {
                    "kind": "publication",
                    "id": "doi:10.1/missed",
                    "doi": "10.1/missed",
                    "title": "Important missed paper",
                    "label": "relevant",
                },
            )
            missed = next(
                item
                for item in detail["publications"]
                if item["publication_id"] == "doi:10.1/missed"
            )
            self.assertFalse(missed["retrieved"])
            metric = next(
                item
                for item in detail["scorecard"]["metrics"]
                if item["id"] == "relevant_paper_recall"
            )
            self.assertEqual(metric["value"], 0.0)

    def test_silver_or_system_output_cannot_be_promoted_without_named_independent_review(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self._workspace(Path(temporary))
            with self.assertRaisesRegex(ValueError, "named researcher"):
                workspace.annotate(
                    "case-0",
                    {"kind": "publication", "id": "publication:one", "label": "relevant"},
                )
            with self.assertRaisesRegex(ValueError, "independent"):
                workspace.annotate(
                    "case-0",
                    {
                        "kind": "publication",
                        "id": "publication:one",
                        "label": "relevant",
                        "reviewer": "Researcher A",
                        "independent_review": False,
                        "blinded_to_system_output": True,
                    },
                )

    def test_explicit_gold_labels_capture_blinding_revisions_and_disagreement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self._workspace(Path(temporary))
            self._annotate(
                workspace,
                "case-0",
                {
                    "kind": "counterevidence",
                    "id": "counter-1",
                    "label": "present",
                    "evidence_ids": ["evidence:one"],
                },
            )
            self._annotate(
                workspace,
                "case-0",
                {"kind": "distinction", "id": "method-scale", "label": "required"},
            )
            self._annotate(
                workspace,
                "case-0",
                {"kind": "answerability", "id": "overall", "answerable": True},
            )
            self._annotate(
                workspace,
                "case-0",
                {"kind": "answerability", "id": "overall", "answerable": False},
                reviewer="Researcher B",
            )

            detail = workspace.case("case-0")
            answerability = detail["annotation"]["answerability_labels"]["overall"]
            self.assertEqual(len(answerability["review_revisions"]), 2)
            self.assertTrue(answerability["review_revisions"][0]["blinded_to_system_output"])
            disagreement = next(
                item
                for item in detail["scorecard"]["metrics"]
                if item["id"] == "reviewer_disagreement_rate"
            )
            self.assertEqual(disagreement["value"], 1.0)

    def test_gold_label_schema_declares_required_scientific_label_groups(self) -> None:
        schema = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "benchmarks"
                / "researcher_gold_v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        required = set(schema["required"])
        self.assertTrue(
            {
                "must_retrieve_publications",
                "must_exclude_publications",
                "key_conclusions",
                "counterevidence",
                "required_distinctions",
                "answerability",
                "review_revisions",
            }
            <= required
        )

    def test_validation_full_text_and_export_are_auditable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self._workspace(Path(temporary))
            document = workspace.full_text("case-0", "publication:one")
            self.assertIn("measured value", document["content"])
            import io
            import zipfile

            with zipfile.ZipFile(io.BytesIO(workspace.export_package())) as archive:
                self.assertIn("scorecard.json", archive.namelist())
                self.assertIn("benchmark.json", archive.namelist())
                self.assertIn("annotations/case-0.json", archive.namelist())


if __name__ == "__main__":
    unittest.main()
