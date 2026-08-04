"""Market digest (deck M3 summarization) — the LLM boundary under test.

Invariants: the digest is ALWAYS deterministic in its facts (rollups, top findings, suggested focus);
the LLM (injected) may only rewrite the narrative WORDING; LLM failure/empty output → the deterministic
narrative stands; the digest never mutates anything and is honest when the finding store is empty."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.market_digest import build_digest


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def _seed_findings(db, rows):
    from src.app.services.market_analysis import MarketFinding, persist_findings
    findings = [MarketFinding(t, ent, sev, conf, summ, {}, "recent") for t, ent, sev, conf, summ in rows]
    persist_findings(db, findings, expire_unobserved=False)
    db.commit()


def test_deterministic_digest_rolls_up_and_prioritizes_critical(db):
    _seed_findings(db, [
        ("competitor_undercut", "SKU-1", "warn", 0.4, "Competitor undercut on 'SKU-1': 7% lower."),
        ("demand_shift", "search", "critical", 0.9, "Search demand slowdown."),
        ("objection_cluster", "price", "critical", 0.8, "Recurring objection 'price': raised 8x."),
    ])
    d = build_digest(db, llm_fn=None)
    assert d["mode"] == "deterministic" and d["advisory_only"] is True
    assert d["finding_count"] == 3
    assert d["by_severity"] == {"critical": 2, "warn": 1}
    assert d["by_type"]["competitor_undercut"] == 1
    # top findings are severity-ordered (criticals first), focus follows that order and dedups by type
    assert d["top_findings"][0]["severity"] == "critical"
    assert any("inventory" in f or "objection" in f for f in d["suggested_focus"][:2])
    assert "pricing review" in " ".join(d["suggested_focus"])
    assert "2 critical" in d["narrative"]


def test_llm_rewrites_wording_but_facts_stay_deterministic(db):
    _seed_findings(db, [("demand_shift", "search", "critical", 0.9, "Demand spike.")])
    d = build_digest(db, llm_fn=lambda prompt: "Demand is spiking; secure stock early.")
    assert d["mode"] == "llm_rewrite"
    assert d["narrative"] == "Demand is spiking; secure stock early."
    # the FACTS are still the deterministic rollups — the LLM touched only the narrative string
    assert d["finding_count"] == 1 and d["by_severity"] == {"critical": 1}
    assert d["advisory_only"] is True


def test_llm_failure_or_empty_falls_back_to_deterministic(db):
    _seed_findings(db, [("demand_shift", "search", "warn", 0.5, "Mild shift.")])
    def boom(prompt):
        raise RuntimeError("ollama down")
    d1 = build_digest(db, llm_fn=boom)
    assert d1["mode"] == "deterministic" and d1["narrative"]      # exception swallowed, facts stand
    d2 = build_digest(db, llm_fn=lambda p: "   ")
    assert d2["mode"] == "deterministic" and d2["narrative"]      # empty output → deterministic stands


def test_empty_store_is_honest_and_llm_is_not_called(db):
    # no market_finding table at all — the production empty-store path (load is best-effort → [])
    called = []
    d = build_digest(db, llm_fn=lambda p: called.append(p) or "x")
    assert d["finding_count"] == 0 and d["suggested_focus"] == []
    assert called == []                                            # nothing to summarize → no LLM call
    assert "0 critical" in d["narrative"]


def test_digest_never_mutates_findings(db):
    _seed_findings(db, [("demand_shift", "search", "warn", 0.5, "Shift.")])
    before = db.execute(text("SELECT COUNT(*) FROM market_finding")).scalar()
    build_digest(db, llm_fn=None)
    assert db.execute(text("SELECT COUNT(*) FROM market_finding")).scalar() == before
