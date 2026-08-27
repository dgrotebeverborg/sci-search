"""Auditable post-acquisition relevance screening over parsed full text."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sci_search.coverage import decompose_question
from sci_search.discovery import PublicationCandidate
from sci_search.question_planning import ResearchPlan

SCREENING_METHOD = "deterministic_fulltext_relevance_v1"
_WEAK_GENERIC_LABELS = {"observed", "present", "reported", "published"}


@dataclass(frozen=True, slots=True)
class FullTextDecision:
    publication_id: str
    decision: str
    reason: str
    method: str
    content_sha256: str
    core_groups_required: int
    core_groups_matched: int
    supporting_groups_required: int
    supporting_groups_matched: int
    matched_groups: tuple[str, ...]
    missing_groups: tuple[str, ...]
    researcher_override: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def screen_full_text(
    question: str,
    plan: ResearchPlan,
    candidate: PublicationCandidate,
    text: str,
    *,
    researcher_decision: dict[str, Any] | None = None,
) -> FullTextDecision:
    """Classify an acquired document without treating download as inclusion."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    override = str((researcher_decision or {}).get("decision") or "")
    if override in {"include", "background", "exclude"}:
        decision = {"include": "included", "background": "background", "exclude": "excluded"}[
            override
        ]
        reason = str((researcher_decision or {}).get("reason") or "researcher decision")
        return FullTextDecision(
            candidate.id,
            decision,
            f"Researcher override: {reason}",
            SCREENING_METHOD,
            digest,
            0,
            0,
            0,
            0,
            (),
            (),
            True,
        )

    scope = decompose_question(question, plan)
    substantive = _without_references(text)
    title = candidate.title.casefold()
    metadata = f"{candidate.title}\n{candidate.abstract[:3000]}".casefold()
    dimensions = [item for item in scope.get("dimensions", []) if isinstance(item, dict)]
    subject = next((item for item in dimensions if item.get("kind") == "subject"), {})
    raw_core = subject.get("term_groups") or [[term] for term in subject.get("terms", [])]
    core_groups = [(str(group[0]), tuple(map(str, group))) for group in raw_core if group]
    mandatory = {
        int(item) for item in subject.get("mandatory_group_indexes", []) if isinstance(item, int)
    }
    if plan.profile_id == "generic" and core_groups:
        mandatory.add(0)
    required_core = max(1, int(subject.get("minimum_group_matches") or 1))

    core_matches = [
        _group_strength(aliases, metadata, substantive, primary=True) for _, aliases in core_groups
    ]
    strong_core = {index for index, strength in enumerate(core_matches) if strength >= 2}
    weak_core = {index for index, strength in enumerate(core_matches) if strength == 1}
    core_ok = len(strong_core) >= required_core and mandatory <= strong_core

    support_groups = _support_groups(dimensions, core_groups, plan)
    local_context = _subject_context(
        substantive, tuple(alias for _, aliases in core_groups for alias in aliases)
    )
    support_body = (
        local_context
        if plan.intent in {"relationship", "comparison", "contradiction"}
        else substantive
    )
    support_matches = [
        _group_strength(aliases, metadata, support_body) for _, aliases in support_groups
    ]
    strong_support = {index for index, strength in enumerate(support_matches) if strength >= 2}
    required_support = _required_support(plan, support_groups)
    strict_scope_labels = {
        str(item.get("label") or item.get("kind"))
        for item in dimensions
        if item.get("kind") in {"geography", "time"}
    }
    if plan.intent == "temporal_trend":
        strict_scope_labels.add("change across time")
    dimension_by_label = {str(item.get("label") or item.get("kind")): item for item in dimensions}
    for index, (label, aliases) in enumerate(support_groups):
        dimension = dimension_by_label.get(label, {})
        present = (
            _time_scope_present(metadata, substantive, dimension)
            if dimension.get("kind") == "time"
            else any(
                _contains(metadata, alias) or _contains(substantive, alias) for alias in aliases
            )
        )
        if label in strict_scope_labels:
            if present:
                strong_support.add(index)
            else:
                strong_support.discard(index)
    support_ok = len(strong_support) >= required_support
    missing_strict_scope = {
        label
        for index, (label, _) in enumerate(support_groups)
        if label in strict_scope_labels and index not in strong_support
    }
    core_title_focus = any(
        _contains(title, alias) for _, aliases in core_groups for alias in aliases
    )

    matched = tuple(
        [label for index, (label, _) in enumerate(core_groups) if index in strong_core]
        + [label for index, (label, _) in enumerate(support_groups) if index in strong_support]
    )
    missing = tuple(
        [label for index, (label, _) in enumerate(core_groups) if index not in strong_core]
        + [label for index, (label, _) in enumerate(support_groups) if index not in strong_support]
    )

    if not core_ok:
        if weak_core and not mandatory.difference(strong_core | weak_core):
            decision = "uncertain"
            reason = "The primary subject appears only once in substantive text and needs researcher review."
        else:
            decision = "excluded"
            reason = "The acquired full text does not substantively cover the question's primary subject."
    elif missing_strict_scope:
        decision = "excluded"
        reason = (
            "The primary subject is present, but the full text is outside required scope: "
            + ", ".join(sorted(missing_strict_scope))
            + "."
        )
    elif support_ok:
        decision = "included"
        reason = "The full text substantively covers the primary subject and the required question dimensions."
    elif plan.intent in {"relationship", "comparison", "contradiction"} and not core_title_focus:
        decision = "excluded"
        reason = "The primary subject is mentioned, but it is not the document's focus and the requested relationship is unsupported."
    else:
        decision = "background"
        reason = "The primary subject is covered, but direct coverage of the requested outcome or relationship is incomplete."
    return FullTextDecision(
        candidate.id,
        decision,
        reason,
        SCREENING_METHOD,
        digest,
        required_core,
        len(strong_core),
        required_support,
        len(strong_support),
        matched,
        missing,
    )


