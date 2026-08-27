"""Cross-domain evaluation for question planning, retrieval and citation grounding."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sci_search.generic_research import GenericResearchEngine


@dataclass(frozen=True, slots=True)
class GenericEvaluationReport:
    question_count: int
    expected_evidence_count: int
    matched_evidence_count: int
    missing_evidence_count: int
    unexpected_negative_evidence_count: int
    ungrounded_finding_count: int
    invalid_provenance_count: int

    @property
    def passed(self) -> bool:
        return not any(
            (
                self.missing_evidence_count,
                self.unexpected_negative_evidence_count,
                self.ungrounded_finding_count,
                self.invalid_provenance_count,
            )
        )


def evaluate_generic(engine: GenericResearchEngine, gold_path: Path) -> GenericEvaluationReport:
    payload = json.loads(gold_path.read_text(encoding="utf-8"))
    questions = payload.get("questions")
    if not isinstance(questions, list):
        raise ValueError("generic gold set questions must be a list")
    expected_count = matched = missing = unexpected_negative = ungrounded = invalid_provenance = 0
    canonical = {
        document.publication.source_document: document.text for document in engine.documents
    }
    for item in questions:
        report = engine.investigate(str(item["question"]))
        expectations = item.get("expected_evidence", [])
        expected_count += len(expectations)
        for expected in expectations:
            result = next(
                (
                    evidence
                    for evidence in report.evidence
                    if evidence.publication_id == expected["publication_id"]
                    and expected["passage_contains"] in evidence.passage
                ),
                None,
            )
            if result is None:
                missing += 1
            else:
                matched += 1
        if item.get("expect_no_evidence") and report.evidence:
            unexpected_negative += len(report.evidence)
        evidence_ids = {evidence.id for evidence in report.evidence}
        for finding in report.findings:
            if finding.status != "insufficient_evidence" and (
                not finding.evidence_ids or not set(finding.evidence_ids) <= evidence_ids
            ):
                ungrounded += 1
        for evidence in report.evidence:
            source = canonical[evidence.source_document]
            if (
                source[evidence.passage_start : evidence.passage_end] != evidence.passage
                or evidence.statement not in evidence.passage
            ):
                invalid_provenance += 1
    return GenericEvaluationReport(
        len(questions),
        expected_count,
        matched,
        missing,
        unexpected_negative,
        ungrounded,
        invalid_provenance,
    )
