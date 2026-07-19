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


# ── S2: query-scoped findings + structured/narration evidence ─────────────────
def test_findings_are_query_scoped_not_a_recency_dump(db):
    # one finding tied to a SKU we surface, one tied to an unrelated SKU, one global
    persist_findings(db, [
        MarketFinding("demand_shift", "GAM-1", "critical", 0.9, "GAM-1 demand spiking", {}, "daily"),
        MarketFinding("demand_shift", "ZZZ-9", "warn", 0.8, "unrelated product", {}, "daily"),
        MarketFinding("conversion_anomaly", None, "warn", 0.7, "site-wide conversion dip", {}, "daily"),
    ])
    db.commit()
    ctx = gather_market_context(db, query="is GAM-1 trending", uid_hash="u1", result_skus=["GAM-1"])
    summaries = {f["summary"] for f in ctx["market_findings"]}
    assert "GAM-1 demand spiking" in summaries          # entity matches a surfaced SKU → in scope
    assert "site-wide conversion dip" in summaries        # global → always in scope
    assert "unrelated product" not in summaries           # different SKU, not in query → scoped out


def test_structured_and_narration_evidence_emitted(db):
    persist_findings(db, [MarketFinding("demand_shift", None, "critical", 0.95, "demand surging 3x", {}, "daily")])
    db.commit()
    ctx = gather_market_context(db, query="what is trending in the market now", uid_hash="u1")
    assert ctx["market_evidence"]["findings"], "structured evidence object populated"
    assert "demand surging 3x" in ctx["narration_note"]   # narration-ready preamble carries the summary
    assert "invent" in ctx["narration_note"].lower()       # the guard phrasing is present


def test_recall_surfaces_finding_tied_to_surfaced_product(db):
    # a finding on GAM-7 must recall when GAM-7 is a seed (finding↔entity edge + include_findings)
    from src.app.services.hippograph_feedback import build_hippograph_insights
    persist_findings(db, [MarketFinding("demand_shift", "GAM-7", "critical", 0.9, "spike", {}, "daily")])
    db.commit()
    insights = build_hippograph_insights(db, seed_skus=["GAM-7"], top_k=8)
    assert any(i["kind"] == "finding" and "demand_shift" in i["id"] for i in insights)


def test_scope_findings_pure_function():
    from src.app.services.market_intelligence_agent import _scope_findings
    fs = [
        MarketFinding("demand_shift", "GAM-1", "critical", 0.9, "a", {}, "daily"),
        MarketFinding("demand_shift", "OTHER", "info", 0.2, "b", {}, "daily"),
    ]
    out = _scope_findings(fs, result_skus=["GAM-1"], taxonomy_nodes=[], ancestor_nodes=[])
    assert [f.entity_ref for f in out] == ["GAM-1"]


def test_scope_findings_does_not_match_brand_token_overlap():
    from src.app.services.market_intelligence_agent import _scope_findings
    fs = [MarketFinding("demand_shift", "Lenovo backpack", "warn", 0.8, "accessory spike", {}, "daily")]

    out = _scope_findings(fs, result_skus=["LAP-LENOVO-1"], taxonomy_nodes=["laptops"], ancestor_nodes=[])

    assert out == []


def test_agent_derives_taxonomy_scope_from_approved_result_sku(db):
    from src.app.services.taxonomy_registry import approve_classification, upsert_classification
    upsert_classification(db, sku="LAP-SCOPED-1", node_handle="el-6-6", source="test",
                          confidence=1.0, tenant_id="tenant-a")
    approve_classification(db, sku="LAP-SCOPED-1", approved_by="reviewer",
                           tenant_id="tenant-a")
    persist_findings(db, [
        MarketFinding("demand_shift", "laptop-family", "warn", 0.8, "laptop demand up",
                      {"subject_type": "taxonomy", "subject_id": "el-6-6",
                       "taxonomy_node": "el-6-6", "source_system": "erp"}, "daily")
    ], tenant_id="tenant-a")
    db.commit()

    ctx = gather_market_context(db, query="are these trending", result_skus=["LAP-SCOPED-1"],
                                tenant_id="tenant-a")

    assert [f["summary"] for f in ctx["market_findings"]] == ["laptop demand up"]


def test_agent_never_reads_another_tenants_findings(db):
    persist_findings(db, [MarketFinding("demand_shift", None, "critical", 1.0,
                                                "tenant b secret", {"scope": "global"}, "daily")],
                     tenant_id="tenant-b")
    db.commit()

    ctx = gather_market_context(db, query="what is trending", tenant_id="tenant-a")

    assert ctx["market_findings"] == []
