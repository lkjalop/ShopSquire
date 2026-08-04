"""Reconciliation-seam tests for route_enforcement.enforce_action_authority.

Proves (a) the legacy matrix stays authoritative by default so wired routers are
unchanged, (b) the engine runs in shadow and parity is recorded, and (c) the
AUTHZ_ENGINE_AUTHORITATIVE cutover flag flips the engine to driving the verdict.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.app.policy.action_authority_matrix import AuthDecision
from src.app.policy.route_enforcement import enforce_action_authority


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    monkeypatch.setenv("AUTHZ_CONTROL_PLANE_LOG", "0")          # no DB writes in seam tests
    monkeypatch.delenv("AUTHZ_ENGINE_AUTHORITATIVE", raising=False)
    monkeypatch.delenv("AUTHZ_ENGINE_MODE", raising=False)
    yield


# ── matrix authoritative (default) — behaviour preserved ─────────────────────
def test_small_refund_allowed_by_matrix():
    v = enforce_action_authority("refund", value_aud_cents=4_000)  # $40 ≤ $50
    assert v.decision == AuthDecision.ALLOW


def test_mid_refund_raises_409():
    with pytest.raises(HTTPException) as ei:
        enforce_action_authority("refund", value_aud_cents=30_000)  # $300 → DUAL_CONTROL
    assert ei.value.status_code == 409


def test_high_refund_raises_409():
    with pytest.raises(HTTPException) as ei:
        enforce_action_authority("refund", value_aud_cents=60_000)  # $600 → HUMAN_REVIEW
    assert ei.value.status_code == 409


def test_bank_change_blocked_403():
    with pytest.raises(HTTPException) as ei:
        enforce_action_authority("bank_change", context={"beneficiary_changed": True})
    assert ei.value.status_code == 403


def test_pii_export_blocked_403():
    with pytest.raises(HTTPException) as ei:
        enforce_action_authority("pii_export", context={"uid": "u1"})
    assert ei.value.status_code == 403


# ── engine shadow runs + parity recorded ─────────────────────────────────────
def test_engine_shadow_runs_and_agrees(monkeypatch):
    seen = []
    import src.app.policy.route_enforcement as re_mod
    monkeypatch.setattr(re_mod, "_record_parity", lambda action, mv, d: seen.append((action, mv.decision, d.allowed)))
    enforce_action_authority("refund", value_aud_cents=4_000)
    assert seen and seen[0][0] == "refund"
    # matrix ALLOW and engine allowed → agreement
    assert (seen[0][1] == AuthDecision.ALLOW) == bool(seen[0][2])


# ── cutover: engine becomes authoritative ────────────────────────────────────
def test_cutover_engine_drives_block(monkeypatch):
    monkeypatch.setenv("AUTHZ_ENGINE_AUTHORITATIVE", "1")
    with pytest.raises(HTTPException) as ei:
        enforce_action_authority("bank_change", context={"beneficiary_changed": True})
    assert ei.value.status_code == 403
    assert ei.value.detail.get("authority") == "engine"
    assert ei.value.detail.get("rule_id") == "ENGINE"


def test_cutover_engine_allows_small_refund(monkeypatch):
    monkeypatch.setenv("AUTHZ_ENGINE_AUTHORITATIVE", "1")
    v = enforce_action_authority("refund", value_aud_cents=4_000)  # $40 ≤ engine $50 cap
    assert v.decision == AuthDecision.ALLOW
    assert v.rule_id == "ENGINE"


def test_engine_failure_falls_back_to_matrix(monkeypatch):
    # If the engine shadow blows up, the matrix must still drive (no crash).
    import src.app.policy.route_enforcement as re_mod
    monkeypatch.setattr(re_mod, "_run_engine_shadow", lambda *a, **k: None)
    monkeypatch.setenv("AUTHZ_ENGINE_AUTHORITATIVE", "1")  # even asking for engine
    v = enforce_action_authority("refund", value_aud_cents=4_000)
    assert v.decision == AuthDecision.ALLOW  # matrix fallback still works
