"""DB-backed hippograph projection + the read-only /api/v1/hippograph/recall endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.main import app
from src.app.services import attribution
from src.app.services.hippograph import recall
from src.app.services.hippograph_db import build_from_db
from tests.utils import default_headers


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    s.execute(text(
        "CREATE TABLE decision_trace_events (id TEXT, tenant_id TEXT NOT NULL DEFAULT 'default', trace_id TEXT, event_type TEXT, "
        "source_type TEXT, source_id TEXT, target_type TEXT, target_id TEXT, payload TEXT, "
        "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
    attribution.ensure_tables(s)
    s.commit()
    try:
        yield s
    finally:
        s.close()


def _tev(s, st, si, tt, ti):
    s.execute(text(
        "INSERT INTO decision_trace_events (id, trace_id, event_type, source_type, source_id, "
        "target_type, target_id, payload) VALUES (:id,'T','e',:st,:si,:tt,:ti,'{}')"),
        {"id": f"{si}-{ti}", "st": st, "si": si, "tt": tt, "ti": ti})


def test_build_from_db_is_tenant_isolated(db):
    db.execute(text(
        "INSERT INTO decision_trace_events (id,tenant_id,trace_id,event_type,source_type,source_id,"
        "target_type,target_id,payload) VALUES "
        "('ta','tenant-a','TA','viewed','user','same-user','product','SKU-A','{}'),"
        "('tb','tenant-b','TB','viewed','user','same-user','product','SKU-B','{}')"))
    db.execute(text(
        "INSERT INTO conversion_event (id,tenant_id,decision_id,order_id,uid_hash,attributed_skus_json,"
        "value_cents,converted_at) VALUES "
        "('ca','tenant-a','DA','OA','same-user','[\"SKU-A\"]',10000,'2026-07-18'),"
        "('cb','tenant-b','DB','OB','same-user','[\"SKU-B\"]',999999,'2026-07-18')"))
    db.commit()

    graph = build_from_db(db, tenant_id="tenant-a")

    assert "SKU-A" in graph.nodes
    assert "SKU-B" not in graph.nodes
    assert "decision:DB" not in graph.nodes


def test_build_from_db_projects_trace_and_reward(db):
    _tev(db, "user", "u1", "product", "GAM-1")
    _tev(db, "user", "u1", "product", "GAM-2")
    db.execute(text(
        "INSERT INTO conversion_event (id, decision_id, order_id, uid_hash, attributed_skus_json, "
        "value_cents, converted_at) VALUES ('c1','D1','O1','u1','[\"GAM-1\"]',500000,'2020-01-01')"))
    db.commit()
    g = build_from_db(db, tenant_id="default")
    # SKUs stayed canonical (sku_pattern), not name-mangled
    assert "GAM-1" in g.nodes and "GAM-2" in g.nodes
    assert g.nodes["GAM-1"].weight > 0  # conversion reward applied
    order = [n for n, _ in recall(g, ["u1"], top_k=5)]
    assert order.index("GAM-1") < order.index("GAM-2")  # the converter is recalled first


def test_build_from_db_none_is_empty():
    g = build_from_db(None, tenant_id="default")
    assert g.nodes == {} and g.edges == {}


def test_build_from_db_requires_explicit_tenant(db):
    with pytest.raises(ValueError, match="tenant_id is required"):
        build_from_db(db, tenant_id="")


def test_build_from_db_include_findings_projects_finding_nodes(db):
    # seed market_signal with recurring zero-result searches → inventory_demand_mismatch finding
    from src.app.services.market_signal import ensure_table as _ms_ensure
    _ms_ensure(db)
    # NOTE (2026-07-12): detect_inventory_demand_mismatch was hardened against poisoning — it
    # requires DISTINCT-user identity (uid_hash/session) per zero-result search and gates on
    # >= min_unmet(3) distinct users. Seed 4 DISTINCT users so the finding legitimately surfaces
    # (an anonymous-only seed can no longer, by design).
    for i in range(4):
        db.execute(text("INSERT INTO market_signal (id, signal_type, source, dedup_key, trust_score, "
                        "payload_json, occurred_at) VALUES (:id,'demand','search_events',:k,0.8,:pl,'2026-06-24T10:00:00')"),
                   {"id": f"ms{i}", "k": f"ms{i}",
                    "pl": '{"query": "framework 16", "result_count": 0, "uid_hash": "user-%d"}' % i})
    db.commit()
    base = build_from_db(db, tenant_id="default", include_findings=False)
    enriched = build_from_db(db, tenant_id="default", include_findings=True)
    assert not any(n.startswith("finding:") for n in base.nodes)  # off by default
    assert any(n.startswith("finding:inventory_demand_mismatch") for n in enriched.nodes)  # M3 → hippograph


def test_build_from_db_degrades_when_tables_absent():
    # an engine with no tables → best-effort empty graph, never raises
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        g = build_from_db(s, tenant_id="default")
        assert g.nodes == {}
    finally:
        s.close()


# ── endpoint contract (read-only, role-gated) ────────────────────────────────
_client = TestClient(app, headers=default_headers())


def test_hippograph_recall_endpoint_contract():
    r = _client.get("/api/v1/hippograph/recall", params={"seed": "GAM-1", "kind": "product", "top_k": 5})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["kind"] == "product"
    assert isinstance(b["recall"], list)
    assert "node_count" in b and "edge_count" in b
