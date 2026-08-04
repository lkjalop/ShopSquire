"""S5 contact-frequency governance — consent, frequency windows, region rules, audit trail.

Every campaign/offer must pass this gate before it can message anyone. The gate sends nothing; it
returns ALLOW or SUPPRESS(reason) and audits every decision. Privacy-first: consent is required by
default and the gate fails CLOSED on error.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import contact_governance as cg


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def test_no_consent_suppresses_by_default(db):
    d = cg.evaluate_contact(db, uid_hash="u1", channel="email")
    assert d.allowed is False and d.reason == cg.SUPPRESS_NO_CONSENT


def test_consent_granted_allows_first_contact(db):
    cg.record_consent(db, uid_hash="u1", channel="email", granted=True)
    d = cg.evaluate_contact(db, uid_hash="u1", channel="email", now_iso="2026-06-25 10:00:00")
    assert d.allowed is True and d.reason == cg.ALLOW


def test_frequency_cap_suppresses_second_contact_in_window(db):
    cg.record_consent(db, uid_hash="u1", channel="email", granted=True)
    # one real send accrues frequency
    cg.record_contact(db, uid_hash="u1", channel="email", now_iso="2026-06-25 10:00:00")
    d = cg.evaluate_contact(db, uid_hash="u1", channel="email", per_window=1, window_seconds=86400,
                            now_iso="2026-06-25 12:00:00")
    assert d.allowed is False and d.reason == cg.SUPPRESS_FREQUENCY and d.detail["count"] == 1
    # outside the window it's allowed again
    d2 = cg.evaluate_contact(db, uid_hash="u1", channel="email", per_window=1, window_seconds=3600,
                             now_iso="2026-06-26 10:00:00")
    assert d2.allowed is True


def test_per_campaign_cap_suppresses_repeat(db):
    cg.record_consent(db, uid_hash="u1", channel="email", granted=True)
    cg.record_contact(db, uid_hash="u1", channel="email", campaign_id="spring", now_iso="2026-06-25 10:00:00")
    d = cg.evaluate_contact(db, uid_hash="u1", channel="email", campaign_id="spring",
                            per_window=100, now_iso="2026-06-25 10:05:00")  # high freq cap, still campaign-capped
    assert d.allowed is False and d.reason == cg.SUPPRESS_CAMPAIGN_CAP


def test_region_blocked_channel(db):
    rules = {"EU": {"requires_consent": False, "blocked_channels": ["sms"], "quiet_hours": []}}
    d = cg.evaluate_contact(db, uid_hash="u1", channel="sms", region="EU", region_rules=rules)
    assert d.allowed is False and d.reason == cg.SUPPRESS_REGION_BLOCKED


def test_quiet_hours_suppress(db):
    rules = {"default": {"requires_consent": False, "blocked_channels": [], "quiet_hours": [3]}}
    d = cg.evaluate_contact(db, uid_hash="u1", channel="email", region_rules=rules,
                            now_iso="2026-06-25 03:30:00")
    assert d.allowed is False and d.reason == cg.SUPPRESS_QUIET_HOURS and d.detail["hour"] == 3


def test_every_decision_is_audited(db):
    cg.evaluate_contact(db, uid_hash="u1", channel="email")                       # suppress (no consent)
    cg.record_consent(db, uid_hash="u2", channel="email", granted=True)
    cg.evaluate_contact(db, uid_hash="u2", channel="email", now_iso="2026-06-25 10:00:00")  # allow
    audit = cg.load_recent_audit(db)
    decisions = {(a["uid_hash"], a["decision"], a["reason"]) for a in audit}
    assert ("u1", "suppress", cg.SUPPRESS_NO_CONSENT) in decisions
    assert ("u2", "allow", cg.ALLOW) in decisions


def test_fails_closed_without_db():
    # an autonomous messenger with no store to check must NOT send — consent can't be proven
    d = cg.evaluate_contact(None, uid_hash="u1", channel="email")
    assert d.allowed is False and d.reason == cg.SUPPRESS_NO_CONSENT


def test_tenant_isolation_of_consent(db):
    cg.record_consent(db, uid_hash="u1", channel="email", granted=True, tenant_id="t-a")
    a = cg.evaluate_contact(db, uid_hash="u1", channel="email", tenant_id="t-a", now_iso="2026-06-25 10:00:00")
    b = cg.evaluate_contact(db, uid_hash="u1", channel="email", tenant_id="t-b", now_iso="2026-06-25 10:00:00")
    assert a.allowed is True and b.allowed is False  # consent in t-a doesn't leak to t-b


# ── fail-closed hardening (Finding 7) ────────────────────────────────────────
def test_unreadable_history_fails_closed(db, monkeypatch):
    cg.record_consent(db, uid_hash="u1", channel="email", granted=True)
    # frequency history can't be read → must NOT permit blindly (was: returned 0 → allowed)
    def _boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(cg, "_count_in_window", _boom)
    d = cg.evaluate_contact(db, uid_hash="u1", channel="email", now_iso="2026-06-25 10:00:00")
    assert d.allowed is False and d.reason == cg.SUPPRESS_ERROR_FAIL_CLOSED


def test_allow_suppressed_when_audit_cannot_persist(db, monkeypatch):
    cg.record_consent(db, uid_hash="u1", channel="email", granted=True)
    monkeypatch.setattr(cg, "_write_audit", lambda *a, **k: False)  # authz record can't be persisted
    d = cg.evaluate_contact(db, uid_hash="u1", channel="email", now_iso="2026-06-25 10:00:00")
    assert d.allowed is False and d.reason == cg.SUPPRESS_AUDIT_UNAVAILABLE  # no record → no send
