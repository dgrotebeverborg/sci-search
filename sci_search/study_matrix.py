"""Question-specific, passage-grounded study cards and bounded adjudication."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from sci_search.corpus import _document_text, summarize_document_parse_error
from sci_search.coverage import decompose_question
from sci_search.discovery import PublicationCandidate
from sci_search.mistral_analysis import MistralAnalyzer
from sci_search.model_provider import configured_analyzer, selected_profile
from sci_search.question_planning import ResearchPlan

MATRIX_METHOD = "deterministic_question_specific_study_matrix_v1"
ADJUDICATION_METHOD = "mistral_quote_validated_fulltext_adjudication_v1"

ADJUDICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decisions"],
    "properties": {
        "decisions": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["publication_id", "decision", "reason", "dimension_findings"],
                "properties": {
                    "publication_id": {"type": "string"},
                    "decision": {
                        "type": "string",
                        "enum": ["include", "background", "exclude", "remain_uncertain"],
                    },
                    "reason": {"type": "string", "maxLength": 400},
                    "dimension_findings": {
                        "type": "array",
                        "maxItems": 12,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["dimension_id", "status", "passage_id", "quote"],
                            "properties": {
                                "dimension_id": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["supported", "unsupported", "unclear"],
                                },
                                "passage_id": {"type": "string"},
                                "quote": {"type": "string", "maxLength": 500},
                            },
                        },
                    },
                },
            },
        }
    },
}

_SECTION_CUES = {
    "methods": ("method", "materials", "experimental", "data and methods", "methodology"),
    "results": ("result", "finding", "discussion", "conclusion"),
    "limitations": ("limitation", "uncertaint", "caveat"),
}
_SENTENCE_CUES = {
    "methods": (
        "method",
        "measur",
        "model",
        "experiment",
        "sample",
        "dataset",
        "survey",
        "simulation",
    ),
    "results": (
        "result",
        "found",
        "show",
        "observ",
        "increas",
        "decreas",
        "efficien",
        "%",
        "significant",
    ),
    "limitations": (
        "limitation",
        "uncertain",
        "caution",
        "however",
        "restricted",
        "lack",
        "future work",
    ),
    "assumptions": ("assum", "scenario", "presum", "suppos", "estimated", "projected"),
}


def build_study_matrix(
    question: str,
    plan: ResearchPlan,
    corpus_directory: Path,
    acquired: list[tuple[PublicationCandidate, Any]],
    screening: list[dict[str, Any]],
    *,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one auditable card per acquired publication."""
    scope = decompose_question(question, plan)
    dimensions = [item for item in scope.get("dimensions", []) if isinstance(item, dict)]
    screening_by_id = {str(item.get("publication_id")): item for item in screening}
    evidence_by_publication: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in evidence or []:
        if isinstance(item, dict):
            evidence_by_publication[str(item.get("publication_id"))].append(item)
    cards: list[dict[str, Any]] = []
    for candidate, outcome in acquired:
        path = (corpus_directory / str(outcome.relative_path or "")).resolve()
        path.relative_to(corpus_directory.resolve())
        try:
            text = _document_text(path)
        except Exception as exc:
            screening_item = dict(screening_by_id.get(candidate.id) or {})
            cards.append(
                {
                    "schema_version": "question_specific_study_card_v1",
                    "publication_id": candidate.id,
                    "title": candidate.title,
                    "authors": list(candidate.authors),
                    "year": candidate.year,
                    "doi": candidate.doi,
                    "publication_type": candidate.publication_type,
                    "source_artifact": str(outcome.relative_path or ""),
                    "screening": screening_item,
                    "inferred_evidence_nature": {
                        "label": "unreadable",
                        "basis": "document parsing failed",
                    },
                    "dimension_coverage": [],
                    "selected_passages": [],
                    "extractive_fields": {},
                    "linked_final_evidence": [],
                    "provenance": {
                        "method": MATRIX_METHOD,
                        "source_text_sha256": screening_item.get("content_sha256"),
                    },
                    "parse_error": summarize_document_parse_error(exc, path),
                }
            )
            continue
        passages = _select_passages(candidate.id, text, dimensions)
        coverage = []
        for dimension in dimensions:
            dimension_id = str(dimension.get("id"))
            supporting = [
                item["id"] for item in passages if dimension_id in item["matched_dimension_ids"]
            ]
            coverage.append(
                {
                    "dimension_id": dimension_id,
                    "label": dimension.get("label"),
                    "kind": dimension.get("kind"),
                    "required": bool(dimension.get("required")),
                    "status": "supported" if supporting else "not_found",
                    "supporting_passage_ids": supporting,
                }
            )
        extracts = {
            name: _extract_sentences(passages, cues) for name, cues in _SENTENCE_CUES.items()
        }
        linked_evidence = [
            {
                "evidence_id": item.get("id"),
                "passage": item.get("passage"),
                "section": item.get("section"),
                "page": item.get("page"),
                "evidence_type": item.get("evidence_type"),
                "study_design": item.get("study_design"),
            }
            for item in evidence_by_publication.get(candidate.id, [])
        ]
        screening_item = dict(screening_by_id.get(candidate.id) or {})
        cards.append(
            {
                "schema_version": "question_specific_study_card_v1",
                "publication_id": candidate.id,
                "title": candidate.title,
                "authors": list(candidate.authors),
                "year": candidate.year,
                "doi": candidate.doi,
                "publication_type": candidate.publication_type,
                "source_artifact": str(outcome.relative_path or ""),
                "screening": screening_item,
                "inferred_evidence_nature": _evidence_nature(candidate, text),
                "dimension_coverage": coverage,
                "selected_passages": passages,
                "extractive_fields": extracts,
                "linked_final_evidence": linked_evidence,
                "provenance": {
                    "method": MATRIX_METHOD,
                    "source_text_sha256": screening_item.get("content_sha256"),
                },
            }
        )
    return {
        "schema_version": "question_specific_study_matrix_v1",
        "question": question,
        "method": MATRIX_METHOD,
        "dimensions": dimensions,
        "studies": cards,
        "summary": {
            "studies_acquired": len(cards),
            "studies_included_or_background": sum(
                card["screening"].get("decision") in {"included", "background"} for card in cards
            ),
            "studies_awaiting_review": sum(
                card["screening"].get("decision") == "uncertain" for card in cards
            ),
        },
    }


