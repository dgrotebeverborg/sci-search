from pathlib import Path
from uuid import uuid4

from sci_search.application.memory import MemoryContext
from sci_search.infrastructure.database import Database
from sci_search.infrastructure.filesystem_blobs import FilesystemBlobStore
from sci_search.infrastructure.sql_memory import SqlScientificMemory
from sci_search.infrastructure.tables import Base, ProjectRow
from sci_search.question_planning import plan_question


def test_sql_memory_survives_worker_restart_and_projects_are_isolated(tmp_path: Path):
    database = Database(f"sqlite:///{tmp_path / 'db'}")
    Base.metadata.create_all(database.engine)
    project_a, project_b = uuid4(), uuid4()
    with database.transaction() as session:
        for project_id in (project_a, project_b):
            session.add(
                ProjectRow(
                    id=project_id,
                    workspace_id=uuid4(),
                    owner_user_id=uuid4(),
                    name="test",
                    is_private=True,
                )
            )
    blobs = FilesystemBlobStore(tmp_path / "objects")

    def memory(scratch, project):
        return SqlScientificMemory(
            tmp_path / scratch,
            MemoryContext("alice", str(project)),
            database,
            blobs,
            authorize=lambda context: None,
        )

    first = memory("worker-a", project_a)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "manifest.json").write_text('{"documents": []}')
    payload = {
        "research_run": {
            "candidates": [
                {"id": "paper-a", "title": "iron air battery efficiency", "doi": "10.123/test"}
            ]
        },
        "evidence": [],
    }
    first.ingest_run("run-a", "iron air battery efficiency", corpus, payload)
    assert first.stats()["publications"] == 0
    first.publish_pending(revision=1)
    reopened = memory("worker-b", project_a)
    assert reopened.candidates(plan_question("iron air battery efficiency"))[0].id == "paper-a"
    assert (
        memory("worker-c", project_b).candidates(plan_question("iron air battery efficiency")) == ()
    )
    reopened.ingest_run("run-a", "iron air battery efficiency", corpus, payload)
    assert reopened.publish_pending(revision=1).get("new_nodes", 0) == 0


def test_cached_source_hash_is_verified_before_reuse(tmp_path: Path):
    import hashlib
    import json

    from sci_search.discovery import PublicationCandidate
    from sci_search.scientific_memory import ScientificMemory

    memory = ScientificMemory(tmp_path / "memory")
    digest = hashlib.sha256(b"original").hexdigest()
    (memory.documents / f"{digest}.txt").write_text("tampered")
    with memory._connect() as connection:
        connection.execute(
            "INSERT INTO publications VALUES (?,?,?,?,?,?,?,?)",
            (
                "paper",
                "title:iron air battery",
                json.dumps({"title": "iron air battery"}),
                "iron air battery",
                digest,
                f"documents/{digest}.txt",
                None,
                "now",
            ),
        )
    candidate = PublicationCandidate(
        id="paper",
        title="iron air battery",
        abstract="",
        year=None,
        doi=None,
        authors=(),
        publication_type="article",
        source_url=None,
    )
    assert memory.reuse_document(candidate, tmp_path / "corpus") is None


def test_concurrent_worker_checkpoints_merge_and_sources_rehydrate(tmp_path: Path):
    from sci_search.corpus import load_corpus
    from sci_search.discovery import PublicationCandidate
    from sci_search.generic_research import GenericResearchEngine

    database = Database(f"sqlite:///{tmp_path / 'concurrent.db'}")
    Base.metadata.create_all(database.engine)
    project = uuid4()
    with database.transaction() as session:
        session.add(
            ProjectRow(
                id=project,
                workspace_id=uuid4(),
                owner_user_id=uuid4(),
                name="test",
                is_private=True,
            )
        )
    blobs = FilesystemBlobStore(tmp_path / "blobs")
    context = MemoryContext("alice", str(project))
    first = SqlScientificMemory(
        tmp_path / "first", context, database, blobs, authorize=lambda context: None
    )
    second = SqlScientificMemory(
        tmp_path / "second", context, database, blobs, authorize=lambda context: None
    )
    corpus = Path(__file__).resolve().parents[2] / "fixtures/iron_air_pilot"
    payload = (
        GenericResearchEngine(load_corpus(corpus))
        .investigate("What efficiency is reported?")
        .to_dict()
    )
    first.ingest_run("run-a", payload["question"], corpus, payload)
    second.ingest_run("run-b", payload["question"], corpus, payload)
    first.publish_pending()
    second.publish_pending()
    third = SqlScientificMemory(
        tmp_path / "third", context, database, blobs, authorize=lambda context: None
    )
    assert third.stats()["runs"] == 2
    assert list(third.documents.iterdir()) == []
    paper = load_corpus(corpus)[0].publication
    candidate = PublicationCandidate(
        id=paper.id,
        title=paper.title,
        abstract="",
        doi=paper.doi,
        year=paper.year,
        authors=(),
        publication_type="article",
        source_url=None,
    )
    assert third.reuse_document(candidate, tmp_path / "new-corpus") is not None
    assert list(third.documents.iterdir())


def test_legacy_import_requires_ownership_and_is_idempotent(tmp_path: Path):
    import json

    from sci_search.scientific_memory import ScientificMemory
    from scripts.import_scientific_memory import import_memory

    source = ScientificMemory(tmp_path / "source")
    assert (
        import_memory(source.root, tmp_path / "dest", "project", dry_run=True)["status"]
        == "blocked_unknown_ownership"
    )
    (source.root / ".memory-owner.json").write_text(
        json.dumps({"project_id": "project", "user_id": "alice"})
    )
    assert (
        import_memory(source.root, tmp_path / "dest", "project", dry_run=True)["status"]
        == "validated"
    )
    assert (
        import_memory(source.root, tmp_path / "dest", "project", dry_run=False)["status"]
        == "imported"
    )
    assert (
        import_memory(source.root, tmp_path / "dest", "project", dry_run=False)["status"]
        == "already_imported"
    )


