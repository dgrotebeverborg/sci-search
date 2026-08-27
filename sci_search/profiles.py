"""Optional domain profiles layered over the generic scientific core."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DomainProfile:
    id: str
    label: str
    vocabulary: tuple[tuple[str, tuple[str, ...]], ...]
    comparison_dimensions: tuple[str, ...] = ()
    anchor_concepts: tuple[str, ...] = ()

    def expand(self, term: str) -> tuple[str, ...]:
        normalized = term.lower().strip()
        for canonical, aliases in self.vocabulary:
            values = (canonical, *aliases)
            if normalized in values:
                return values
        return (normalized,)


GENERIC_PROFILE = DomainProfile(
    "generic",
    "Generic science",
    (
        (
            "el niño",
            ("el nino", "enso", "el niño-southern oscillation", "el nino-southern oscillation"),
        ),
        ("greenland ice sheet", ("greenland ice-sheet", "gris")),
        ("precipitation", ("rainfall", "snowfall", "rain", "snow accumulation")),
    ),
)

ENERGY_PROFILE = DomainProfile(
    "energy",
    "Energy storage",
    (
        (
            "round-trip efficiency",
            (
                "round-trip efficiencies",
                "round trip efficiency",
                "round trip efficiencies",
                "rte",
                "energy efficiency",
                "energy-efficiency",
                "energy efficiencies",
                "energy-efficiencies",
            ),
        ),
        (
            "iron-air battery",
            (
                "iron-air batteries",
                "iron air battery",
                "iron air batteries",
                "iron-air cell",
                "iron-air cells",
                "iron air cell",
                "iron air cells",
                "iron-air",
                "iron air",
                "fe-air battery",
                "fe-air batteries",
                "fe-air cell",
                "fe-air cells",
                "soiab",
                "sofearb",
            ),
        ),
        ("long-duration energy storage", ("ldes", "multi-day storage")),
        ("degradation", ("capacity fade", "capacity loss", "deactivation", "durability loss")),
        ("cycle life", ("cycle lives", "cycling stability", "cycling durability", "service life")),
        ("temperature", ("operating temperature", "thermal condition")),
        ("current density", ("current densities", "c-rate", "charge rate", "discharge rate")),
        ("cost", ("costs", "capital cost", "capex", "opex", "lcos", "levelized cost")),
    ),
    (
        "chemistry",
        "configuration",
        "scale",
        "temperature",
        "current density",
        "duration",
        "boundary",
    ),
    ("iron-air battery", "long-duration energy storage"),
)

ECOLOGY_PROFILE = DomainProfile(
    "ecology",
    "Behavioural ecology",
    (
        ("goat", ("goats", "capra hircus", "caprine")),
        ("sheep", ("ovine", "ewes", "lambs")),
        (
            "foraging behaviour",
            (
                "foraging behavior",
                "feeding behaviour",
                "feeding behavior",
                "diet selection",
                "forage selection",
                "browsing behaviour",
                "browsing behavior",
                "grazing behaviour",
                "grazing behavior",
                "grazing patterns",
                "foraging",
                "browsing",
                "browse",
                "grazing",
            ),
        ),
        (
            "vegetation structure",
            (
                "sward structure",
                "sward height",
                "plant structure",
                "vegetation height",
                "canopy structure",
                "vegetation strata",
                "forage availability",
                "plant species",
                "plant communities",
                "leaf type",
                "broad-leaved",
                "fine-leaved",
                "woody species",
            ),
        ),
        ("habitat", ("rangeland", "pasture", "pastures", "shrubland", "woodland")),
        (
            "season",
            (
                "seasons",
                "seasonal",
                "wet season",
                "dry season",
                "spring",
                "summer",
                "autumn",
                "winter",
            ),
        ),
        (
            "browsing experience",
            (
                "foraging experience",
                "prior experience",
                "feeding experience",
                "experienced browsers",
            ),
        ),
        (
            "observation method",
            (
                "observation methods",
                "direct observation",
                "gps tracking",
                "gps sensor",
                "gps collar",
                "gps collars",
                "video recording",
                "accelerometer",
            ),
        ),
    ),
    (
        "species",
        "breed",
        "habitat",
        "season",
        "sex",
        "age",
        "stocking density",
        "observation method",
    ),
    ("goat", "sheep"),
)

PROFILES = {profile.id: profile for profile in (GENERIC_PROFILE, ENERGY_PROFILE, ECOLOGY_PROFILE)}


def detect_profile(question: str) -> DomainProfile:
    lowered = question.lower()
    # ``energy efficiency`` also belongs to economics (notably the rebound
    # effect), so it is useful for expansion after choosing the energy profile
    # but is too ambiguous to choose that profile by itself.
    scores = {}
    anchors = {}
    for profile in (ENERGY_PROFILE, ECOLOGY_PROFILE):
        score = 0
        for canonical, aliases in profile.vocabulary:
            candidates = (canonical, *aliases)
            if profile.id == "energy" and canonical == "round-trip efficiency":
                candidates = tuple(
                    value
                    for value in candidates
                    if not value.replace("-", " ").startswith("energy efficien")
                )
            score += any(_contains_term(lowered, alias) for alias in candidates)
        scores[profile.id] = score
        anchors[profile.id] = any(
            _contains_term(lowered, value)
            for canonical in profile.anchor_concepts
            for value in profile.expand(canonical)
        )
    best = max(scores, key=scores.get)
    # A single generic word such as ``temperature``, ``degradation`` or
    # ``grazing`` must not force an unrelated domain profile. One explicit
    # anchor, or two independent vocabulary concepts, is required.
    return PROFILES[best] if anchors[best] or scores[best] >= 2 else GENERIC_PROFILE


def contains_term(text: str, term: str) -> bool:
    """Match vocabulary terms as terms, so e.g. RTE is not found in 'reported'."""
    return _contains_term(text.lower(), term.lower())


def _contains_term(text: str, term: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None
