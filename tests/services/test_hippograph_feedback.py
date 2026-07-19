"""Unit tests for hippograph feedback injection (services/hippograph_feedback.py)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import attribution
from src.app.services.hippograph_feedback import build_hippograph_insights


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


def test_insights_from_uid_seed_reward_weighted(db):
    _tev(db, "user", "u1", "product", "GAM-1")
    _tev(db, "user", "u1", "product", "GAM-2")
    db.execute(text(
        "INSERT INTO conversion_event (id, decision_id, order_id, uid_hash, attributed_skus_json, "
        "value_cents, converted_at) VALUES ('c1','D1','O1','u1','[\"GAM-1\"]',500000,'2020-01-01')"))
    db.commit()
    ins = build_hippograph_insights(db, uid_hash="u1", top_k=5)
    ids = [i["id"] for i in ins]
    assert "GAM-1" in ids
    assert ids.index("GAM-1") < ids.index("GAM-2")  # the converter ranks first


def test_insights_seed_from_sku_surfaces_co_occurrence(db):
    _tev(db, "user", "u1", "product", "GAM-1")
    _tev(db, "user", "u2", "product", "GAM-1")
    _tev(db, "user", "u2", "product", "GAM-9")  # GAM-9 co-occurs with GAM-1 via u2
    db.commit()
    ids = [i["id"] for i in build_hippograph_insights(db, seed_skus=["GAM-1"], top_k=8)]
    assert "GAM-9" in ids or "u2" in ids  # a related entity surfaces (2-hop)


def test_empty_when_seed_not_in_graph(db):
    _tev(db, "user", "u1", "product", "GAM-1")
    db.commit()
    assert build_hippograph_insights(db, uid_hash="nobody") == []


def test_empty_on_bad_db():
    assert build_hippograph_insights(None, uid_hash="u1") == []


def test_insights_exclude_internal_nodes(db):
    # a decision→product edge + the seed user; insights must carry the PRODUCT, not the
    # decision/user plumbing nodes (GPT-5.5: recall was surfacing a decision + the user node).
    _tev(db, "decision", "D1", "product", "GAM-1")
    _tev(db, "user", "u1", "product", "GAM-1")
    db.commit()
    ins = build_hippograph_insights(db, uid_hash="u1", seed_skus=["GAM-1"], top_k=8)
    ids = [i["id"] for i in ins]
    assert all(i["kind"] in {"product", "brand", "finding", "segment"} for i in ins)
    assert not any(x.startswith("decision:") for x in ids)
    assert "u1" not in ids  # the seed user is excluded
