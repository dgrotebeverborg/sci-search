from datetime import UTC, datetime
from uuid import uuid4

from sci_search.infrastructure.database import Database
from sci_search.infrastructure.tables import Base, ResearchRunRow


def test_dashboard_publication_is_immutable_and_rejects_stale_feedback(tmp_path):
    from sci_search.infrastructure.dashboard_repository import DashboardRepository

    database = Database(f"sqlite:///{tmp_path / 'dashboard.db'}")
    Base.metadata.create_all(database.engine)
    run_id, project_id = uuid4(), uuid4()
    with database.transaction() as session:
        session.add(
            ResearchRunRow(
                id=run_id,
                project_id=project_id,
                created_by_user_id=uuid4(),
                question="Why?",
                configuration_json={},
                status="complete",
            )
        )
    with database.transaction() as session:
        repo = DashboardRepository(session)
        assert (
            repo.publish(
                str(project_id),
                str(run_id),
                {"answer": "first"},
                feedback_sequence=0,
                created_at=datetime.now(UTC),
            )
            == 1
        )
        assert (
            repo.publish(
                str(project_id),
                str(run_id),
                {"answer": "duplicate"},
                feedback_sequence=0,
                created_at=datetime.now(UTC),
            )
            == 1
        )
    with database.transaction() as session:
        assert (
            DashboardRepository(session).get(str(project_id), str(run_id)).snapshot_json["answer"]
            == "first"
        )


def test_production_adapter_exposes_saved_history():
    from sci_search.infrastructure.production_services import DatabaseResearchApiService

    assert "get_dashboard" in DatabaseResearchApiService.__dict__
