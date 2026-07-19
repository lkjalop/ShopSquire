"""S9 (runnable, no browser) — end-to-end proof of the two adaptive-growth pipelines at the service
level. The Playwright gates (tests/e2e/test_adaptive_growth_playwright.py) drive the SAME two flows
through the live UI; this proves the spine deterministically in-process so CI catches a break without a
stack.

Gate-2 pipeline: signal → finding → hippograph recall → decomposition → narration evidence.
Gate-3 pipeline: control/treatment assignment → visible ranking delta → attributed outcome →
                 guardrail breach → AUTOMATIC rollback.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import experiments as ex
from src.app.services import market_signal as ms
from src.app.services.experiment_eval import evaluate_experiment, returns_guardrail
from src.app.services.experiment_ops import canary_assignment, composite_guardrail, escalation_rate_guardrail
from src.app.services.market_analysis import persist_findings, run_analysis
from src.app.services.market_intelligence_agent import gather_market_context
from src.app.services.ranking_nudge import apply_experiment_nudge


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


class _Anom:
    is_anomaly = True
    confidence = 0.9
    severity = "critical"
    z_score = 3.1


def _fake_anomaly_fn(series, domain):
    # deterministic: flag the last point as anomalous (no 1.6s real models in a test)
    return [None] * (len(series) - 1) + [_Anom()]


# ── Gate 2: signal → finding → hippograph → decomposition → narration ─────────
def test_gate2_signal_to_finding_to_recall_to_narration(db):
    # seed a recurring zero-result demand for a single-token entity across enough history
    for day in ("2026-06-20", "2026-06-21", "2026-06-22", "2026-06-23", "2026-06-24"):
        for i in range(4):
            # distinct uid_hash per searcher — detect_inventory_demand_mismatch gates on DISTINCT users
            # (anti-flood), so anonymous zero-result signals never manufacture the catalog-gap finding.
            sig = ms.normalize(signal_type="demand", source="search_events",
                               payload={"event_id": f"{day}-{i}", "query": "sku9monitor",
                                        "result_count": 0, "uid_hash": f"u{i}"},
                               occurred_at=f"{day} 10:0{i}:00", dedup_fields=["event_id"])
            ms.ingest(db, sig)
    db.commit()

    # finding generation (BATCH) → persist
    findings = run_analysis(db, anomaly_fn=_fake_anomaly_fn)
    assert any(f.finding_type == "inventory_demand_mismatch" and f.entity_ref == "sku9monitor" for f in findings)
    assert persist_findings(db, findings) >= 1
    db.commit()

    # consumption (HOT path): query that needs market evidence, naming the entity
    ctx = gather_market_context(db, query="is sku9monitor trending right now", uid_hash="u1",
                                result_skus=["sku9monitor"])
    # decomposition fired
    assert ctx["needs_market_evidence"] is True
    # finding surfaced in the query-scoped findings list
    assert any(f["entity_ref"] == "sku9monitor" for f in ctx["market_findings"])
    # Finding recall is seeded from the authorized result subject, never free-text token overlap.
    insights = gather_market_context(db, query="anything about sku9monitor", uid_hash="u1",
                                     result_skus=["sku9monitor"])
    assert any(i.get("kind") == "finding" for i in insights["hippograph_insights"]), \
        "an exact result-SKU finding must be reachable in recall"
    # narration receives structured + plain-English evidence
    assert ctx["market_evidence"]["findings"]
    assert "sku9monitor" in ctx["narration_note"] or ctx["narration_note"]  # note built


# ── Gate 3: assignment → ranking delta → outcome → guardrail → rollback ───────
def test_gate3_assignment_delta_outcome_guardrail_rollback(db):
    ex.ensure_tables(db)
    from src.app.services import attribution
    attribution.ensure_tables(db)
    db.execute(text("CREATE TABLE orders (id TEXT, status TEXT)"))
    eid = ex.create_experiment(db, name="ranking_canary", target_metric="rpv", status="live")

    # 1) assignment: control vs treatment exist within the canary, deterministically
    variants = {canary_assignment(experiment_id=eid, subject=f"u{i}", canary_fraction=1.0) for i in range(40)}
    assert {"control", "treatment"} <= variants

    # 2) visible ranking delta for a TREATMENT user (and NOT for control)
    rows = [{"sku": "A", "score": 1.0}, {"sku": "B", "score": 0.9}]
    treated = apply_experiment_nudge(rows, recall_ids=["B"], assignment="treatment", live=True, max_boost=0.5)
    assert treated[0]["sku"] == "B" and treated[0].get("_nudge_delta")  # B boosted above A — visible delta
    assert apply_experiment_nudge(rows, recall_ids=["B"], assignment="control", live=True) is rows  # control unchanged

    # 3) attributed outcomes per variant: treatment earns MORE revenue but refunds far more
    for arm, val, refund_every in (("control", 100.0, 5), ("treatment", 150.0, 2)):
        for i in range(8):
            subj = f"{eid}-{arm}-{i}"
            oid = f"O-{subj}"
            # assign BEFORE the conversion so the post-assignment attribution window credits it
            ex.record_assignment(db, experiment_id=eid, subject_hash=subj, variant=arm, assigned_at="2026-06-24")
            db.execute(text("INSERT INTO orders (id, status) VALUES (:o,:s)"),
                       {"o": oid, "s": "refunded" if (i % refund_every == 0) else "paid"})
            db.execute(text("INSERT INTO conversion_event (id, decision_id, order_id, uid_hash, "
                            "attributed_skus_json, value_cents, converted_at) VALUES (:i,:d,:o,:u,'[]',:v,'2026-06-25')"),
                       {"i": f"{subj}-c", "d": f"D{subj}", "o": oid, "u": subj, "v": int(val * 100)})
    db.commit()

    # 4) guardrail breach + 5) AUTOMATIC rollback: revenue is up, but returns guardrail reverts it
    guardrail = composite_guardrail(returns_guardrail, escalation_rate_guardrail)
    out = evaluate_experiment(db, eid, min_samples=2, guardrail_fn=guardrail)
    assert out["uplift_pct"] > 0                                   # treatment "won" on revenue ...
    assert out["decision"] == "revert" and out["reason"] == "guardrail_breach"  # ... but guardrail breached
    assert ex.is_experiment_live(db, eid) is False                # the nudge stops globally — autonomous rollback
