"""Roadmap #3 — the unified adaptive-action gate: kill switch + authorization + confidence + audit."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import adaptive_action_gate as gate


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def test_allows_known_action_and_audits(db):
    d = gate.authorize(db, action_type="adjust_ranking", confidence=0.9, subject="u1", target="SKU-1")
    assert d.allowed is True and d.reason == gate.ALLOW
    audit = gate.load_recent_audit(db)
    assert len(audit) == 1 and audit[0]["decision"] == "allow" and audit[0]["action_type"] == "adjust_ranking"


def test_unknown_action_type_denied(db):
    d = gate.authorize(db, action_type="delete_everything", confidence=1.0)
    assert d.allowed is False and d.reason == gate.DENY_NOT_AUTHORIZED


def test_kill_switch_denies_everything(db, monkeypatch):
    monkeypatch.setenv("ADAPTATION_KILL_SWITCH", "1")
    d = gate.authorize(db, action_type="adjust_ranking", confidence=1.0)
    assert d.allowed is False and d.reason == gate.DENY_KILLED


def test_confidence_threshold(db, monkeypatch):
    monkeypatch.setenv("ADAPTIVE_MIN_CONFIDENCE", "0.7")
    assert gate.authorize(db, action_type="adjust_ranking", confidence=0.5).reason == gate.DENY_LOW_CONFIDENCE
    assert gate.authorize(db, action_type="adjust_ranking", confidence=0.8).allowed is True


def test_default_min_confidence_is_off(db, monkeypatch):
    monkeypatch.delenv("ADAPTIVE_MIN_CONFIDENCE", raising=False)
    assert gate.authorize(db, action_type="adjust_ranking", confidence=0.0).allowed is True  # off until calibrated


def test_every_decision_is_audited(db):
    gate.authorize(db, action_type="adjust_ranking", confidence=1.0)        # allow
    gate.authorize(db, action_type="nope", confidence=1.0)                  # deny
    decisions = {(a["action_type"], a["decision"], a["reason"]) for a in gate.load_recent_audit(db)}
    assert ("adjust_ranking", "allow", gate.ALLOW) in decisions
    assert ("nope", "deny", gate.DENY_NOT_AUTHORIZED) in decisions


def test_allow_fails_closed_when_audit_unavailable(db, monkeypatch):
    monkeypatch.setattr(gate, "_write_audit", lambda *a, **k: False)  # can't persist the authz record
    d = gate.authorize(db, action_type="adjust_ranking", confidence=1.0)
    assert d.allowed is False and d.reason == gate.DENY_AUDIT_UNAVAILABLE  # no unaudited action


def test_safe_without_db():
    d = gate.authorize(None, action_type="adjust_ranking", confidence=1.0)
    assert d.allowed is True  # no DB to audit to, but the decision itself stands (write_audit skipped)