def adjudicate_uncertain_studies(
    question: str,
    matrix: dict[str, Any],
    analyzer: MistralAnalyzer | None = None,
) -> dict[str, Any]:
    """Ask a model only about uncertain studies; accept only exact-quote findings."""
    uncertain = [
        card
        for card in matrix.get("studies", [])
        if (card.get("screening") or {}).get("decision") == "uncertain"
    ][:12]
    if not uncertain:
        return {"status": "not_needed", "method": ADJUDICATION_METHOD, "decisions": []}
    selected = analyzer
    if selected is None:
        selected = configured_analyzer()
        if selected is None:
            return {
                "status": "unavailable",
                "method": ADJUDICATION_METHOD,
                "reason": f"{selected_profile().key_variable} is not configured",
                "decisions": [],
            }
    compact = [
        {
            "publication_id": card["publication_id"],
            "title": card["title"],
            "dimensions": card["dimension_coverage"],
            "passages": card["selected_passages"],
        }
        for card in uncertain
    ]
    body = {
        "model": selected.model,
        "temperature": 0,
        "max_tokens": 5000,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "fulltext_adjudication",
                "schema": ADJUDICATION_SCHEMA,
                "strict": True,
            },
        },
        "messages": [
            {
                "role": "system",
                "content": (
                    "You adjudicate uncertain scientific full texts. Use only supplied passages. "
                    "A supported finding requires a verbatim quote from its passage. Include only when the "
                    "paper directly supports all required question dimensions; background means the primary "
                    "subject is supported but the complete question is not. Never infer absent evidence."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"question": question, "studies": compact}, ensure_ascii=False
                ),
            },
        ],
    }
    try:
        response = selected.complete_json(
            body,
            {
                "Authorization": f"Bearer {selected.api_key}",
                "Content-Type": "application/json",
            },
        )
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed = json.loads(content)
        decisions, rejected = validate_adjudication(parsed, uncertain)
        return {
            "status": "complete",
            "provider": selected.provider.name,
            "model": selected.model,
            "method": f"{selected.provider.name}_quote_validated_fulltext_adjudication_v1",
            "decisions": decisions,
            "rejected_records": rejected,
        }
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return {
            "status": "unavailable",
            "method": ADJUDICATION_METHOD,
            "reason": f"validated adjudication failed: {type(exc).__name__}: {str(exc)[:300]}",
            "decisions": [],
        }


