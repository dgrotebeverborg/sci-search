from __future__ import annotations

import unittest
from decimal import Decimal

from sci_search.models import Condition, ExtractionMethod, Provenance


class ModelTests(unittest.TestCase):
    def test_provenance_requires_complete_offsets(self) -> None:
        with self.assertRaisesRegex(ValueError, "offsets"):
            Provenance(
                publication_id="paper",
                source_document="paper.txt",
                section="results",
                passage="supported text",
                passage_start=2,
                extraction_method=ExtractionMethod("fixture", "1"),
            )

    def test_condition_rejects_non_finite_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite"):
            Condition("temperature", Decimal("NaN"), "degC")