def screen_acquired_documents(
    question: str,
    plan: ResearchPlan,
    corpus_directory: Path,
    acquired: list[tuple[PublicationCandidate, Any]],
    *,
    researcher_decisions: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[tuple[PublicationCandidate, Any]], list[dict[str, Any]]]:
    from sci_search.corpus import _document_text, summarize_document_parse_error

    active: list[tuple[PublicationCandidate, Any]] = []
    decisions: list[dict[str, Any]] = []
    overrides = researcher_decisions or {}
    for candidate, outcome in acquired:
        path = (corpus_directory / str(outcome.relative_path or "")).resolve()
        path.relative_to(corpus_directory.resolve())
        try:
            text = _document_text(path)
        except Exception as exc:  # keep one malformed or scanned file local to this record
            error = summarize_document_parse_error(exc, path)
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                digest = ""
            decisions.append(
                {
                    "publication_id": candidate.id,
                    "decision": "unreadable",
                    "reason": "The acquired artifact could not be converted to usable scientific text.",
                    "method": "document_parse_validation_v1",
                    "content_sha256": digest,
                    "core_groups_required": 0,
                    "core_groups_matched": 0,
                    "supporting_groups_required": 0,
                    "supporting_groups_matched": 0,
                    "matched_groups": (),
                    "missing_groups": (),
                    "researcher_override": False,
                    "parse_error": error,
                }
            )
            continue
        decision = screen_full_text(
            question,
            plan,
            candidate,
            text,
            researcher_decision=overrides.get(candidate.id),
        )
        decisions.append(decision.to_dict())
        if decision.decision in {"included", "background"}:
            active.append((candidate, outcome))
    return active, decisions


def _support_groups(
    dimensions: list[dict[str, Any]],
    core_groups: list[tuple[str, tuple[str, ...]]],
    plan: ResearchPlan,
) -> list[tuple[str, tuple[str, ...]]]:
    core_alias_sets = [{_normalized(term) for term in aliases} for _, aliases in core_groups]
    groups: list[tuple[str, tuple[str, ...]]] = []
    for dimension in dimensions:
        kind = str(dimension.get("kind") or "")
        label = str(dimension.get("label") or kind)
        if kind in {"subject", "task"} or (
            kind == "topic" and label.casefold() in _WEAK_GENERIC_LABELS
        ):
            continue
        aliases = tuple(str(item) for item in dimension.get("terms", []) if str(item).strip())
        normalized = {_normalized(item) for item in aliases}
        if not aliases or any(normalized <= core for core in core_alias_sets):
            continue
        if not any(
            normalized == {_normalized(item) for item in existing} for _, existing in groups
        ):
            groups.append((label, aliases))
    if plan.intent == "temporal_trend":
        task = next((item for item in dimensions if item.get("kind") == "task"), None)
        if task:
            groups.append(("change across time", tuple(map(str, task.get("terms", [])))))
    return groups


