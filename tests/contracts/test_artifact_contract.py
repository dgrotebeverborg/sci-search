import pytest

from sci_search.store import EvidenceStore


@pytest.fixture
def evidence_store() -> EvidenceStore:
    return EvidenceStore()


def test_evidence_artifact_keeps_versioned_top_level_contract(evidence_store):
    artifact = evidence_store.to_evidence_artifact()

    assert artifact["artifact_type"] == "scientific_evidence"
    assert artifact["artifact_contract_version"] == "scientific_evidence_v1"
    assert set(artifact) == {
        "artifact_type",
        "artifact_contract_version",
        "publications",
        "entities",
        "results",
        "statements",
        "evidence",
    }


def test_graph_artifact_keeps_versioned_top_level_contract(evidence_store):
    artifact = evidence_store.to_graph_artifact()

    assert artifact["artifact_type"] == "scientific_evidence_graph"
    assert artifact["artifact_contract_version"] == "scientific_evidence_graph_v1"
    assert set(artifact) == {
        "artifact_type",
        "artifact_contract_version",
        "nodes",
        "relations",
    }