def validate_adjudication(
    payload: Any, cards: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("decisions"), list):
        raise ValueError("adjudication must contain a decisions array")
    by_publication = {str(card["publication_id"]): card for card in cards}
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for raw in payload["decisions"]:
        publication_id = str(raw.get("publication_id") or "") if isinstance(raw, dict) else ""
        card = by_publication.get(publication_id)
        if card is None:
            rejected.append({"publication_id": publication_id, "reason": "unknown publication"})
            continue
        passages = {str(item["id"]): item for item in card.get("selected_passages", [])}
        required = {
            str(item["dimension_id"])
            for item in card.get("dimension_coverage", [])
            if item.get("required")
        }
        findings = []
        invalid = None
        for finding in raw.get("dimension_findings", []):
            passage = passages.get(str(finding.get("passage_id") or ""))
            quote = str(finding.get("quote") or "").strip()
            dimension_id = str(finding.get("dimension_id") or "")
            if dimension_id not in required:
                invalid = f"unknown or non-required dimension: {dimension_id}"
                break
            if finding.get("status") == "supported":
                if not passage or len(quote) < 12 or quote not in passage["passage"]:
                    invalid = f"supporting quote was not found in {finding.get('passage_id')}"
                    break
                if dimension_id not in passage.get("matched_dimension_ids", []):
                    invalid = f"passage {finding.get('passage_id')} does not match dimension {dimension_id}"
                    break
            findings.append(
                {
                    "dimension_id": dimension_id,
                    "status": finding.get("status"),
                    "passage_id": finding.get("passage_id"),
                    "quote": quote,
                }
            )
        if invalid:
            rejected.append({"publication_id": publication_id, "reason": invalid})
            continue
        supported = {item["dimension_id"] for item in findings if item["status"] == "supported"}
        proposed = str(raw.get("decision") or "remain_uncertain")
        # The validator, not the model, determines whether promotion is safe.
        if proposed == "include" and not required <= supported:
            proposed = "remain_uncertain"
        if proposed == "background" and not any(item.startswith("subject:") for item in supported):
            proposed = "remain_uncertain"
        accepted.append(
            {
                "publication_id": publication_id,
                "decision": proposed,
                "reason": str(raw.get("reason") or "")[:400],
                "dimension_findings": findings,
                "all_required_dimensions_supported": required <= supported,
            }
        )
    return accepted, rejected


def apply_adjudication(
    screening: list[dict[str, Any]], adjudication: dict[str, Any]
) -> list[dict[str, Any]]:
    by_id = {str(item.get("publication_id")): item for item in adjudication.get("decisions", [])}
    output = []
    for original in screening:
        item = dict(original)
        result = by_id.get(str(item.get("publication_id")))
        if item.get("decision") == "uncertain" and result:
            mapped = {"include": "included", "background": "background", "exclude": "excluded"}.get(
                result["decision"]
            )
            item["adjudication"] = result
            if mapped:
                item["decision"] = mapped
                item["reason"] = f"Quote-validated AI adjudication: {result['reason']}"
                item["method"] = f"{item.get('method')}+{ADJUDICATION_METHOD}"
        output.append(item)
    return output


