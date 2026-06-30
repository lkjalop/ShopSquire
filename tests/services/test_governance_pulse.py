"""Governance pulse — the read-only Step-11 visibility aggregate over the existing audit trails."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import adaptive_action_gate as gate
from src.app.services import contact_governance as cg
from src.app.services import governance_pulse as gp
from src.app.services import market_analysis as ma
from src.app.services import market_outcome as mo


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def test_empty_pulse_is_all_zeros_not_an_error(db):
    p = gp.governance_pulse(db)
    assert p["signal_decision_state"]["active_findings"] == 0
    assert p["policy_compliance"]["policy_block_rate"] == 0.0
    assert p["experiment_health"]["rollback_count"] == 0
    assert p["operational_pressure"]["critical_findings"] == 0


def test_policy_block_rate_and_reasons(db, monkeypatch):
    # authorize a mix: 2 allowed, 1 denied (unknown action) → block rate 1/3
    gate.authorize(db, action_type="adjust_ranking", confidence=0.9)          # allow
    gate.authorize(db, action_type="adjust_ranking", confidence=0.9)          # allow
    gate.authorize(db, action_type="not_a_real_action", confidence=0.9)       # deny (unauthorized)
    p = gp.governance_pulse(db)
    pc = p["policy_compliance"]
    assert pc["actions_evaluated"] == 3 and pc["actions_blocked"] == 1
    assert pc["policy_block_rate"] == round(1 / 3, 4)
    assert sum(pc["block_reasons"].values()) == 1


def test_ai_confidence_distribution_buckets(db):
    gate.authorize(db, action_type="adjust_ranking", confidence=0.2)   # low
    gate.authorize(db, action_type="adjust_ranking", confidence=0.6)   # medium
    gate.authorize(db, action_type="adjust_ranking", confidence=0.95)  # high
    dist = gp.governance_pulse(db)["signal_decision_state"]["ai_confidence_distribution"]
    assert dist["low"] == 1 and dist["medium"] == 1 and dist["high"] == 1


def test_findings_severity_and_type_counts(db):
    # distinct (type, entity_ref, window) → distinct dedup keys → all three stay active (no supersession).
    findings = [
        ma.MarketFinding("demand_shift", "rA", "critical", 0.9, "spike", {}, "7d"),
        ma.MarketFinding("demand_shift", "rB", "warn", 0.6, "rise", {}, "7d"),
        ma.MarketFinding("objection_cluster", "price", "warn", 0.7, "price", {}, "7d"),
    ]
    ma.persist_findings(db, findings)
    p = gp.governance_pulse(db)
    sd = p["signal_decision_state"]
    assert sd["active_findings"] == 3
    assert sd["findings_by_severity"]["critical"] == 1 and sd["findings_by_severity"]["warn"] == 2
    assert p["operational_pressure"]["critical_findings"] == 1
    assert p["operational_pressure"]["findings_by_type"]["demand_shift"] == 2


def test_rollback_count_from_outcomes(db):
    mo.record_outcome(db, decision_ref="exp1", decision="keep", uplift_pct=3.0, significant=True,
                      n_control=40, n_treatment=40, reverted=False, commit=True)
    mo.record_outcome(db, decision_ref="exp1", decision="revert", uplift_pct=-1.0, significant=True,
                      n_control=40, n_treatment=40, reverted=True, commit=True)
    eh = gp.governance_pulse(db)["experiment_health"]
    assert eh["outcomes_recorded"] == 2 and eh["rollback_count"] == 1
    assert eh["decision_breakdown"].get("keep") == 1 and eh["decision_breakdown"].get("revert") == 1


def test_contact_suppression_by_region(db):
    # consent defaults to REQUIRED (opt-in) → an un-consented contact is suppressed, audited with its region.
    cg.evaluate_contact(db, uid_hash="u1", channel="email", campaign_id="c1", region="EU")
    cg.evaluate_contact(db, uid_hash="u2", channel="email", campaign_id="c1", region="EU")
    pc = gp.governance_pulse(db)["policy_compliance"]
    assert pc["contacts_evaluated"] == 2 and pc["contacts_suppressed"] >= 1
    assert pc["suppression_by_region"].get("EU", 0) >= 1
    assert pc["exception_count"] == pc["actions_blocked"] + pc["contacts_suppressed"]


def test_adaptation_mode_reflects_flags(db, monkeypatch):
    monkeypatch.setenv("ADAPTATION_KILL_SWITCH", "1")
    monkeypatch.setenv("HIPPOGRAPH_FEEDBACK_ENABLED", "shadow")
    mode = gp.governance_pulse(db)["signal_decision_state"]["adaptation_mode"]
    assert mode["kill_switch"] is True and mode["hippograph_mode"] == "shadow"
