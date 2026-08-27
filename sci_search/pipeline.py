"""Small end-to-end local corpus pipeline."""

from __future__ import annotations

from pathlib import Path

from sci_search.corpus import load_corpus
from sci_search.extraction import RuleBasedEnergyExtractor, ScientificExtractor
from sci_search.store import EvidenceStore


def build_evidence_store(
    corpus_directory: Path,
    *,
    extractor: ScientificExtractor | None = None,
) -> tuple[EvidenceStore, tuple[str, ...]]:
    selected_extractor = extractor or RuleBasedEnergyExtractor()
    store = EvidenceStore()
    warnings: list[str] = []
    for document in load_corpus(corpus_directory):
        bundle = selected_extractor.extract(document)
        store.add(bundle)
        warnings.extend(bundle.warnings)
    return store, tuple(warnings)
