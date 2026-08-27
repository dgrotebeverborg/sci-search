"""Small-corpus lexical passage retrieval with inspectable scores."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from sci_search.corpus import CorpusDocument, SourcePassage
from sci_search.profiles import PROFILES, contains_term
from sci_search.question_planning import ResearchPlan


@dataclass(frozen=True, slots=True)
class RetrievedPassage:
    publication_id: str
    publication_title: str
    source_document: str
    passage: SourcePassage
    score: float
    matched_terms: tuple[str, ...]


class PassageIndex:
    def __init__(self, documents: tuple[CorpusDocument, ...]) -> None:
        self.documents = documents
        self._records = tuple(
            (document, passage, _tokens(passage.text))
            for document in documents
            for passage in document.passages()
            if len(passage.text) >= 40
        )
        document_frequency: Counter[str] = Counter()
        for _, _, tokens in self._records:
            document_frequency.update(set(tokens))
        self._idf = {
            term: math.log((len(self._records) + 1) / (count + 1)) + 1
            for term, count in document_frequency.items()
        }

    def search(self, plan: ResearchPlan, *, limit: int = 20) -> tuple[RetrievedPassage, ...]:
        query_terms = tuple(
            dict.fromkeys(term for phrase in plan.expanded_terms for term in _tokens(phrase))
        )
        profile = PROFILES[plan.profile_id]
        concept_term_groups = tuple(
            tuple(
                dict.fromkeys(
                    token for alias in profile.expand(concept) for token in _tokens(alias)
                )
            )
            for concept in plan.concepts
        )
        concept_phrase_groups = tuple(
            tuple(alias.lower() for alias in profile.expand(concept) if " " in alias)
            for concept in plan.concepts
        )
        ranked: list[RetrievedPassage] = []
        coverage_ratio = 0.5 if plan.profile_id == "generic" else 0.67
        required_coverage = (
            len(plan.concepts)
            if len(plan.concepts) <= 2
            else math.ceil(len(plan.concepts) * coverage_ratio)
        )
        for document, passage, tokens in self._records:
            title_tokens = _tokens(document.publication.title)
            counts = Counter((*tokens, *title_tokens))
            matched = tuple(
                term
                for term in query_terms
                if any(_token_matches(term, source_token) for source_token in counts)
            )
            if not matched:
                continue
            searchable = (document.publication.title + " " + passage.text).lower()
            covered_concepts = sum(
                any(
                    contains_term(searchable, alias)
                    or all(
                        any(
                            _token_matches(token, source_token)
                            for source_token in (*tokens, *title_tokens)
                        )
                        for token in _tokens(alias)
                    )
                    for alias in profile.expand(concept)
                )
                for concept in plan.concepts
            )
            if covered_concepts < required_coverage:
                continue
            length_normalizer = 1 + 0.15 * max(0, len(tokens) / 120 - 1)
            score = (
                sum(
                    max(
                        (
                            (1 + math.log(counts[term])) * self._idf.get(term, 1)
                            for term in group
                            if counts[term]
                        ),
                        default=0.0,
                    )
                    for group in concept_term_groups
                )
                / length_normalizer
            )
            lowered = passage.text.lower()
            score += sum(
                3.0 for group in concept_phrase_groups if any(phrase in lowered for phrase in group)
            )
            score += 1.0 if passage.section not in {"references", "unknown"} else 0
            section = passage.section.lower()
            if plan.intent == "method" and any(
                term in section for term in ("method", "materials", "experimental")
            ):
                score += 3.0
            elif any(term in section for term in ("result", "finding")):
                score += 2.5
            elif any(term in section for term in ("discussion", "conclusion")):
                score += 1.5
            elif section == "abstract":
                score += 0.5
            score += (
                0.75
                if any(
                    cue in lowered
                    for cue in (
                        "we found",
                        "results show",
                        "was associated",
                        "increased",
                        "decreased",
                        "significant",
                    )
                )
                else 0
            )
            ranked.append(
                RetrievedPassage(
                    document.publication.id,
                    document.publication.title,
                    document.publication.source_document,
                    passage,
                    round(score, 4),
                    matched,
                )
            )
        ranked.sort(key=lambda item: (-item.score, item.publication_id, item.passage.start))
        return tuple(ranked[:limit])


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z][a-z0-9-]{1,}", text.lower()))


def _token_matches(query_token: str, source_token: str) -> bool:
    """Allow transparent inflection matching without a language model."""
    if query_token == source_token:
        return True
    return min(len(query_token), len(source_token)) >= 4 and (
        query_token.startswith(source_token) or source_token.startswith(query_token)
    )
