"""Conservative, domain-independent matching of research concepts.

Short phrases require an exact normalized token sequence. Long descriptions can
be restated locally, but every content anchor must occur within 80 tokens. No
synonyms, partial anchor scores, or document-wide word bags are used.
"""

import re
import unicodedata
from collections import Counter, deque
from functools import lru_cache

_CONNECTORS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "for",
        "to",
        "from",
        "in",
        "on",
        "at",
        "by",
        "with",
        "using",
        "under",
        "over",
        "between",
        "based",
    }
)
_MIN_ANCHORS = 6
_MAX_WINDOW_TOKENS = 80


@lru_cache(maxsize=4)
def _normalized(text: str) -> tuple[str, tuple[int, ...] | None]:
    if text.isascii():
        return text.lower(), None
    parts = [unicodedata.normalize("NFKC", char).casefold() for char in text]
    normalized = "".join(parts)
    if all(len(part) == 1 for part in parts):
        return normalized, None
    offsets = tuple(index for index, part in enumerate(parts) for _ in part)
    return normalized, offsets


def _tokens(text: str) -> list[tuple[str, int, int]]:
    normalized, offsets = _normalized(text)
    return [
        (
            match.group(),
            offsets[match.start()] if offsets is not None else match.start(),
            offsets[match.end() - 1] + 1 if offsets is not None else match.end(),
        )
        for match in re.finditer(r"[^\W_]+", normalized)
    ]


def _literal_spans(text: str, term: str) -> list[tuple[int, int]]:
    normalized, offsets = _normalized(text)
    normalized_term, _ = _normalized(term)
    # Only separators between words can vary. Keep slash, charge/polarity,
    # programming-language suffixes, and other meaningful symbols literal.
    pieces = re.split(r"(?<=\w)[\s\-‐‑‒–—]+(?=\w)", normalized_term.strip())
    pattern = r"(?<![\w+−])" + r"[\s\-‐‑‒–—]+".join(re.escape(part) for part in pieces)
    pattern += r"(?!\w|[+−]|-(?!\w))"
    return [
        (
            offsets[match.start()] if offsets is not None else match.start(),
            offsets[match.end() - 1] + 1 if offsets is not None else match.end(),
        )
        for match in re.finditer(pattern, normalized)
    ]


def _singular(token: str) -> str:
    # Deliberately limited regular inflections; do not stem scientific terms.
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def _anchor_groups(words: list[str]) -> list[frozenset[str]]:
    groups: list[set[str]] = []
    occurrences = Counter(_singular(word) for word in words if word not in _CONNECTORS)
    alternative = False
    for word in words:
        if word == "or":
            alternative = bool(groups)
        elif word not in _CONNECTORS:
            anchor = _singular(word)
            if alternative:
                # A repeated endpoint can be the shared noun of multiword
                # alternatives ("lithium ion batteries or iron air batteries").
                # Its OR scope is ambiguous; retain only literal matching.
                if occurrences[anchor] > 1 or any(
                    occurrences[previous] > 1 for previous in groups[-1]
                ):
                    return []
                groups[-1].add(anchor)
            else:
                groups.append({anchor})
            alternative = False
    return list(dict.fromkeys(frozenset(group) for group in groups))


def concept_spans(text: str, term: str) -> list[tuple[int, int]]:
    """Return matching character spans in *text*, retaining all required anchors.

    Explicit ``x or y`` / ``x and/or y`` joins adjacent content tokens as
    alternatives only for long descriptions. Ordinary ``and`` requires both.
    Long-description matches are local windows, possibly overlapping.
    """
    term_words = [word for word, _, _ in _tokens(term)]
    if not term_words:
        return []
    exact = _literal_spans(text, term)
    groups = _anchor_groups(term_words)
    normalized_term, _ = _normalized(term)
    if len(groups) < _MIN_ANCHORS or re.search(r"[+−]|-(?:$|\s+(?!and\b|or\b))", normalized_term):
        return exact
    text_tokens = _tokens(text)

    compounds = [
        [_singular(word) for word, _, _ in _tokens(part)]
        for part in re.findall(r"[^\W_]+(?:[-‐‑‒–—][^\W_]+)+", term)
        if len([word for word, _, _ in _tokens(part) if word not in _CONNECTORS]) > 1
    ]
    memberships: dict[str, set[int]] = {}
    for group_id, group in enumerate(groups):
        for anchor in group:
            memberships.setdefault(anchor, set()).add(group_id)
    events: deque[tuple[int, set[int]]] = deque()
    counts: Counter[int] = Counter()
    spans = set(exact)
    for index, (word, _, end) in enumerate(text_tokens):
        matched = memberships.get(_singular(word))
        if not matched:
            continue
        events.append((index, matched))
        counts.update(matched)
        while events and index - events[0][0] >= _MAX_WINDOW_TOKENS:
            _, expired = events.popleft()
            counts.subtract(expired)
            counts += Counter()  # Remove zero counts before checking coverage.
        if len(counts) != len(groups):
            continue
        start_index = events[0][0]
        window_words = [_singular(item[0]) for item in text_tokens[start_index : index + 1]]
        if all(
            any(
                window_words[i : i + len(compound)] == compound
                for i in range(len(window_words) - len(compound) + 1)
            )
            for compound in compounds
        ):
            spans.add((text_tokens[start_index][1], end))
    return sorted(spans)


def concept_present(text: str, term: str) -> bool:
    """Whether a literal phrase or fully anchored local restatement is present."""
    return bool(concept_spans(text, term))
