"""S8 offers/campaigns — LAST, double-locked behind a readiness gate that proves rollback + contact-freq.

The defining property: a campaign cannot dispatch until (a) an experiment has actually auto-reverted
AND the eval loop is alive, and (b) the contact-governance gate has really suppressed a contact. Past
the gate, every recipient still passes the per-user consent/frequency check.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import campaign_governance as cgov
from src.app.services import contact_governance as cg
from src.app.services import experiment_ops as ops
from src.app.services import experiments as ex


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    ex.ensure_tables(s)
    from src.app.services import attribution
    attribution.ensure_tables(s)
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def offers_on(monkeypatch):
    monkeypatch.setenv("OFFERS_CAMPAIGNS_ENABLED", "1")  # the outer flag-lock (off by default)


def _prove_rollback(db, now_iso):
    """A REAL data-driven revert: a losing experiment EVALUATED → experiment_result decision='revert'.
    (A forced_rollback_drill sets status but writes no result, so it would NOT satisfy readiness.)"""
    from sqlalchemy import text

    from src.app.services.experiment_eval import evaluate_experiment
    eid = ex.create_experiment(db, name="loser", target_metric="rpv", status="live")
    for arm, val in (("control", 130.0), ("treatment", 100.0)):  # treatment significantly worse
        for i in range(8):
            subj = f"{eid}-{arm}-{i}"
            ex.record_assignment(db, experiment_id=eid, subject_hash=subj, variant=arm, assigned_at="2026-06-24")
            db.execute(text("INSERT INTO conversion_event (id,decision_id,order_id,uid_hash,"
                            "attributed_skus_json,value_cents,converted_at) VALUES (:id,'d',:o,:u,'[]',:v,'2026-06-25')"),
                       {"id": f"{subj}-c", "o": f"order-{subj}",
                        "u": subj, "v": int(val * 100)})
    db.commit()
    out = evaluate_experiment(db, eid, min_samples=2)
    assert out["decision"] == "revert"  # the evaluator recorded a data-driven revert
    ops.record_heartbeat(db, now_iso=now_iso)
    return eid


def _prove_contact_freq(db):
    """A REAL frequency_cap suppression (not just a no-consent block)."""
    cg.record_consent(db, uid_hash="probe", channel="email", granted=True)
    cg.record_contact(db, uid_hash="probe", channel="email", now_iso="2026-06-25 10:00:00")
    d = cg.evaluate_contact(db, uid_hash="probe", channel="email", per_window=1, now_iso="2026-06-25 11:00:00")
    assert d.reason == cg.SUPPRESS_FREQUENCY


# ── readiness gate ────────────────────────────────────────────────────────────
def test_not_ready_before_anything_demonstrated(db):
    r = cgov.adaptation_readiness(db, now_iso="2026-06-25 12:00:00")
    assert r["ready"] is False
    assert "no_data_driven_rollback" in r["reasons"]
    assert "frequency_governance_not_exercised" in r["reasons"]


def test_manual_drill_alone_does_not_prove_rollback(db):
    # a forced drill flips status but writes NO experiment_result → not a data-driven rollback
    eid = ex.create_experiment(db, name="drill", target_metric="rpv", status="live")
    ops.forced_rollback_drill(db, experiment_id=eid)
    ops.record_heartbeat(db, now_iso="2026-06-25 12:00:00")
    _prove_contact_freq(db)
    r = cgov.adaptation_readiness(db, now_iso="2026-06-25 12:05:00")
    assert r["rollback_proven"] is False and r["ready"] is False  # drill ≠ proof


def test_noconsent_suppression_does_not_prove_frequency_governance(db):
    _prove_rollback(db, now_iso="2026-06-25 12:00:00")
    cg.evaluate_contact(db, uid_hash="x", channel="email")  # a no-consent suppression only
    r = cgov.adaptation_readiness(db, now_iso="2026-06-25 12:05:00")
    assert r["contact_freq_proven"] is False  # frequency gate never actually fired


def test_ready_only_after_rollback_and_contact_freq_proven(db):
    _prove_rollback(db, now_iso="2026-06-25 12:00:00")
    # rollback alone is not enough — contact-freq must also be proven
    r1 = cgov.adaptation_readiness(db, now_iso="2026-06-25 12:10:00")
    assert r1["rollback_proven"] is True and r1["contact_freq_proven"] is False and r1["ready"] is False
    _prove_contact_freq(db)
    r2 = cgov.adaptation_readiness(db, now_iso="2026-06-25 12:11:00")
    assert r2["ready"] is True


def test_rollback_not_proven_if_eval_loop_stale(db):
    _prove_rollback(db, now_iso="2026-06-25 08:00:00")  # heartbeat 4h before the check
    _prove_contact_freq(db)
    r = cgov.adaptation_readiness(db, eval_max_stale_seconds=3600, now_iso="2026-06-25 12:00:00")
    assert r["rollback_proven"] is False and "eval_loop_stale" in r["reasons"] and r["ready"] is False


# ── governed dispatch ─────────────────────────────────────────────────────────
def test_dispatch_blocked_by_flag_when_offers_disabled(db):
    # OFFERS_CAMPAIGNS_ENABLED is OFF by default → the outer lock blocks even a ready system
    out = cgov.dispatch_campaign(db, recipients=["u1"], channel="email", campaign_id="c1",
                                 now_iso="2026-06-25 12:00:00")
    assert out["blocked_by_flag"] is True and out["allowed"] == []


def test_dispatch_blocked_until_ready(db, offers_on):
    cg.record_consent(db, uid_hash="u1", channel="email", granted=True)
    out = cgov.dispatch_campaign(db, recipients=["u1"], channel="email", campaign_id="c1",
                                 now_iso="2026-06-25 12:00:00")
    assert out["blocked_by_flag"] is False
    assert out["blocked_by_readiness"] is True and out["allowed"] == []  # flag on, but not proven yet


def test_dispatch_honors_contact_governance_once_ready(db, offers_on):
    _prove_rollback(db, now_iso="2026-06-25 12:00:00")
    _prove_contact_freq(db)
    cg.record_consent(db, uid_hash="yes", channel="email", granted=True)
    # "no" has no consent → suppressed even though the campaign is allowed to run
    out = cgov.dispatch_campaign(db, recipients=["yes", "no"], channel="email", campaign_id="c1",
                                 now_iso="2026-06-25 12:30:00")
    assert out["blocked_by_readiness"] is False
    assert out["allowed"] == ["yes"]
    assert any(s["uid"] == "no" and s["reason"] == cg.SUPPRESS_NO_CONSENT for s in out["suppressed"])


def test_dispatch_safe_without_db(offers_on):
    out = cgov.dispatch_campaign(None, recipients=["u1"], channel="email", campaign_id="c1")
    assert out["blocked_by_readiness"] is True


# ── typed offer proposals (log-only) ─────────────────────────────────────────
def test_offer_proposals_are_typed_and_proposed():
    from src.app.services.market_analysis import MarketFinding
    offers = cgov.propose_offers_from_findings([
        MarketFinding("demand_shift", "SKU-1", "warn", 0.7, "demand up", {}, "daily"),
        MarketFinding("conversion_anomaly", "SKU-2", "warn", 0.6, "conv down", {}, "daily"),
    ])
    kinds = {o.offer_type for o in offers}
    assert kinds == {"promo", "winback"} and all(o.status == "proposed" for o in offers)
