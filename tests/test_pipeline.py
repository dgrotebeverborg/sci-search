from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from sci_search.pipeline import build_evidence_store

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "fixtures" / "iron_air_pilot"


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store, cls.warnings = build_evidence_store(CORPUS)

    def test_extracts_and_normalizes_round_trip_efficiency(self) -> None:
        results = self.store.query_results("round_trip_efficiency")
        self.assertEqual(
            [result.quantity.value for result in results],
            [Decimal(62), Decimal("64.00"), Decimal(70)],
        )
        self.assertEqual({result.quantity.unit for result in results}, {"%"})
        self.assertEqual(self.warnings, ())

    def test_preserves_exact_passage_offsets_and_context(self) -> None:
        result = self.store.query_results("round_trip_efficiency")[0]
        source = (CORPUS / result.provenance.source_document).read_text(encoding="utf-8")
        self.assertEqual(
            source[result.provenance.passage_start : result.provenance.passage_end],
            result.provenance.passage,
        )
        self.assertEqual(result.provenance.page, 3)
        self.assertEqual(result.provenance.section, "results")
        conditions = {item.name: item for item in result.context.conditions}
        self.assertEqual(conditions["temperature"].value, Decimal(25))
        self.assertEqual(conditions["current_density"].unit, "mA/cm^2")

    def test_graph_projection_keeps_result_provenance(self) -> None:
        graph = self.store.to_graph_artifact()
        result_nodes = [node for node in graph["nodes"] if "MeasurementResult" in node["labels"]]
        self.assertEqual(len(result_nodes), 3)
        self.assertTrue(all(node["properties"]["provenance"]["passage"] for node in result_nodes))
        self.assertEqual(
            sum(relation["type"] == "REPORTS_RESULT" for relation in graph["relations"]), 3
        )

    def test_extraction_creates_traceable_claims_assumptions_and_evidence(self) -> None:
        self.assertEqual(len(self.store.statements), 3)
        self.assertEqual(len(self.store.evidence), 3)
        kinds = {statement.kind.value for statement in self.store.statements.values()}
        self.assertEqual(kinds, {"claim", "assumption"})
        for statement in self.store.statements.values():
            self.assertTrue(statement.supports_result_ids)
            self.assertTrue(statement.provenance.passage)
