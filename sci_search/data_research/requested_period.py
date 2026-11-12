"""Conservative recovery of a literal output interval from the original request."""

import re

_YEAR = r"(?<!\d)(?:18|19|20|21)\d{2}(?!\d)"
_RANGE = re.compile(
    rf"({_YEAR})\s*(?:[-–—]|\bto\b|\bthrough\b|\btot(?:\s+en\s+met)?\b)\s*({_YEAR})"
    rf"|\b(?:between|tussen)\s+({_YEAR})\s+(?:and|en)\s+({_YEAR})",
    re.I,
)
_REFERENCE = re.compile(
    r"\b(?:base(?:line)?|reference|referentie\w*|basis\w*|rebased)\b|=\s*100\b", re.I
)


def explicit_interval(question: str) -> tuple[int, int] | None:
    """Recover only a sole unambiguous bounded range; leave richer timing to the model.

    In particular, never use the min/max of all years: reference periods, base
    years, multiple windows and open intervals are not a single output interval.
    """
    if len(re.findall(_YEAR, question)) != 2 or _REFERENCE.search(question):
        return None
    match = _RANGE.search(question)
    if not match:
        return None
    start, end = (int(year) for year in match.groups() if year is not None)
    if not 1800 <= start <= end <= 2100 or end - start > 200:
        return None
    return start, end


def requested_interval(question: str, clarification: str | None = None):
    """Keep the original bound unless a clarification introduces new timing."""
    if clarification:
        interval = explicit_interval(clarification)
        if interval:
            return interval
        if re.search(
            _YEAR + r"|\b(?:years?|jaren|jaar|period|periode|since|until|vanaf|tot|"
            r"recent|latest|last|laatste|earlier|later|historical|historisch)\b",
            clarification,
            re.I,
        ):
            return None
    return explicit_interval(question)
