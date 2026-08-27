"""Deterministic validation and versioning for automatically extracted evidence.

The checks in this module establish source grounding, not scientific truth.  A
record can be silver-source-verified while its scientific interpretation still
awaits researcher or expert review.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

EVIDENCE_SCHEMA_VERSION = "generic_evidence_v2"
VALIDATOR_VERSION = "source_grounding_v1"


@dataclass(frozen=True, slots=True)
class ValidationCheck:
    name: str
    passed: bool
    detail: str
    severity: str = "error"


@dataclass(frozen=True, slots=True)
class EvidenceValidation:
    status: str
    review_state: str
    schema_version: str
    validator_version: str
    evidence_fingerprint: str
    document_sha256: str
    checks: tuple[ValidationCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks if check.severity == "error")


def validate_extractive_evidence(
    *,
    publication_id: str,
    source_document: str,
    document_text: str,
    passage: str,
    statement: str,
    passage_start: int,
    passage_end: int,
    numerical_mentions: tuple[str, ...],
    page: int | None,
    extraction_method: str,
) -> EvidenceValidation:
    """Validate facts that can be established without scientific judgement."""
    document_sha = hashlib.sha256(document_text.encode("utf-8")).hexdigest()
    checks = (
        ValidationCheck(
            "publication_linked",
            bool(publication_id.strip()),
            "A publication identifier is present.",
        ),
        ValidationCheck(
            "source_document_linked", bool(source_document.strip()), "A source document is present."
        ),
        ValidationCheck(
            "passage_offsets_exact",
            0 <= passage_start < passage_end <= len(document_text)
            and document_text[passage_start:passage_end] == passage,
            "The stored character offsets reproduce the complete source passage exactly.",
        ),
        ValidationCheck(
            "statement_in_passage",
            bool(statement.strip()) and statement in passage,
            "The selected statement occurs verbatim in the source passage.",
        ),
        ValidationCheck(
            "numbers_in_statement",
            all(mention in statement for mention in numerical_mentions),
            "Every extracted numerical mention occurs verbatim in the selected statement.",
        ),
        ValidationCheck(
            "page_available",
            page is not None and page > 0,
            "A positive source page is encoded."
            if page
            else "The source format does not encode a page number.",
            severity="warning",
        ),
        ValidationCheck(
            "extraction_method_versioned",
            bool(extraction_method.strip()),
            "The extraction method is recorded.",
        ),
    )
    critical_passed = all(item.passed for item in checks if item.severity == "error")
    fingerprint_input = "\x1f".join(
        (
            publication_id,
            document_sha,
            str(passage_start),
            str(passage_end),
            statement,
            extraction_method,
            EVIDENCE_SCHEMA_VERSION,
        )
    )
    return EvidenceValidation(
        status="silver_source_verified" if critical_passed else "validation_failed",
        review_state="unreviewed",
        schema_version=EVIDENCE_SCHEMA_VERSION,
        validator_version=VALIDATOR_VERSION,
        evidence_fingerprint="evidence-fingerprint:"
        + hashlib.sha256(fingerprint_input.encode("utf-8")).hexdigest(),
        document_sha256=document_sha,
        checks=checks,
    )


def normalized_number_mentions(text: str) -> tuple[str, ...]:
    """Expose the canonical number matcher for validators and tests."""
    return tuple(
        dict.fromkeys(
            re.findall(
                r"(?<!\w)[<>~≈]?\d+(?:\.\d+)?\s*(?:%|°C|km|m|h|days?|years?|kg|g)?",
                text,
                re.IGNORECASE,
            )
        )
    )
