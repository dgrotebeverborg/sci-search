"""Researcher-owned validation records and full-pipeline scorecards."""

from __future__ import annotations

import hashlib
import io
import json
import threading
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sci_search.corpus import _document_text

DEFAULT_THRESHOLDS = {
    "relevant_paper_recall": 0.85,
    "fulltext_screening_precision": 0.90,
    "fulltext_screening_recall": 0.85,
    "evidence_result_correctness": 0.90,
    "numerical_value_correctness": 0.95,
    "unit_correctness": 0.98,
    "provenance_correctness": 1.0,
    "context_association_correctness": 0.90,
    "important_conclusion_coverage": 0.80,
    "unsupported_answer_assertions": 0,
    "hallucinated_values": 0,
    "missing_important_conclusions": 0,
    "reviewer_disagreement_rate": 1.0,
}

DEFAULT_MINIMUM_SAMPLES = {
    "relevant_paper_recall": 3,
    "fulltext_screening_precision": 3,
    "fulltext_screening_recall": 3,
    "evidence_result_correctness": 3,
    "numerical_value_correctness": 3,
    "unit_correctness": 3,
    "provenance_correctness": 3,
    "context_association_correctness": 3,
    "important_conclusion_coverage": 3,
    "unsupported_answer_assertions": 1,
    "hallucinated_values": 1,
    "missing_important_conclusions": 1,
    "reviewer_disagreement_rate": 1,
}


