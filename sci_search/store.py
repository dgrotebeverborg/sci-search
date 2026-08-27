"""Validated evidence store and derived graph artifact."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from sci_search.models import (
    Evidence,
    ExtractionBundle,
    MeasurementResult,
    Publication,
    ScientificEntity,
    ScientificStatement,
    dataclass_to_dict,
)


@dataclass(slots=True)
class EvidenceStore:
    publications: dict[str, Publication] = field(default_factory=dict)
    entities: dict[str, ScientificEntity] = field(default_factory=dict)
    results: dict[str, MeasurementResult] = field(default_factory=dict)
    statements: dict[str, ScientificStatement] = field(default_factory=dict)
    evidence: dict[str, Evidence] = field(default_factory=dict)

    def add(self, bundle: ExtractionBundle) -> None:
        publication = bundle.publication
        existing = self.publications.get(publication.id)
        if existing is not None and existing != publication:
            raise ValueError(f"conflicting publication record: {publication.id}")
        self.publications[publication.id] = publication
        self._add_provenance_records(bundle.entities, self.entities, publication.id, "entity")
        for result in bundle.results:
            if result.provenance.publication_id != publication.id:
                raise ValueError(f"result provenance does not match publication: {result.id}")
            existing_result = self.results.get(result.id)
            if existing_result is not None and existing_result != result:
                raise ValueError(f"conflicting result record: {result.id}")
            self.results[result.id] = result
        self._add_provenance_records(
            bundle.statements, self.statements, publication.id, "statement"
        )
        self._add_provenance_records(bundle.evidence, self.evidence, publication.id, "evidence")

    @staticmethod
    def _add_provenance_records(
        records: tuple[object, ...], target: dict[str, object], publication_id: str, label: str
    ) -> None:
        for record in records:
            record_id = record.id
            if record.provenance.publication_id != publication_id:
                raise ValueError(f"{label} provenance does not match publication: {record_id}")
            existing = target.get(record_id)
            if existing is not None and existing != record:
                raise ValueError(f"conflicting {label} record: {record_id}")
            target[record_id] = record

    def query_results(self, metric: str) -> tuple[MeasurementResult, ...]:
        return tuple(
            sorted(
                (result for result in self.results.values() if result.metric == metric),
                key=lambda result: (result.provenance.publication_id, result.id),
            )
        )

    def to_evidence_artifact(self) -> dict[str, object]:
        return {
            "artifact_type": "scientific_evidence",
            "artifact_contract_version": "scientific_evidence_v1",
            "publications": [
                dataclass_to_dict(item)
                for item in sorted(self.publications.values(), key=lambda x: x.id)
            ],
            "entities": [
                dataclass_to_dict(item)
                for item in sorted(self.entities.values(), key=lambda x: x.id)
            ],
            "results": [
                dataclass_to_dict(item)
                for item in sorted(self.results.values(), key=lambda x: x.id)
            ],
            "statements": [
                dataclass_to_dict(item)
                for item in sorted(self.statements.values(), key=lambda x: x.id)
            ],
            "evidence": [
                dataclass_to_dict(item)
                for item in sorted(self.evidence.values(), key=lambda x: x.id)
            ],
        }

    def to_graph_artifact(self) -> dict[str, object]:
        nodes: list[dict[str, object]] = []
        relations: list[dict[str, object]] = []
        metric_ids: set[str] = set()
        technology_ids: set[str] = set()
        for publication in sorted(self.publications.values(), key=lambda item: item.id):
            nodes.append(
                {
                    "id": f"publication:{publication.id}",
                    "labels": ["Publication"],
                    "properties": dataclass_to_dict(publication),
                }
            )
        for result in sorted(self.results.values(), key=lambda item: item.id):
            metric_id = f"metric:{result.metric}"
            technology_id = f"technology:{_key_id(result.context.technology)}"
            if metric_id not in metric_ids:
                metric_ids.add(metric_id)
                nodes.append(
                    {"id": metric_id, "labels": ["Metric"], "properties": {"name": result.metric}}
                )
            if technology_id not in technology_ids:
                technology_ids.add(technology_id)
                nodes.append(
                    {
                        "id": technology_id,
                        "labels": ["Technology"],
                        "properties": {"name": result.context.technology},
                    }
                )
            nodes.append(
                {
                    "id": result.id,
                    "labels": ["MeasurementResult"],
                    "properties": dataclass_to_dict(result),
                }
            )
            relations.extend(
                (
                    _relation(
                        f"publication:{result.provenance.publication_id}",
                        "REPORTS_RESULT",
                        result.id,
                    ),
                    _relation(result.id, "MEASURES", metric_id),
                    _relation(result.id, "CONCERNS", technology_id),
                )
            )
        for statement in sorted(self.statements.values(), key=lambda item: item.id):
            nodes.append(
                {
                    "id": statement.id,
                    "labels": [
                        "ScientificStatement",
                        statement.kind.value.title().replace("_", ""),
                    ],
                    "properties": dataclass_to_dict(statement),
                }
            )
            relations.append(
                _relation(
                    f"publication:{statement.provenance.publication_id}",
                    "REPORTS_STATEMENT",
                    statement.id,
                )
            )
            relations.extend(
                _relation(statement.id, "DESCRIBES_RESULT", result_id)
                for result_id in statement.supports_result_ids
            )
        for evidence in sorted(self.evidence.values(), key=lambda item: item.id):
            nodes.append(
                {
                    "id": evidence.id,
                    "labels": ["Evidence"],
                    "properties": dataclass_to_dict(evidence),
                }
            )
            relations.append(
                _relation(
                    f"publication:{evidence.provenance.publication_id}",
                    "PROVIDES_EVIDENCE",
                    evidence.id,
                )
            )
            relations.extend(
                _relation(result_id, "SUPPORTED_BY", evidence.id)
                for result_id in evidence.result_ids
            )
        node_ids = {str(node["id"]) for node in nodes}
        for relation in relations:
            if relation["source"] not in node_ids or relation["target"] not in node_ids:
                raise ValueError(f"graph relation references missing node: {relation['id']}")
        return {
            "artifact_type": "scientific_evidence_graph",
            "artifact_contract_version": "scientific_evidence_graph_v1",
            "nodes": nodes,
            "relations": relations,
        }

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(self.to_evidence_artifact(), indent=2, sort_keys=True), encoding="utf-8"
        )


def _relation(source: str, relation_type: str, target: str) -> dict[str, str]:
    raw = f"{source}\x1f{relation_type}\x1f{target}"
    relation_id = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return {
        "id": f"relation:{relation_id}",
        "type": relation_type,
        "source": source,
        "target": target,
    }


def _key_id(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()[:20]
