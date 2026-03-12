import json
import os
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from tests.utils import default_headers

# Test will create app after configuring test engine and dependencies
from src.app.config import get_settings
from src.app.models.orm import Base, Product, DraftOrder


def test_decision_logs_include_retrieved_context_and_policy(monkeypatch, tmp_path):
    # Use in-memory SQLite for this test
    from sqlalchemy.pool import StaticPool
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    SessionLocal = sessionmaker(bind=engine, future=True)
    # patch app's engine and SessionLocal
    import src.app.models.db as dbmod
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    try:
        dbmod.set_engine(engine)
    except Exception:
        monkeypatch.setattr(dbmod, "engine", engine)
    monkeypatch.setattr(dbmod, "SessionLocal", SessionLocal)

    # Register minimal customers and decision_logs table in ORM metadata so FK/inserts succeed
    from src.app.models.orm import Base as ORMBase
    from sqlalchemy import Table, Column, Text as SA_Text, Boolean as SA_Boolean
    Table("customers", ORMBase.metadata, Column("id", SA_Text, primary_key=True), Column("email", SA_Text), Column("name", SA_Text), extend_existing=True)
    Table(
        "decision_logs",
        ORMBase.metadata,
        Column("id", SA_Text, primary_key=True),
        Column("agent_name", SA_Text, nullable=False),
        Column("valid_from", SA_Text, nullable=False),
        Column("valid_to", SA_Text),
        Column("system_from", SA_Text),
        Column("system_to", SA_Text),
        Column("input_data", SA_Text, nullable=False),
        Column("retrieved_context", SA_Text),
        Column("agent_reasoning", SA_Text),
        Column("proposed_action", SA_Text),
        Column("policy_version", SA_Text, nullable=False),
        Column("approval_required", SA_Boolean),
        Column("approved_by", SA_Text),
        Column("approved_at", SA_Text),
        Column("execution_status", SA_Text),
        Column("error_message", SA_Text),
        extend_existing=True,
    )
    # create tables including decision_logs from ORM Base
    ORMBase.metadata.create_all(engine, checkfirst=True)

    # Insert product and draft order
    with SessionLocal() as s:
        p = Product(sku="P1", name="P1", price_cents=1000)
        s.add(p)
        s.commit()
        s.refresh(p)
        d = DraftOrder(line_items=[{"sku": "P1", "quantity": 1}])
        s.add(d)
        s.commit()
        s.refresh(d)
        draft_id = d.id

    # enable decision log writes and policy version via feature flags
    settings = get_settings()
    with open(settings.feature_flags_path, "w", encoding="utf-8") as f:
        json.dump({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"pricing": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": True,
            "POLICY_VERSION": "v-test-1",
        }, f, ensure_ascii=False, indent=2)

    # set session kv to reference draft using a FakeRedis
    class FakeRedis:
        def __init__(self):
            self.store = {}

        def setex(self, k, ttl, v):
            self.store[k] = v

        def get(self, k):
            return self.store.get(k)

        def ping(self):
            return True

    from src.app import deps as deps_mod
    fake = FakeRedis()
    monkeypatch.setattr(deps_mod, "get_redis", lambda: fake)
    fake.setex("session:uid_decision:kv_state", 3600, json.dumps({"draft_cart_id": draft_id}))

    # create TestClient after patching engine and deps
    from src.app.main import create_app
    app = create_app()
    client = TestClient(app, headers=default_headers())
    # call pricing suggest to create a decision_log
    resp = client.get("/api/v1/pricing/suggest", params={"uid": "uid_decision", "cart_total_cents": 500})
    assert resp.status_code == 200

    # query decision_logs table for last insert
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM decision_logs ORDER BY rowid DESC LIMIT 1")).fetchone()
        assert row is not None
        m = getattr(row, "_mapping", None) or {}
        retrieved = m.get("retrieved_context")
        policy_version = m.get("policy_version")
        approval_required = m.get("approval_required")
        execution_status = m.get("execution_status")
        assert retrieved is not None
        assert json.loads(retrieved)  # valid JSON
        assert policy_version == "v-test-1"
        assert approval_required in (0, 1, True, False)
        assert execution_status in ("executed", "pending")