class ValidationWorkspace:
    """Persist annotations separately from immutable research-run artifacts."""

    def __init__(
        self, specification: Path, annotation_root: Path, run_roots: tuple[Path, ...]
    ) -> None:
        self.specification_path = specification
        self.annotation_root = annotation_root
        self.run_roots = run_roots
        self.annotation_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.specification = self._load_specification()
        self._seed_annotations()
        self._ensure_proposed_negative_controls()

    def overview(self) -> dict[str, Any]:
        cases = []
        for case in self.specification["cases"]:
            annotation = self._annotation(str(case["id"]))
            detail = self._case_detail(case, annotation, include_records=False)
            cases.append(
                {
                    "id": case["id"],
                    "domain": case["domain"],
                    "question": case["question"],
                    "baseline_run_id": case["baseline_run_id"],
                    "status": annotation["status"],
                    "confirmed_publications": sum(
                        item.get("review_state") == "researcher_confirmed"
                        for item in annotation["publication_labels"].values()
                    ),
                    "confirmed_evidence": sum(
                        item.get("review_state") == "researcher_confirmed"
                        for item in annotation["evidence_labels"].values()
                    ),
                    "scorecard": detail["scorecard"],
                }
            )
        aggregate = aggregate_scorecards([item["scorecard"] for item in cases])
        return {
            "schema_version": "sci_search_validation_workspace_v1",
            "benchmark": {
                key: self.specification.get(key)
                for key in (
                    "name",
                    "version",
                    "validation_status",
                    "purpose",
                )
            },
            "thresholds": self.specification.get("thresholds") or DEFAULT_THRESHOLDS,
            "cases": cases,
            "aggregate_scorecard": aggregate,
            "governance": self.specification.get("governance") or {},
            "integrity": self.integrity_report(),
        }

    def integrity_report(self) -> dict[str, Any]:
        replay_manifest_path = next(
            (
                root / "replay-manifest.json"
                for root in self.run_roots
                if (root / "replay-manifest.json").is_file()
            ),
            None,
        )
        replay_manifest = (
            json.loads(replay_manifest_path.read_text(encoding="utf-8"))
            if replay_manifest_path
            else {}
        )
        replay_cases = {str(item.get("run_id")): item for item in replay_manifest.get("cases", [])}
        case_rows = []
        for case in self.specification["cases"]:
            annotation = self._annotation(str(case["id"]))
            negative_controls = sum(
                item.get("label") == "irrelevant"
                and item.get("review_state")
                in {
                    "silver_seed_pending_confirmation",
                    "system_proposed_negative_pending_confirmation",
                    "researcher_confirmed",
                }
                for item in annotation["publication_labels"].values()
            )
            replay = replay_cases.get(str(case["baseline_run_id"]))
            case_rows.append(
                {
                    "case_id": case["id"],
                    "negative_controls": negative_controls,
                    "replay_available": replay is not None,
                    "replay_run_sha256": (replay or {}).get("replay_run_sha256"),
                }
            )
        current_fingerprint = _source_code_fingerprint()
        replay_fingerprint = replay_manifest.get("code_fingerprint")
        return {
            "specification_sha256": hashlib.sha256(
                self.specification_path.read_bytes()
            ).hexdigest(),
            "replay_manifest_available": bool(replay_manifest),
            "replay_version": replay_manifest.get("version"),
            "replay_code_fingerprint": replay_fingerprint,
            "current_code_fingerprint": current_fingerprint,
            "current_code_matches_replay": bool(
                replay_fingerprint and replay_fingerprint == current_fingerprint
            ),
            "all_cases_have_replay": all(item["replay_available"] for item in case_rows),
            "all_cases_have_negative_controls": all(
                item["negative_controls"] >= 1 for item in case_rows
            ),
            "cases": case_rows,
        }

    def case(self, case_id: str) -> dict[str, Any]:
        case = self._case_spec(case_id)
        return self._case_detail(case, self._annotation(case_id), include_records=True)

    def full_text(self, case_id: str, publication_id: str) -> dict[str, Any]:
        case = self._case_spec(case_id)
        run, run_root = self._load_run_with_root(str(case["baseline_run_id"]))
        outcomes = {
            str(item.get("publication_id")): item
            for item in run.get("acquisitions", [])
            if item.get("status") == "acquired" and item.get("relative_path")
        }
        outcome = outcomes.get(publication_id)
        if outcome is None:
            raise KeyError(f"full text is unavailable in the validation snapshot: {publication_id}")
        corpus = run_root / str(case["baseline_run_id"]) / "corpus"
        path = (corpus / str(outcome["relative_path"])).resolve()
        path.relative_to(corpus.resolve())
        if not path.is_file():
            raise FileNotFoundError(path)
        candidate = next(
            (item for item in run.get("candidates", []) if str(item.get("id")) == publication_id),
            {},
        )
        return {
            "case_id": case_id,
            "publication_id": publication_id,
            "title": candidate.get("title") or publication_id,
            "source_document": path.name,
            "content": _document_text(path),
            "replay_run_id": case["baseline_run_id"],
        }

    def export_package(self, guide_path: Path | None = None) -> bytes:
        output = io.BytesIO()
        overview = self.overview()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "scorecard.json", json.dumps(overview, indent=2, ensure_ascii=False) + "\n"
            )
            archive.writestr("benchmark.json", self.specification_path.read_bytes())
            for case in self.specification["cases"]:
                case_id = str(case["id"])
                detail = self.case(case_id)
                archive.writestr(
                    f"annotations/{case_id}.json", self._annotation_path(case_id).read_bytes()
                )
                archive.writestr(
                    f"cases/{case_id}.json",
                    json.dumps(detail, indent=2, ensure_ascii=False) + "\n",
                )
                if detail["scorecard"]["gold_eligible"]:
                    gold = self._gold_record(case_id)
                    validate_gold_record(gold)
                    archive.writestr(
                        f"gold/{case_id}.json",
                        json.dumps(gold, indent=2, ensure_ascii=False) + "\n",
                    )
            replay_manifest = next(
                (
                    root / "replay-manifest.json"
                    for root in self.run_roots
                    if (root / "replay-manifest.json").is_file()
                ),
                None,
            )
            if replay_manifest:
                archive.writestr("replay-manifest.json", replay_manifest.read_bytes())
            if guide_path and guide_path.is_file():
                archive.writestr("RESEARCHER_VALIDATION_GUIDE.md", guide_path.read_bytes())
        return output.getvalue()

    def annotate(self, case_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        case = self._case_spec(case_id)
        annotation = self._annotation(case_id)
        kind = str(payload.get("kind") or "")
        identifier = str(payload.get("id") or "").strip()
        review = _researcher_review(payload)
        reviewer = str(review["reviewer"])
        if kind == "publication":
            if not identifier:
                raise ValueError("publication id is required")
            label = str(payload.get("label") or "")
            if label not in {"relevant", "background", "irrelevant", "uncertain"}:
                raise ValueError("invalid publication relevance label")
            reason = _clean(payload.get("reason"), 1000)
            if label in {"irrelevant", "uncertain"} and not reason:
                raise ValueError(
                    "a reason is required for irrelevant or uncertain publication labels"
                )
            values = {
                "label": label,
                "selection_label": {
                    "relevant": "must_retrieve",
                    "background": "contextual",
                    "irrelevant": "must_exclude",
                    "uncertain": "uncertain",
                }[label],
                "reason": reason,
                "title": _clean(payload.get("title"), 500),
                "doi": _clean(payload.get("doi"), 200).lower(),
                "year": int(payload["year"]) if str(payload.get("year") or "").isdigit() else None,
            }
            annotation["publication_labels"][identifier] = _reviewed_label(
                annotation["publication_labels"].get(identifier), values, label, review
            )
        elif kind == "evidence":
            if not identifier:
                raise ValueError("evidence id is required")
            flags = {
                field: _optional_bool(payload.get(field))
                for field in (
                    "result_correct",
                    "value_correct",
                    "unit_correct",
                    "provenance_correct",
                    "context_correct",
                )
            }
            reason = _clean(payload.get("reason"), 1000)
            if any(value is False for value in flags.values()) and not reason:
                raise ValueError("a reason is required when an evidence field is incorrect")
            values = {
                **flags,
                "reason": reason,
            }
            annotation["evidence_labels"][identifier] = _reviewed_label(
                annotation["evidence_labels"].get(identifier), values, flags, review
            )
        elif kind == "assertion":
            if not identifier:
                raise ValueError("assertion id is required")
            support = str(payload.get("support") or "")
            if support not in {"supported", "unsupported", "unclear"}:
                raise ValueError("invalid assertion support label")
            reason = _clean(payload.get("reason"), 1000)
            if support != "supported" and not reason:
                raise ValueError("a reason is required for unsupported or unclear assertions")
            values = {
                "support": support,
                "reason": reason,
            }
            annotation["assertion_labels"][identifier] = _reviewed_label(
                annotation["assertion_labels"].get(identifier), values, support, review
            )
        elif kind == "conclusion":
            if not identifier:
                raise ValueError("conclusion id is required")
            covered = _required_bool(payload.get("covered"))
            reason = _clean(payload.get("reason"), 1000)
            if not covered and not reason:
                raise ValueError("a reason is required when an important conclusion is missing")
            values = {
                "covered": covered,
                "reason": reason,
            }
            annotation["conclusion_labels"][identifier] = _reviewed_label(
                annotation["conclusion_labels"].get(identifier), values, covered, review
            )
        elif kind == "counterevidence":
            label = str(payload.get("label") or "")
            if not identifier or label not in {"present", "absent", "uncertain"}:
                raise ValueError("counterevidence requires an id and a valid label")
            values = {
                "label": label,
                "evidence_ids": _string_list(payload.get("evidence_ids")),
                "reason": _clean(payload.get("reason"), 1000),
            }
            annotation["counterevidence_labels"][identifier] = _reviewed_label(
                annotation["counterevidence_labels"].get(identifier), values, label, review
            )
        elif kind == "distinction":
            label = str(payload.get("label") or "")
            if not identifier or label not in {"required", "not_required", "unclear"}:
                raise ValueError("distinction requires an id and a valid label")
            values = {"label": label, "reason": _clean(payload.get("reason"), 1000)}
            annotation["distinction_labels"][identifier] = _reviewed_label(
                annotation["distinction_labels"].get(identifier), values, label, review
            )
        elif kind == "answerability":
            if not identifier:
                raise ValueError("answerability id is required")
            answerable = _required_bool(payload.get("answerable"))
            values = {
                "answerable": answerable,
                "reason": _clean(payload.get("reason"), 1000),
            }
            annotation["answerability_labels"][identifier] = _reviewed_label(
                annotation["answerability_labels"].get(identifier), values, answerable, review
            )
        elif kind == "case":
            status = str(payload.get("status") or "")
            if status not in {"in_progress", "complete"}:
                raise ValueError("case status must be in_progress or complete")
            if status == "complete":
                completion = self._completion_requirements(case, annotation)
                if not completion["ready"]:
                    raise ValueError(
                        "case review is incomplete: " + "; ".join(completion["missing"])
                    )
            annotation["status"] = status
            annotation["notes"] = _clean(payload.get("notes"), 4000)
            annotation["reviewer"] = reviewer
            annotation["review_revisions"] = [
                *annotation.get("review_revisions", []),
                {**review, "decision": status},
            ]
        else:
            raise ValueError(
                "annotation kind must be publication, evidence, assertion, conclusion, "
                "counterevidence, distinction, answerability, or case"
            )
        annotation["updated_at"] = _now()
        self._write_annotation(case_id, annotation)
        return self._case_detail(case, annotation, include_records=True)

    def _gold_record(self, case_id: str) -> dict[str, Any]:
        annotation = self._annotation(case_id)
        publications = annotation["publication_labels"]
        return {
            "schema_version": "researcher_gold_v1",
            "case_id": case_id,
            "must_retrieve_publications": sorted(
                key
                for key, item in publications.items()
                if item.get("selection_label") == "must_retrieve"
                and item.get("review_state") == "researcher_confirmed"
            ),
            "must_exclude_publications": sorted(
                key
                for key, item in publications.items()
                if item.get("selection_label") == "must_exclude"
                and item.get("review_state") == "researcher_confirmed"
            ),
            "key_conclusions": annotation["conclusion_labels"],
            "counterevidence": annotation["counterevidence_labels"],
            "required_distinctions": annotation["distinction_labels"],
            "answerability": annotation["answerability_labels"],
            "review_revisions": annotation.get("review_revisions", []),
        }

    def _case_detail(
        self, case: dict[str, Any], annotation: dict[str, Any], *, include_records: bool
    ) -> dict[str, Any]:
        run = self._load_run(str(case["baseline_run_id"]))
        result = run.get("result") if isinstance(run.get("result"), dict) else {}
        publications = _publication_records(run, annotation)
        evidence = _evidence_records(result, annotation)
        assertions = _assertion_records(result, annotation)
        conclusions = _conclusion_records(case, annotation)
        scorecard = score_case(
            case,
            run,
            annotation,
            publications,
            evidence,
            assertions,
            conclusions,
            self.specification.get("thresholds") or DEFAULT_THRESHOLDS,
            self.specification.get("minimum_samples") or DEFAULT_MINIMUM_SAMPLES,
        )
        payload = {
            "schema_version": "sci_search_validation_case_v1",
            "case": case,
            "annotation": annotation,
            "scorecard": scorecard,
            "completion": self._completion_requirements(case, annotation),
            "run_summary": {
                "run_id": run.get("run_id"),
                "status": run.get("status"),
                "records_retrieved": (result.get("research_run") or {}).get(
                    "records_retrieved", len(run.get("candidates", []))
                ),
                "full_texts_acquired": (result.get("research_run") or {}).get(
                    "full_texts_acquired", 0
                ),
                "evidence_passages": len(result.get("evidence", [])),
                "answer_withheld": not bool(
                    (result.get("answer_adequacy") or {}).get("can_answer_overall_question", True)
                ),
            },
        }
        if include_records:
            payload.update(
                {
                    "publications": publications,
                    "evidence": evidence,
                    "assertions": assertions,
                    "important_conclusions": conclusions,
                }
            )
        return payload

    def _load_specification(self) -> dict[str, Any]:
        payload = json.loads(self.specification_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "sci_search_validation_benchmark_v1":
            raise ValueError("unsupported validation benchmark schema")
        cases = payload.get("cases")
        if not isinstance(cases, list) or len(cases) != 10:
            raise ValueError("validation benchmark must contain exactly ten cases")
        ids = [str(item.get("id")) for item in cases]
        if len(set(ids)) != len(ids):
            raise ValueError("validation benchmark case ids must be unique")
        return payload

    def _seed_annotations(self) -> None:
        for case in self.specification["cases"]:
            case_id = str(case["id"])
            if self._annotation_path(case_id).is_file():
                continue
            publications = {}
            for item in case.get("silver_publications", []):
                key = _reference_key(item)
                publications[key] = {
                    "label": {
                        "direct": "relevant",
                        "contextual": "background",
                        "distractor": "irrelevant",
                    }.get(item.get("relevance"), "uncertain"),
                    "reason": item.get("reason") or "",
                    "review_state": "silver_seed_pending_confirmation",
                    "source": "source-checked silver reference set",
                }
            annotation = {
                "schema_version": "sci_search_researcher_annotation_v1",
                "case_id": case_id,
                "status": "pending",
                "reviewer": None,
                "notes": "",
                "publication_labels": publications,
                "evidence_labels": {},
                "assertion_labels": {},
                "conclusion_labels": {},
                "counterevidence_labels": {},
                "distinction_labels": {},
                "answerability_labels": {},
                "review_revisions": [],
                "created_at": _now(),
                "updated_at": _now(),
            }
            self._write_annotation(case_id, annotation)

    def _ensure_proposed_negative_controls(self) -> None:
        """Give every case review candidates without claiming they are gold negatives."""
        for case in self.specification["cases"]:
            case_id = str(case["id"])
            annotation = self._annotation(case_id)
            if any(
                item.get("label") == "irrelevant"
                for item in annotation["publication_labels"].values()
            ):
                continue
            run = self._load_run(str(case["baseline_run_id"]))
            excluded = [
                item
                for item in run.get("candidates", [])
                if item.get("screening_status") == "excluded"
                and float(item.get("concept_coverage") or 0) <= 0.5
            ]
            excluded.sort(
                key=lambda item: (
                    float(item.get("concept_coverage") or 0),
                    float(item.get("relevance_score") or 0),
                )
            )
            changed = False
            for item in excluded[:2]:
                publication_id = str(item.get("id"))
                if not publication_id or publication_id in annotation["publication_labels"]:
                    continue
                annotation["publication_labels"][publication_id] = {
                    "label": "irrelevant",
                    "reason": "Low-coverage excluded record proposed as a negative control; researcher confirmation required.",
                    "title": item.get("title") or "",
                    "doi": str(item.get("doi") or "").lower(),
                    "year": item.get("year"),
                    "review_state": "system_proposed_negative_pending_confirmation",
                    "source": "deterministic negative-control proposal",
                }
                changed = True
            if changed:
                annotation["updated_at"] = _now()
                self._write_annotation(case_id, annotation)

    def _annotation(self, case_id: str) -> dict[str, Any]:
        with self._lock:
            annotation = json.loads(self._annotation_path(case_id).read_text(encoding="utf-8"))
        for name in (
            "counterevidence_labels",
            "distinction_labels",
            "answerability_labels",
            "review_revisions",
        ):
            annotation.setdefault(name, {} if name.endswith("_labels") else [])
        return annotation

    def _write_annotation(self, case_id: str, payload: dict[str, Any]) -> None:
        path = self._annotation_path(case_id)
        temporary = path.with_suffix(".tmp")
        with self._lock:
            temporary.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            temporary.replace(path)

    def _annotation_path(self, case_id: str) -> Path:
        safe = "".join(
            character for character in case_id if character.isalnum() or character in "-_"
        )
        if safe != case_id:
            raise ValueError("invalid validation case id")
        return self.annotation_root / f"{safe}.json"

    def _case_spec(self, case_id: str) -> dict[str, Any]:
        case = next(
            (item for item in self.specification["cases"] if item.get("id") == case_id), None
        )
        if case is None:
            raise KeyError(f"unknown validation case: {case_id}")
        return case

    def _load_run(self, run_id: str) -> dict[str, Any]:
        return self._load_run_with_root(run_id)[0]

    def _load_run_with_root(self, run_id: str) -> tuple[dict[str, Any], Path]:
        for root in self.run_roots:
            path = root / run_id / "run.json"
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8")), root
        raise FileNotFoundError(f"baseline run is unavailable: {run_id}")

    def _completion_requirements(
        self, case: dict[str, Any], annotation: dict[str, Any]
    ) -> dict[str, Any]:
        run = self._load_run(str(case["baseline_run_id"]))
        result = run.get("result") if isinstance(run.get("result"), dict) else {}
        acquired = {
            str(item.get("publication_id"))
            for item in run.get("acquisitions", [])
            if item.get("status") == "acquired"
        }
        required_publications = set(acquired)
        required_publications.update(
            _reference_key(item) for item in case.get("silver_publications", [])
        )
        confirmed_keys = {
            key
            for key, item in annotation["publication_labels"].items()
            if item.get("review_state") == "researcher_confirmed"
        }
        candidate_dois = {
            str(item.get("id")): f"doi:{str(item.get('doi')).lower()}"
            for item in run.get("candidates", [])
            if item.get("doi")
        }
        confirmed_publications = set(confirmed_keys)
        confirmed_publications.update(
            pub_id for pub_id, doi in candidate_dois.items() if doi in confirmed_keys
        )
        confirmed_publications.update(
            doi for pub_id, doi in candidate_dois.items() if pub_id in confirmed_keys
        )
        assertions = _assertion_records(result, annotation)
        evidence = _evidence_records(result, annotation)
        conclusions = _conclusion_records(case, annotation)
        missing = []
        if required_publications and not required_publications <= confirmed_publications:
            missing.append(
                f"{len(required_publications - confirmed_publications)} required publication decisions"
            )
        elif not required_publications and not confirmed_publications:
            missing.append("at least one publication decision")
        unchecked_assertions = sum(
            not (item.get("annotation") or {}).get("review_state") == "researcher_confirmed"
            for item in assertions
        )
        if unchecked_assertions:
            missing.append(f"{unchecked_assertions} answer assertions")
        unchecked_evidence = sum(
            not (item.get("annotation") or {}).get("review_state") == "researcher_confirmed"
            or any(
                (item.get("annotation") or {}).get(field) is None
                for field in ("result_correct", "provenance_correct", "context_correct")
            )
            for item in evidence
        )
        if unchecked_evidence:
            missing.append(f"{unchecked_evidence} evidence records")
        unchecked_conclusions = sum(
            not (item.get("annotation") or {}).get("review_state") == "researcher_confirmed"
            for item in conclusions
        )
        if unchecked_conclusions:
            missing.append(f"{unchecked_conclusions} important conclusions")
        if not any(
            item.get("review_state") == "researcher_confirmed"
            for item in annotation["answerability_labels"].values()
        ):
            missing.append("overall answerability judgment")
        return {
            "ready": not missing,
            "missing": missing,
            "required_publications": len(required_publications),
            "assertions": len(assertions),
            "evidence_records": len(evidence),
            "important_conclusions": len(conclusions),
        }


def score_case(
    case: dict[str, Any],
    run: dict[str, Any],
    annotation: dict[str, Any],
    publications: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    assertions: list[dict[str, Any]],
    conclusions: list[dict[str, Any]],
    thresholds: dict[str, Any],
    minimum_samples: dict[str, int],
) -> dict[str, Any]:
    confirmed_publications = [
        item
        for item in publications
        if (item.get("annotation") or {}).get("review_state") == "researcher_confirmed"
    ]
    gold_relevant = [
        item
        for item in confirmed_publications
        if item["annotation"]["label"] in {"relevant", "background"}
    ]
    retrieved_relevant = [item for item in gold_relevant if item.get("retrieved")]
    predicted_included = [
        item
        for item in confirmed_publications
        if item.get("predicted_inclusion") in {"included", "background"}
    ]
    correct_included = [
        item
        for item in predicted_included
        if item["annotation"]["label"] in {"relevant", "background"}
    ]
    screened_relevant = [
        item
        for item in gold_relevant
        if item.get("predicted_inclusion") in {"included", "background"}
    ]
    confirmed_evidence = [
        item
        for item in evidence
        if (item.get("annotation") or {}).get("review_state") == "researcher_confirmed"
    ]
    confirmed_assertions = [
        item
        for item in assertions
        if (item.get("annotation") or {}).get("review_state") == "researcher_confirmed"
    ]
    confirmed_conclusions = [
        item
        for item in conclusions
        if (item.get("annotation") or {}).get("review_state") == "researcher_confirmed"
    ]
    stats = {
        "relevant_paper_recall": (len(retrieved_relevant), len(gold_relevant)),
        "fulltext_screening_precision": (len(correct_included), len(predicted_included)),
        "fulltext_screening_recall": (len(screened_relevant), len(gold_relevant)),
        "evidence_result_correctness": _flag_counts(confirmed_evidence, "result_correct"),
        "numerical_value_correctness": _flag_counts(confirmed_evidence, "value_correct"),
        "unit_correctness": _flag_counts(confirmed_evidence, "unit_correct"),
        "provenance_correctness": _flag_counts(confirmed_evidence, "provenance_correct"),
        "context_association_correctness": _flag_counts(confirmed_evidence, "context_correct"),
        "important_conclusion_coverage": _flag_counts(confirmed_conclusions, "covered"),
        "unsupported_answer_assertions": (
            sum(
                item["annotation"].get("support") == "unsupported" for item in confirmed_assertions
            ),
            len(confirmed_assertions),
        ),
        "hallucinated_values": (
            sum((item["annotation"].get("value_correct") is False) for item in confirmed_evidence),
            len(
                [
                    item
                    for item in confirmed_evidence
                    if item["annotation"].get("value_correct") is not None
                ]
            ),
        ),
        "missing_important_conclusions": (
            sum(item["annotation"].get("covered") is False for item in confirmed_conclusions),
            len(confirmed_conclusions),
        ),
        "reviewer_disagreement_rate": _reviewer_disagreement(annotation),
    }
    metric_rows = []
    count_metrics = {
        "unsupported_answer_assertions",
        "hallucinated_values",
        "missing_important_conclusions",
    }
    for name, (numerator, denominator) in stats.items():
        threshold = thresholds.get(name, DEFAULT_THRESHOLDS[name])
        evaluable = denominator >= int(minimum_samples.get(name, 1))
        value = (
            numerator
            if name in count_metrics and evaluable
            else _ratio(numerator, denominator)
            if evaluable
            else None
        )
        passed = (
            None
            if not evaluable
            else value <= threshold
            if name == "unsupported_answer_assertions"
            else value >= threshold
        )
        if name in {"hallucinated_values", "missing_important_conclusions"} and evaluable:
            passed = value <= threshold
        metric_rows.append(
            {
                "id": name,
                "value": value,
                "threshold": threshold,
                "minimum_sample": minimum_samples.get(name, 1),
                "numerator": numerator,
                "denominator": denominator,
                "evaluable": evaluable,
                "passed": passed,
                "confidence_interval_95": _wilson(numerator, denominator)
                if evaluable and name not in count_metrics
                else None,
            }
        )
    hard_ids = {"provenance_correctness", "unsupported_answer_assertions"}
    hard_failures = [
        item["id"] for item in metric_rows if item["id"] in hard_ids and item["passed"] is False
    ]
    evaluated = [item for item in metric_rows if item["evaluable"]]
    return {
        "status": "not_evaluable"
        if not evaluated
        else "failed"
        if hard_failures or any(item["passed"] is False for item in evaluated)
        else "passed",
        "annotation_status": annotation.get("status"),
        "metrics": metric_rows,
        "hard_gate_failures": hard_failures,
        "counts": {
            "confirmed_publications": len(confirmed_publications),
            "confirmed_evidence": len(confirmed_evidence),
            "confirmed_assertions": len(confirmed_assertions),
            "confirmed_conclusions": len(confirmed_conclusions),
        },
        "gold_eligible": annotation.get("status") == "complete"
        and not hard_failures
        and bool(evaluated)
        and _has_independent_named_reviews(annotation)
        and all(
            item["evaluable"]
            for item in metric_rows
            if item["id"]
            not in {
                "numerical_value_correctness",
                "unit_correctness",
                "hallucinated_values",
                "reviewer_disagreement_rate",
            }
        ),
    }


def aggregate_scorecards(scorecards: list[dict[str, Any]]) -> dict[str, Any]:
    values: dict[str, list[float]] = {}
    totals: dict[str, list[int]] = {}
    hard_failures: set[str] = set()
    for card in scorecards:
        hard_failures.update(card.get("hard_gate_failures") or [])
        for metric in card.get("metrics", []):
            if metric.get("value") is not None:
                values.setdefault(str(metric["id"]), []).append(float(metric["value"]))
                totals.setdefault(str(metric["id"]), [0, 0])
                totals[str(metric["id"])][0] += int(metric.get("numerator") or 0)
                totals[str(metric["id"])][1] += int(metric.get("denominator") or 0)
    count_metrics = {
        "unsupported_answer_assertions",
        "hallucinated_values",
        "missing_important_conclusions",
    }
    return {
        "cases": len(scorecards),
        "evaluable_cases": sum(card.get("status") != "not_evaluable" for card in scorecards),
        "complete_cases": sum(card.get("annotation_status") == "complete" for card in scorecards),
        "hard_gate_failures": sorted(hard_failures),
        "macro_average": {
            name: round(sum(items) / len(items), 4) for name, items in values.items()
        },
        "micro_average": {
            name: numerator if name in count_metrics else _ratio(numerator, denominator)
            for name, (numerator, denominator) in totals.items()
        },
        "release_ready": bool(scorecards) and all(card.get("gold_eligible") for card in scorecards),
    }


def _publication_records(run: dict[str, Any], annotation: dict[str, Any]) -> list[dict[str, Any]]:
    result = run.get("result") if isinstance(run.get("result"), dict) else {}
    research = result.get("research_run") if isinstance(result.get("research_run"), dict) else {}
    candidates = run.get("candidates") or research.get("candidates") or []
    acquisitions = {
        str(item.get("publication_id"))
        for item in (run.get("acquisitions") or research.get("acquisitions") or [])
        if item.get("status") == "acquired"
    }
    screening = {
        str(item.get("publication_id")): item
        for item in (run.get("full_text_screening") or research.get("full_text_screening") or [])
    }
    by_reference: dict[str, dict[str, Any]] = {}
    records = []
    for candidate in candidates:
        publication_id = str(candidate.get("id"))
        doi = str(candidate.get("doi") or "").lower()
        annotation_item = annotation["publication_labels"].get(publication_id) or annotation[
            "publication_labels"
        ].get(f"doi:{doi}")
        record = {
            "publication_id": publication_id,
            "title": candidate.get("title"),
            "doi": candidate.get("doi"),
            "year": candidate.get("year"),
            "retrieved": True,
            "full_text_acquired": publication_id in acquisitions,
            "predicted_inclusion": (screening.get(publication_id) or {}).get("decision")
            or candidate.get("screening_status"),
            "screening_reason": (screening.get(publication_id) or {}).get("reason")
            or candidate.get("screening_reason"),
            "annotation": annotation_item,
        }
        records.append(record)
        if doi:
            by_reference[f"doi:{doi}"] = record
    # Keep known references that retrieval missed visible; recall needs a denominator.
    for key, item in annotation["publication_labels"].items():
        if key.startswith("doi:") and key not in by_reference:
            records.append(
                {
                    "publication_id": key,
                    "title": item.get("title") or key.removeprefix("doi:"),
                    "doi": item.get("doi") or key.removeprefix("doi:"),
                    "year": item.get("year"),
                    "retrieved": False,
                    "full_text_acquired": False,
                    "predicted_inclusion": "not_retrieved",
                    "screening_reason": "Reference was not found in the baseline run.",
                    "annotation": item,
                }
            )
    # Acquired records and labelled controls first, then the strongest candidates.
    records.sort(
        key=lambda item: (
            not bool(item.get("annotation")),
            not item["full_text_acquired"],
            not item["retrieved"],
            str(item.get("title")),
        )
    )
    priority = [item for item in records if item.get("annotation") or item["full_text_acquired"]]
    filler = [item for item in records if item not in priority]
    return priority + filler[: max(0, 30 - len(priority))]


def _evidence_records(result: dict[str, Any], annotation: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for item in result.get("evidence", []):
        evidence_id = str(item.get("id"))
        records.append(
            {
                "evidence_id": evidence_id,
                "publication_id": item.get("publication_id"),
                "passage": item.get("passage"),
                "section": item.get("section"),
                "page": item.get("page"),
                "study_design": item.get("study_design"),
                "evidence_type": item.get("evidence_type"),
                "annotation": annotation["evidence_labels"].get(evidence_id),
            }
        )
    return records


def _assertion_records(result: dict[str, Any], annotation: dict[str, Any]) -> list[dict[str, Any]]:
    ai = result.get("ai_analysis") if isinstance(result.get("ai_analysis"), dict) else {}
    raw = []
    if isinstance(ai.get("answer"), dict):
        raw.append(("answer", ai["answer"]))
    for category in (
        "claims",
        "agreements",
        "contradictions",
        "method_differences",
        "limitations",
        "uncertainties",
        "assumptions",
        "knowledge_gaps",
    ):
        raw.extend((category, item) for item in ai.get(category, []) if isinstance(item, dict))
    if not raw and result.get("answer_summary"):
        raw.append(
            (
                "extractive_answer",
                {
                    "text": result.get("answer_summary"),
                    "evidence_ids": result.get("summary_evidence_ids", []),
                },
            )
        )
    records = []
    for category, item in raw:
        text = str(item.get("text") or "")
        assertion_id = (
            "assertion:" + hashlib.sha256(f"{category}\x1f{text}".encode()).hexdigest()[:16]
        )
        records.append(
            {
                "assertion_id": assertion_id,
                "category": category,
                "text": text,
                "evidence_ids": item.get("evidence_ids") or [],
                "annotation": annotation["assertion_labels"].get(assertion_id),
            }
        )
    return records


def _conclusion_records(case: dict[str, Any], annotation: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for text in case.get("required_answer_components", []):
        identifier = "conclusion:" + hashlib.sha256(str(text).encode()).hexdigest()[:16]
        records.append(
            {
                "conclusion_id": identifier,
                "text": text,
                "annotation": annotation["conclusion_labels"].get(identifier),
            }
        )
    return records


def _flag_ratio(items: list[dict[str, Any]], field: str) -> float | None:
    flags = [
        item["annotation"].get(field)
        for item in items
        if item.get("annotation", {}).get(field) is not None
    ]
    return _ratio(sum(value is True for value in flags), len(flags))


def _flag_counts(items: list[dict[str, Any]], field: str) -> tuple[int, int]:
    flags = [
        item["annotation"].get(field)
        for item in items
        if item.get("annotation", {}).get(field) is not None
    ]
    return sum(value is True for value in flags), len(flags)


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(numerator / denominator, 4)


def _wilson(numerator: int, denominator: int) -> list[float] | None:
    if denominator <= 0:
        return None
    z = 1.959963984540054
    proportion = numerator / denominator
    denominator_adjusted = 1 + z * z / denominator
    centre = (proportion + z * z / (2 * denominator)) / denominator_adjusted
    margin = (
        z
        * (
            (proportion * (1 - proportion) / denominator + z * z / (4 * denominator * denominator))
            ** 0.5
        )
        / denominator_adjusted
    )
    return [round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4)]


def _reference_key(item: dict[str, Any]) -> str:
    doi = str(item.get("doi") or "").strip().lower()
    if not doi:
        raise ValueError("silver publication requires DOI")
    return f"doi:{doi}"


def _researcher_review(payload: dict[str, Any]) -> dict[str, Any]:
    reviewer = " ".join(str(payload.get("reviewer") or "").split())[:120]
    if not reviewer or reviewer.casefold() in {
        "system",
        "sci-search",
        "local researcher",
        "anonymous",
    }:
        raise ValueError("a named researcher is required for a gold-label revision")
    if payload.get("independent_review") is not True:
        raise ValueError("researcher confirmation must be an independent review")
    blinded = payload.get("blinded_to_system_output")
    if blinded is not True and blinded is not False:
        raise ValueError("blinded review state must be recorded")
    return {
        "reviewer": reviewer,
        "independent_review": True,
        "blinded_to_system_output": blinded,
        "reviewed_at": _now(),
    }


def _reviewed_label(
    existing: Any,
    values: dict[str, Any],
    decision: Any,
    review: dict[str, Any],
) -> dict[str, Any]:
    revisions = list(existing.get("review_revisions", [])) if isinstance(existing, dict) else []
    revisions.append({**review, "decision": decision})
    return {
        **values,
        "review_state": "researcher_confirmed",
        "reviewer": review["reviewer"],
        "reviewed_at": review["reviewed_at"],
        "review_revisions": revisions,
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))[:200]


def _reviewer_disagreement(annotation: dict[str, Any]) -> tuple[int, int]:
    disagreements = 0
    independently_repeated = 0
    for map_name in (
        "publication_labels",
        "evidence_labels",
        "assertion_labels",
        "conclusion_labels",
        "counterevidence_labels",
        "distinction_labels",
        "answerability_labels",
    ):
        for item in annotation.get(map_name, {}).values():
            revisions = item.get("review_revisions", []) if isinstance(item, dict) else []
            reviewers = {entry.get("reviewer") for entry in revisions if entry.get("reviewer")}
            if len(reviewers) < 2:
                continue
            independently_repeated += 1
            decisions = {
                json.dumps(entry.get("decision"), sort_keys=True, default=str)
                for entry in revisions
            }
            disagreements += len(decisions) > 1
    return disagreements, independently_repeated


def _has_independent_named_reviews(annotation: dict[str, Any]) -> bool:
    revisions = annotation.get("review_revisions", [])
    if not revisions:
        return False
    return all(
        item.get("reviewer")
        and item.get("independent_review") is True
        and isinstance(item.get("blinded_to_system_output"), bool)
        for item in revisions
    )


def validate_gold_record(payload: dict[str, Any]) -> None:
    """Validate the locked gold-label contract without promoting pending labels."""

    required = {
        "schema_version",
        "case_id",
        "must_retrieve_publications",
        "must_exclude_publications",
        "key_conclusions",
        "counterevidence",
        "required_distinctions",
        "answerability",
        "review_revisions",
    }
    if set(payload) != required or payload.get("schema_version") != "researcher_gold_v1":
        raise ValueError("gold label record does not match researcher_gold_v1")
    if not str(payload.get("case_id") or "").strip():
        raise ValueError("gold label case id is required")
    for name in ("must_retrieve_publications", "must_exclude_publications"):
        values = payload.get(name)
        if not isinstance(values, list) or len(values) != len(set(values)):
            raise ValueError(f"{name} must contain unique publication identifiers")
    for name in ("key_conclusions", "counterevidence", "required_distinctions", "answerability"):
        if not isinstance(payload.get(name), dict):
            raise ValueError(f"{name} must be an object")
    if not payload["answerability"]:
        raise ValueError("gold labels require an answerability judgment")
    revisions = payload.get("review_revisions")
    if not isinstance(revisions, list) or not revisions:
        raise ValueError("gold labels require a named researcher review revision")
    if not all(
        isinstance(item, dict)
        and str(item.get("reviewer") or "").strip()
        and item.get("independent_review") is True
        and isinstance(item.get("blinded_to_system_output"), bool)
        and item.get("reviewed_at")
        for item in revisions
    ):
        raise ValueError("gold label review provenance is incomplete")


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if value is True or value is False:
        return value
    raise ValueError("evaluation flags must be true, false, or null")


def _required_bool(value: Any) -> bool:
    if value is True or value is False:
        return value
    raise ValueError("covered must be true or false")


def _clean(value: Any, maximum: int) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _source_code_fingerprint() -> str:
    digest = hashlib.sha256()
    source_root = Path(__file__).resolve().parent
    for path in sorted(source_root.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()