def test_missing_projection_checkpoint_replays_archive_once(tmp_path: Path):
    import json
    import zipfile
    from datetime import UTC, datetime
    from io import BytesIO

    from sci_search.infrastructure.sql_memory import recover_project_memory
    from sci_search.infrastructure.tables import DashboardRevisionRow

    database = Database(f"sqlite:///{tmp_path / 'replay.db'}")
    Base.metadata.create_all(database.engine)
    project, run = uuid4(), uuid4()
    with database.transaction() as session:
        session.add(
            ProjectRow(
                id=project,
                workspace_id=uuid4(),
                owner_user_id=uuid4(),
                name="test",
                is_private=True,
            )
        )
    blobs = FilesystemBlobStore(tmp_path / "blobs")
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "internal/investigation.json",
            json.dumps(
                {
                    "question": "iron air battery efficiency",
                    "research_run": {
                        "candidates": [{"id": "paper", "title": "iron air battery efficiency"}]
                    },
                    "evidence": [],
                }
            ),
        )
        archive.writestr("internal/corpus/manifest.json", '{"documents": []}')
    payload = output.getvalue()
    blob = blobs.put(BytesIO(payload), len(payload))
    with database.transaction() as session:
        session.add(
            DashboardRevisionRow(
                project_id=project,
                run_id=run,
                revision=1,
                feedback_sequence=0,
                snapshot_json={"source_archive_key": blob.key, "internal_run_id": "internal"},
                created_at=datetime.now(UTC),
            )
        )
    memory = SqlScientificMemory(
        tmp_path / "scratch",
        MemoryContext("alice", str(project)),
        database,
        blobs,
        authorize=lambda context: None,
    )
    assert recover_project_memory(memory) == {"recovered": 1, "pending": 0}
    assert recover_project_memory(memory) == {"recovered": 0, "pending": 0}
    assert memory.candidates(plan_question("iron air battery efficiency"))[0].id == "paper"


def test_legacy_and_repeated_failures_cannot_starve_newer_memory(tmp_path: Path):
    import json
    import zipfile
    from datetime import UTC, datetime, timedelta
    from io import BytesIO

    from sci_search.infrastructure.sql_memory import recover_project_memory
    from sci_search.infrastructure.tables import DashboardRevisionRow

    for legacy in (True, False):
        case = tmp_path / str(legacy)
        case.mkdir()
        database = Database(f"sqlite:///{case / 'db'}")
        Base.metadata.create_all(database.engine)
        project = uuid4()
        blobs = FilesystemBlobStore(case / "blobs")
        body = BytesIO()
        with zipfile.ZipFile(body, "w") as archive:
            archive.writestr("internal/corpus/manifest.json", '{"documents": []}')
            archive.writestr(
                "internal/investigation.json",
                json.dumps(
                    {
                        "question": "iron air battery efficiency",
                        "research_run": {
                            "candidates": [{"id": "good", "title": "iron air battery efficiency"}]
                        },
                        "evidence": [],
                    }
                ),
            )
        payload = body.getvalue()
        blob = blobs.put(BytesIO(payload), len(payload))
        bad = blobs.put(BytesIO(b"broken archive"), 14)
        with database.transaction() as session:
            session.add(
                ProjectRow(
                    id=project,
                    workspace_id=uuid4(),
                    owner_user_id=uuid4(),
                    name="test",
                    is_private=True,
                )
            )
            for index in range(31):
                snapshot = (
                    {"rebuild_available": False}
                    if legacy
                    else {"source_archive_key": bad.key, "internal_run_id": "internal"}
                )
                if index == 30:
                    snapshot = {"source_archive_key": blob.key, "internal_run_id": "internal"}
                session.add(
                    DashboardRevisionRow(
                        project_id=project,
                        run_id=uuid4(),
                        revision=1,
                        feedback_sequence=0,
                        snapshot_json=snapshot,
                        created_at=datetime.now(UTC) + timedelta(seconds=index),
                    )
                )
        memory = SqlScientificMemory(
            case / "scratch",
            MemoryContext("alice", str(project)),
            database,
            blobs,
            authorize=lambda context: None,
        )
        first = recover_project_memory(memory, limit=25)
        second = recover_project_memory(memory, limit=25)
        assert first["recovered"] + second["recovered"] == 1
        assert memory.candidates(plan_question("iron air battery efficiency"))[0].id == "good"
        if legacy:
            assert first.get("unavailable", 0) == 30
            assert second == {"recovered": 0, "pending": 0}


def test_replaying_older_revision_cannot_regress_scientific_projection(tmp_path: Path):
    from sci_search.infrastructure.local_memory import LocalScientificMemory

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "manifest.json").write_text('{"documents": []}')
    memory = LocalScientificMemory(tmp_path / "root", MemoryContext("alice", "project"))
    for revision, adjective in ((2, "Updated"), (1, "Outdated")):
        payload = {
            "research_run": {
                "candidates": [
                    {
                        "id": "paper",
                        "title": f"{adjective} iron air battery efficiency",
                        "doi": "10.1/paper",
                    }
                ]
            },
            "evidence": [],
        }
        memory.ingest_run("run", "iron air battery efficiency", corpus, payload)
        memory.publish_pending(revision=revision)
    assert memory.candidates(plan_question("iron air battery efficiency"))[0].title.startswith(
        "Updated"
    )
    revisions = [node for node in memory.graph_snapshot()["nodes"] if node["type"] == "Revision"]
    assert {node["properties"]["revision"] for node in revisions} == {1, 2}