def active_from_screening(
    acquired: list[tuple[PublicationCandidate, Any]],
    screening: list[dict[str, Any]],
) -> list[tuple[PublicationCandidate, Any]]:
    active_ids = {
        str(item.get("publication_id")) for item in screening if item.get("decision") == "included"
    }
    return [item for item in acquired if item[0].id in active_ids]


def _select_passages(
    publication_id: str, text: str, dimensions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    candidates = []
    section = "full text"
    for index, match in enumerate(re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|\Z)", text, re.DOTALL)):
        passage = match.group(0).strip()
        if len(passage) < 40:
            if len(passage) < 120 and re.fullmatch(r"[#\s]*[A-Za-z][A-Za-z\s&:/-]{2,80}", passage):
                section = passage.lstrip("# ")
            continue
        matched = []
        lowered = passage.casefold()
        for dimension in dimensions:
            terms = dimension.get("terms") or []
            if dimension.get("kind") == "subject" and dimension.get("term_groups"):
                terms = [term for group in dimension["term_groups"] for term in group]
            if any(_contains(lowered, str(term)) for term in terms):
                matched.append(str(dimension.get("id")))
        scientific = sum(any(cue in lowered for cue in cues) for cues in _SENTENCE_CUES.values())
        score = (
            len(matched) * 5
            + scientific
            + (2 if re.search(r"\b\d+(?:\.\d+)?\s*(?:%|[A-Za-z]+/[A-Za-z]+)\b", passage) else 0)
        )
        stored_passage = passage[:2500]
        candidates.append(
            (
                score,
                index,
                {
                    "id": f"study-passage:{publication_id}:{index}",
                    "publication_id": publication_id,
                    "section": section,
                    "page": text.count("\f", 0, match.start()) + 1 if "\f" in text else None,
                    "start_char": match.start(),
                    "end_char": match.start() + len(stored_passage),
                    "passage": stored_passage,
                    "matched_dimension_ids": matched,
                },
            )
        )
    ranked = sorted(candidates, key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked[:6] if item[0] > 0]


def _extract_sentences(
    passages: list[dict[str, Any]], cues: tuple[str, ...]
) -> list[dict[str, Any]]:
    output = []
    for passage in passages:
        for sentence in re.split(r"(?<=[.!?])\s+", passage["passage"]):
            sentence = sentence.strip()
            if 30 <= len(sentence) <= 700 and any(cue in sentence.casefold() for cue in cues):
                output.append({"text": sentence, "passage_id": passage["id"]})
                if len(output) == 3:
                    return output
    return output


def _evidence_nature(candidate: PublicationCandidate, text: str) -> dict[str, Any]:
    sample = f"{candidate.title}\n{candidate.abstract}\n{text[:12000]}".casefold()
    options = (
        ("review", ("systematic review", "literature review", "meta-analysis")),
        ("techno-economic model", ("techno-economic", "lcos", "cost model")),
        ("simulation or model", ("simulation", "modelled", "modeled", "scenario")),
        ("laboratory experiment", ("laboratory", "experimental cell", "electrode", "we measured")),
        (
            "field or observational study",
            ("observational", "field study", "time series", "satellite observations"),
        ),
    )
    for label, cues in options:
        matched = [cue for cue in cues if cue in sample]
        if matched:
            return {"label": label, "basis": "keyword cues", "matched_cues": matched[:4]}
    return {
        "label": candidate.publication_type or "unclassified",
        "basis": "publication metadata",
        "matched_cues": [],
    }


def _contains(text: str, term: str) -> bool:
    normalized = " ".join(term.casefold().replace("-", " ").split())
    haystack = " ".join(text.casefold().replace("-", " ").split())
    return bool(normalized and re.search(r"(?<!\w)" + re.escape(normalized) + r"(?!\w)", haystack))
