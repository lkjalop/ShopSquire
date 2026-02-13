import json
from fastapi.testclient import TestClient
from src.app.config import get_settings
from src.app.models.orm import Product, DraftOrder, Base
from sqlalchemy import create_engine, text, Table, Column, Text as SA_Text
from sqlalchemy.orm import sessionmaker
from tests.utils import default_headers



def test_retrieve_uses_draft_order_as_canonical(monkeypatch):
    # Use in-memory SQLite and patch the app's db engine/session
    from sqlalchemy.pool import StaticPool
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    SessionLocal = sessionmaker(bind=engine, future=True)
    import src.app.models.db as dbmod
    monkeypatch.setattr(dbmod, "engine", engine)
    monkeypatch.setattr(dbmod, "SessionLocal", SessionLocal)

    # Register a minimal customers table in ORM metadata so FK can be resolved
    Table("customers", Base.metadata, Column("id", SA_Text, primary_key=True), Column("email", SA_Text), Column("name", SA_Text), extend_existing=True)
    # Instead of DB writes, monkeypatch CatalogRepository methods to return draft order and computed total
    from src.app.repositories.catalog import CatalogRepository
    class FakeDraft:
        def __init__(self, id, line_items):
            self.id = id
            self.line_items = line_items

    fake_draft = FakeDraft("draft-1", [{"sku": "TESTSKU", "quantity": 2}])
    monkeypatch.setattr(CatalogRepository, "get_draft_order", lambda self, did: fake_draft)
    monkeypatch.setattr(CatalogRepository, "compute_cart_total", lambda self, did: 1234 * 2)
    draft_id = fake_draft.id

    # set flags to enable pricing capability
    settings = get_settings()
    with open(settings.feature_flags_path, "w", encoding="utf-8") as f:
        json.dump({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"pricing": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
        }, f, ensure_ascii=False, indent=2)

    # monkeypatch Memory.get_context to include draft_cart_id
    from src.app.services.memory import Memory
    monkeypatch.setattr(Memory, "get_context", lambda self, uid: {"kv": {"draft_cart_id": draft_id}})

    # prepare session KV to reference draft_cart_id using a FakeRedis
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
    fake.setex("session:uid123:kv_state", 3600, json.dumps({"draft_cart_id": draft_id}))

    from src.app.main import create_app
    app = create_app()
    client = TestClient(app, headers=default_headers())
    resp = client.get("/api/v1/pricing/suggest", params={"uid": "uid123", "cart_total_cents": 100})
    assert resp.status_code == 200
    data = resp.json()
    # computed cart total should be 1234 * 2 = 2468
    assert data["proposal"]["cart_total_cents"] == 2468