def _required_support(plan: ResearchPlan, groups: list[tuple[str, tuple[str, ...]]]) -> int:
    if not groups or plan.intent in {
        "evidence_search",
        "method",
        "limitation",
        "assumption",
        "gap",
    }:
        return 0
    if plan.intent in {"relationship", "comparison", "contradiction"}:
        return len(groups)
    return 1


def _group_strength(
    aliases: tuple[str, ...], metadata: str, body: str, *, primary: bool = False
) -> int:
    metadata_hit = any(_contains(metadata, alias) for alias in aliases)
    body_count = max((_count(body, alias) for alias in aliases), default=0)
    if primary:
        return 2 if metadata_hit and body_count >= 1 else 1 if metadata_hit or body_count else 0
    if body_count >= 2 or (metadata_hit and body_count >= 1):
        return 2
    return 1 if metadata_hit or body_count == 1 else 0


def _without_references(text: str) -> str:
    lowered = text.casefold()
    cut = len(text)
    for match in re.finditer(
        r"(?m)^\s*(?:#{1,4}\s*)?(?:references|bibliography|works cited)\s*$", lowered
    ):
        if match.start() > len(text) * 0.35:
            cut = match.start()
            break
    return lowered[:cut]


def _subject_context(text: str, aliases: tuple[str, ...], *, radius: int = 600) -> str:
    windows: list[str] = []
    for alias in aliases:
        pieces = [re.escape(item) for item in re.findall(r"(?u)[^\W_]+", alias.casefold())]
        if not pieces:
            continue
        pattern = r"(?<!\w)" + r"[\s\-‐‑‒–—/]*".join(pieces) + r"(?!\w)"
        for match in re.finditer(pattern, text):
            windows.append(
                text[max(0, match.start() - radius) : min(len(text), match.end() + radius)]
            )
    return "\n".join(windows)


def _time_scope_present(metadata: str, body: str, dimension: dict[str, Any]) -> bool:
    start, end = dimension.get("start_year"), dimension.get("end_year")
    if not isinstance(start, int) or not isinstance(end, int):
        return any(
            _contains(metadata, str(term)) or _contains(body, str(term))
            for term in dimension.get("terms", [])
        )
    metadata_years = sorted(
        {
            int(item)
            for item in re.findall(r"\b(?:18|19|20)\d{2}\b", metadata)
            if start <= int(item) <= end
        }
    )
    if start >= 1900 and re.search(
        r"\b(?:holocene|pleistocene|interglacial|paleo(?:climate|environmental)?)\b", metadata
    ):
        if len(metadata_years) < 2:
            return False
    years = sorted(
        {
            int(item)
            for item in re.findall(r"\b(?:18|19|20)\d{2}\b", f"{metadata}\n{body}")
            if start <= int(item) <= end
        }
    )
    label = str(dimension.get("label") or "").casefold()
    if "century" in label:
        return bool(
            re.search(r"\b(?:20|21)(?:st|nd|rd|th)?[-‐‑‒–— ]+century\b", f"{metadata}\n{body}")
        ) or (len(years) >= 2 and years[-1] - years[0] >= 5)
    if label.startswith("since "):
        return ("since" in f"{metadata}\n{body}" and str(start) in f"{metadata}\n{body}") or (
            len(years) >= 2 and years[-1] > years[0]
        )
    return len(years) >= 2 and years[-1] > years[0]


def _contains(text: str, term: str) -> bool:
    return _count(text, term) > 0


def _count(text: str, term: str) -> int:
    counts = []
    for form in _inflection_forms(term):
        pieces = [re.escape(item) for item in re.findall(r"(?u)[^\W_]+", form.casefold())]
        if not pieces:
            continue
        pattern = r"(?<!\w)" + r"[\s\-‐‑‒–—/]*".join(pieces) + r"(?!\w)"
        counts.append(len(re.findall(pattern, text)))
    return max(counts, default=0)


def _inflection_forms(term: str) -> tuple[str, ...]:
    words = term.casefold().split()
    if not words:
        return ()
    last = words[-1]
    variants = {last}
    if last.endswith("ies") and len(last) > 4:
        variants.add(last[:-3] + "y")
    elif last.endswith("s") and len(last) > 4 and not last.endswith(("ss", "us", "is")):
        variants.add(last[:-1])
    elif len(last) > 3:
        variants.add(last + "s")
    return tuple(" ".join([*words[:-1], variant]) for variant in variants)


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"(?u)[^\W_]+", value.casefold()))
