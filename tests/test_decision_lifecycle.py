import json
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text, Table, Column
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from tests.utils import default_headers

from src.app.config import get_settings


def test_approve_and_reject_decision(monkeypatch, tmp_path):
    # shared in-memory sqlite
    db_file = tmp_path / "decision_lifecycle.sqlite"
    db_url = f"sqlite+pysqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("DATABASE_URL_RO", db_url)
    engine = create_engine(db_url, connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    SessionLocal = sessionmaker(bind=engine, future=True)
    import src.app.models.db as dbmod
    monkeypatch.setattr(dbmod, "engine", engine)
    monkeypatch.setattr(dbmod, "SessionLocal", SessionLocal)

    # register tables in metadata
    from src.app.models.orm import Base as ORMBase
    from sqlalchemy import Text as SA_Text, Boolean as SA_Boolean
    Table("customers", ORMBase.metadata, Column("id", SA_Text, primary_key=True), extend_existing=True)
    Table("decision_logs", ORMBase.metadata,
          Column("id", SA_Text, primary_key=True),
          Column("agent_name", SA_Text),
          Column("valid_from", SA_Text),
          Column("valid_to", SA_Text),
          Column("system_from", SA_Text),
          Column("system_to", SA_Text),
          Column("input_data", SA_Text),
          Column("retrieved_context", SA_Text),
          Column("agent_reasoning", SA_Text),
          Column("proposed_action", SA_Text),
          Column("policy_version", SA_Text),
          Column("approval_required", SA_Boolean),
          Column("approved_by", SA_Text),
          Column("approved_at", SA_Text),
          Column("execution_status", SA_Text),
          Column("error_message", SA_Text),
          extend_existing=True)
    ORMBase.metadata.create_all(engine, checkfirst=True)

    # insert a decision row
    with engine.connect() as conn:
        conn.execute(text("INSERT INTO decision_logs (id, agent_name, valid_from, input_data, policy_version, approval_required, execution_status) VALUES ('d1','pricing_agent', CURRENT_TIMESTAMP, '{}', 'v-test', 0, 'executed')"))
        conn.commit()

    # enable decision log writes in flags
    settings = get_settings()
    merged_flags = {}
    try:
        with open(settings.feature_flags_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
            if isinstance(loaded, dict):
                merged_flags.update(loaded)
    except Exception:
        pass
    merged_flags["DECISION_LOG_WRITES_ENABLED"] = True
    with open(settings.feature_flags_path, "w", encoding="utf-8") as f:
        json.dump(merged_flags, f)

    from src.app.main import create_app
    app = create_app()
    client = TestClient(app, headers=default_headers())

    # approve
    resp = client.post("/api/v1/decisions/d1/approve", params={"approved_by": "admin"})
    assert resp.status_code == 200
    with engine.connect() as conn:
        row = conn.execute(text("SELECT approved_by, execution_status, valid_to, system_to FROM decision_logs WHERE id='d1' LIMIT 1")).fetchone()
        assert row is not None
        assert row[0] == 'admin'
        assert row[1] == 'approved'

    # insert a new decision for reject test
    with engine.connect() as conn:
        conn.execute(text("INSERT INTO decision_logs (id, agent_name, valid_from, input_data, policy_version, approval_required, execution_status) VALUES ('d2','pricing_agent', CURRENT_TIMESTAMP, '{}', 'v-test', 1, 'pending')"))
        conn.commit()

    resp2 = client.post("/api/v1/decisions/d2/reject", params={"rejected_by": "admin", "reason": "policy"})
    assert resp2.status_code == 200
    with engine.connect() as conn:
        row = conn.execute(text("SELECT approved_by, execution_status, error_message FROM decision_logs WHERE id='d2' LIMIT 1")).fetchone()
        assert row is not None
        assert row[0] == 'admin'
        assert row[1] == 'rejected'
        assert row[2] == 'policy'
