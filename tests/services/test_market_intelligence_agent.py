"""Market Intelligence Agent + findings persistence (read-fast)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.market_analysis import MarketFinding, load_recent_findings, persist_findings
from src.app.services.market_intelligence_agent import gather_market_context


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


# ── findings persistence (batch writes, hot path reads) ──────────────────────
def test_persist_then_load_findings(db):
    findings = [
        MarketFinding("demand_shift", None, "critical", 0.9, "spike", {"latest": 500}, "daily"),
        MarketFinding("inventory_demand_mismatch", "framework 16", "warn", 0.6, "unmet", {"n": 4}, "recent"),
    ]
    assert persist_findings(db, findings) == 2
    db.commit()
    loaded = load_recent_findings(db, limit=10)
    types = {f.finding_type for f in loaded}
    assert types == {"demand_shift", "inventory_demand_mismatch"}
    fw = next(f for f in loaded if f.entity_ref == "framework 16")
    assert fw.evidence["n"] == 4 and fw.confidence == 0.6


def test_load_findings_empty_safe(db):
    assert load_recent_findings(db) == []  # no table/rows → []
    assert persist_findings(db, []) == 0


# ── agent gating ─────────────────────────────────────────────────────────────
def test_agent_includes_findings_when_market_query(db):
    persist_findings(db, [MarketFinding("demand_shift", None, "critical", 0.9, "spike", {}, "daily")])
    db.commit()
    ctx = gather_market_context(db, query="what laptops are trending right now", uid_hash="u1")
    assert ctx["needs_market_evidence"] is True
    assert "demand" in ctx["evidence_kinds"]
    assert any(f["finding_type"] == "demand_shift" for f in ctx["market_findings"])


def test_agent_skips_findings_for_plain_query(db):
    persist_findings(db, [MarketFinding("demand_shift", None, "critical", 0.9, "spike", {}, "daily")])
    db.commit()
    ctx = gather_market_context(db, query="a laptop for university under 1500", uid_hash="u1")
    assert ctx["needs_market_evidence"] is False
    assert ctx["market_findings"] == []  # plain query → no market findings (no cost)


def test_agent_never_raises_on_bad_db():
    ctx = gather_market_context(None, query="trending laptops")
    assert ctx["market_findings"] == [] and ctx["hippograph_insights"] == []
