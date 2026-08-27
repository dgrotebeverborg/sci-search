"""Inspectable extraction evaluation for contextual measurements."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from sci_search.corpus import load_corpus
from sci_search.models import MeasurementResult


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    expected_count: int
    extracted_count: int
    matched_count: int
    missing_count: int
    hallucinated_count: int
    incorrect_unit_count: int
    incorrect_provenance_count: int
    incorrect_context_count: int

    @property
    def passed(self) -> bool:
        return not any(
            (
                self.missing_count,
                self.hallucinated_count,
                self.incorrect_unit_count,
                self.incorrect_provenance_count,
                self.incorrect_context_count,
            )
        )


def evaluate_results(
    results: tuple[MeasurementResult, ...], gold_path: Path, corpus_directory: Path
) -> EvaluationReport:
    gold_data = json.loads(gold_path.read_text(encoding="utf-8"))
    expected = gold_data.get("results")
    if not isinstance(expected, list):
        raise ValueError("gold results must be a list")
    unmatched = list(results)
    canonical_text = {
        document.publication.source_document: document.text
        for document in load_corpus(corpus_directory)
    }
    matched = 0
    missing = 0
    incorrect_units = 0
    incorrect_provenance = 0
    incorrect_context = 0
    for item in expected:
        publication_id = str(item["publication_id"])
        expected_value = Decimal(str(item["value"]))
        result = next(
            (
                candidate
                for candidate in unmatched
                if candidate.provenance.publication_id == publication_id
                and candidate.metric == str(item.get("metric") or "round_trip_efficiency")
                and candidate.quantity.value == expected_value
            ),
            None,
        )
        if result is None:
            missing += 1
            continue
        unmatched.remove(result)
        matched += 1
        if result.quantity.unit != item["unit"] or result.quantity.value != Decimal(
            str(item["value"])
        ):
            incorrect_units += 1
        source_text = canonical_text[result.provenance.source_document]
        offsets_valid = (
            source_text[result.provenance.passage_start : result.provenance.passage_end]
            == result.provenance.passage
        )
        if (
            result.provenance.page != item["page"]
            or result.provenance.section != item["section"]
            or item["passage_contains"] not in result.provenance.passage
            or not offsets_valid
        ):
            incorrect_provenance += 1
        conditions = {
            condition.name: f"{condition.value} {condition.unit}"
            for condition in result.context.conditions
        }
        if any(conditions.get(key) != value for key, value in item.get("conditions", {}).items()):
            incorrect_context += 1
    hallucinated = len(unmatched)
    return EvaluationReport(
        expected_count=len(expected),
        extracted_count=len(results),
        matched_count=matched,
        missing_count=missing,
        hallucinated_count=hallucinated,
        incorrect_unit_count=incorrect_units,
        incorrect_provenance_count=incorrect_provenance,
        incorrect_context_count=incorrect_context,
    )
