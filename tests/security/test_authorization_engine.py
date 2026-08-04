"""Unit tests for the Authorization Engine (Tier-1 control).

The pure ``authorize()`` core is tested against an in-test policy so the cases are
deterministic and independent of the shipped config file. The orchestrator
``authorize_action()`` is tested for mode resolution, shadow/active enforcement,
idempotency replay, and fail-closed behaviour (control-plane DB writes disabled
so the tests stay hermetic).
"""
from __future__ import annotations

import pytest

import src.app.security.authorization_engine as ae
from src.app.security.authorization_engine import (
    AuthorizationContext,
    authorize,
    authorize_action,
    DECISION_ALLOW,
    DECISION_DENY,
    DECISION_ESCALATE,
)


def _policy() -> dict:
    return {
        "version": "test-authz-v1",
        "default_mode": "shadow",
        "terminal_outcomes": [
            "execute", "reject_under_policy", "request_customer_evidence",
            "substitute", "quarantine", "safe_pause", "defer_retry", "escalate_governance",
        ],
        "actions": {
            "refund": {
                "allowed_requesters": ["Returns_Refund_Automation", "AI_Customer_Support"],
                "min_confidence": 0.75,
                "value_cap_usd": 500,
                "governance_cap_usd": 2000,
                "prohibited_when": ["already_refunded", "chargeback_open"],
                "default_terminal": "reject_under_policy",
            },
            "fraud_disposition": {
                "allowed_requesters": ["Fraud_Trust_Engine"],
                "min_confidence": 0.6,
                "value_cap_usd": 100000,
                "governance_cap_usd": 100000,
                "prohibited_when": [],
                "default_terminal": "quarantine",
            },
            "bank_change": {  # always BLOCK (legacy authority-matrix BANK-01)
                "hard_block": True,
                "default_terminal": "reject_under_policy",
            },
            "supplier_add": {  # always governance (legacy HUMAN_REVIEW SUP-01)
                "never_auto": True,
                "default_terminal": "escalate_governance",
            },
        },
    }


def _ctx(**kw) -> AuthorizationContext:
    base = dict(action="refund", requester="Returns_Refund_Automation", value_usd=100.0, confidence=0.9)
    base.update(kw)
    return AuthorizationContext(**base)


# ── pure core ──────────────────────────────────────────────────────────────
def test_clean_request_executes():
    d = authorize(_ctx(), _policy())
    assert d.decision == DECISION_ALLOW
    assert d.terminal_outcome == "execute"
    assert d.allowed is True


def test_out_of_lane_is_a_compromise_not_a_plain_denial():
    d = authorize(_ctx(requester="NLP_Search_Agent"), _policy())
    assert d.decision == DECISION_DENY
    assert d.terminal_outcome == "safe_pause"
    assert "out_of_lane" in d.compromise_signals
    assert d.is_compromise is True
    assert d.residual  # tells you how to flip it


def test_injection_signal_trips_safe_pause():
    d = authorize(_ctx(signals=frozenset({"prompt_injection_detected"})), _policy())
    assert d.decision == DECISION_DENY
    assert d.terminal_outcome == "safe_pause"
    assert "prompt_injection_detected" in d.compromise_signals


def test_compromise_on_fraud_disposition_quarantines():
    d = authorize(
        AuthorizationContext(
            action="fraud_disposition", requester="Fraud_Trust_Engine",
            confidence=0.9, signals=frozenset({"memory_manipulation_detected"}),
        ),
        _policy(),
    )
    assert d.decision == DECISION_DENY
    assert d.terminal_outcome == "quarantine"


def test_non_compromise_signal_is_ignored():
    # A signal that isn't in the compromise set must not trip the guardrail.
    d = authorize(_ctx(signals=frozenset({"customer_was_polite"})), _policy())
    assert d.decision == DECISION_ALLOW


def test_prohibited_precondition_rejects_under_policy():
    d = authorize(_ctx(conditions=frozenset({"already_refunded"})), _policy())
    assert d.decision == DECISION_DENY
    assert d.terminal_outcome == "reject_under_policy"
    assert "already_refunded" in d.reason


def test_confidence_below_floor_denies():
    d = authorize(_ctx(confidence=0.5), _policy())
    assert d.decision == DECISION_DENY
    assert d.terminal_outcome == "reject_under_policy"
    assert "confidence_below_floor" in d.reason


def test_value_in_governance_band_escalates():
    d = authorize(_ctx(value_usd=800.0), _policy())
    assert d.decision == DECISION_ESCALATE
    assert d.terminal_outcome == "escalate_governance"


def test_value_over_governance_cap_hard_pauses():
    d = authorize(_ctx(value_usd=2500.0), _policy())
    assert d.decision == DECISION_DENY
    assert d.terminal_outcome == "safe_pause"
    assert "governance_cap" in d.guardrails_tripped


def test_unknown_action_fails_closed():
    d = authorize(_ctx(action="launch_missiles"), _policy())
    assert d.decision == DECISION_DENY
    assert d.terminal_outcome == "safe_pause"
    assert "unknown_action" in d.compromise_signals


def test_compromise_precedes_business_checks():
    # An out-of-lane request that also has a prohibited precondition is reported as
    # compromise (the security signal wins over the polite policy rejection).
    d = authorize(_ctx(requester="rogue", conditions=frozenset({"already_refunded"})), _policy())
    assert "out_of_lane" in d.compromise_signals


def test_hard_block_denies_unconditionally():
    d = authorize(_ctx(action="bank_change", value_usd=0.0), _policy())
    assert d.decision == DECISION_DENY
    assert "hard_block" in d.guardrails_tripped


def test_never_auto_always_escalates_regardless_of_value():
    d = authorize(_ctx(action="supplier_add", value_usd=0.0, confidence=1.0), _policy())
    assert d.decision == DECISION_ESCALATE
    assert d.terminal_outcome == "escalate_governance"
    assert "never_auto" in d.guardrails_tripped


def test_lane_skipped_for_human_seam():
    # enforce_lane=False (human-authenticated seam): an unknown requester must NOT
    # be flagged out_of_lane — there is no agent lane to police here.
    ctx = AuthorizationContext(
        action="refund", requester="route_enforcement", value_usd=10.0,
        confidence=0.9, enforce_lane=False,
    )
    d = authorize(ctx, _policy())
    assert d.decision == DECISION_ALLOW
    assert not d.is_compromise


def test_lane_skipped_when_action_declares_no_lane():
    # bank_change declares no allowed_requesters → no lane to enforce even for agents.
    d = authorize(_ctx(action="bank_change", requester="anyone"), _policy())
    assert "out_of_lane" not in d.compromise_signals  # hard_block, not lane


# ── orchestrator: mode + enforcement ─────────────────────────────────────────
@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    # Deterministic policy + no DB writes for orchestrator tests.
    monkeypatch.setattr(ae, "load_policy", lambda force=False: _policy())
    monkeypatch.setenv("AUTHZ_CONTROL_PLANE_LOG", "0")
    monkeypatch.delenv("AUTHZ_ENGINE_MODE", raising=False)
    ae._IDEMPOTENCY_CACHE.clear()
    yield


def test_shadow_mode_never_blocks(monkeypatch):
    monkeypatch.setenv("AUTHZ_ENGINE_MODE", "shadow")
    d = authorize_action("refund", "rogue_agent", value_usd=100, confidence=0.9)
    assert d.decision == DECISION_DENY        # the verdict is still computed + logged
    assert d.enforced is False
    assert d.should_block() is False          # ...but it does not break the caller


def test_active_mode_blocks_denials(monkeypatch):
    monkeypatch.setenv("AUTHZ_ENGINE_MODE", "active")
    d = authorize_action("refund", "rogue_agent", value_usd=100, confidence=0.9)
    assert d.decision == DECISION_DENY
    assert d.enforced is True
    assert d.should_block() is True


def test_active_mode_allows_clean_request(monkeypatch):
    monkeypatch.setenv("AUTHZ_ENGINE_MODE", "active")
    d = authorize_action("refund", "Returns_Refund_Automation", value_usd=100, confidence=0.9)
    assert d.allowed is True
    assert d.should_block() is False


def test_off_kill_switch_passes_through(monkeypatch):
    monkeypatch.setenv("AUTHZ_ENGINE_MODE", "off")
    d = authorize_action("refund", "rogue_agent", value_usd=999999, confidence=0.0)
    assert d.decision == DECISION_ALLOW
    assert d.reason == "engine_off"
    assert d.should_block() is False


def test_idempotency_replays_prior_verdict(monkeypatch):
    monkeypatch.setenv("AUTHZ_ENGINE_MODE", "active")
    first = authorize_action("refund", "Returns_Refund_Automation", value_usd=100, confidence=0.9, idempotency_key="abc-123")
    assert first.cached is False
    second = authorize_action(
        # Even with a now-denying payload, the same key replays the first verdict.
        "refund", "rogue_agent", value_usd=999999, confidence=0.0, idempotency_key="abc-123",
    )
    assert second.cached is True
    assert second.decision == first.decision == DECISION_ALLOW


def test_fail_closed_on_policy_load_error(monkeypatch):
    def _boom(force=False):
        raise FileNotFoundError("policy missing")
    monkeypatch.setattr(ae, "load_policy", _boom)
    d = authorize_action("refund", "Returns_Refund_Automation", value_usd=100, confidence=0.9)
    assert d.decision == DECISION_DENY
    assert d.terminal_outcome == "safe_pause"
    assert d.enforced is True                 # fail-closed halts even mid-rollout
    assert "policy_load_error" in d.reason


def test_control_plane_writes_are_wired(monkeypatch):
    # An allowed request with an idempotency key writes policy_eval + ai_interaction
    # + retry_tracking (the new writer) and NOT exception_queue.
    calls = []
    monkeypatch.setattr(ae, "_cp_insert", lambda sql, params, stage: calls.append(stage))
    monkeypatch.setenv("AUTHZ_ENGINE_MODE", "active")
    authorize_action("refund", "Returns_Refund_Automation", value_usd=10, confidence=0.9, idempotency_key="rt-1")
    assert "policy_evaluation_log" in calls
    assert "ai_interaction_log" in calls
    assert "retry_tracking" in calls
    assert "exception_queue" not in calls


def test_denied_decision_enqueues_exception(monkeypatch):
    calls = []
    monkeypatch.setattr(ae, "_cp_insert", lambda sql, params, stage: calls.append(stage))
    monkeypatch.setenv("AUTHZ_ENGINE_MODE", "active")
    authorize_action("bank_change", "anyone", value_usd=0, confidence=1.0)  # hard_block
    assert "exception_queue" in calls


def test_control_plane_failure_is_observable_not_silent(monkeypatch):
    # A broken DB sink must be counted, not swallowed silently.
    seen = []
    monkeypatch.setattr(ae, "_authz_log_failure", lambda stage, exc=None: seen.append(stage))

    def _broken(*a, **k):
        raise RuntimeError("db down")
    # force _cp_insert down its real path with a failing db_session import target
    monkeypatch.setattr(ae, "_control_plane_enabled", lambda: True)
    import src.app.models.db as dbmod
    monkeypatch.setattr(dbmod, "db_session", _broken)
    monkeypatch.setenv("AUTHZ_ENGINE_MODE", "active")
    authorize_action("refund", "Returns_Refund_Automation", value_usd=10, confidence=0.9)
    assert seen  # at least one failure stage was recorded


# ── the shipped policy file must be valid + cover all six privileged actions ──
def test_shipped_policy_loads_and_covers_all_actions():
    # Read the real file directly (the autouse fixture monkeypatches load_policy).
    import json
    with open(ae._policy_path(), "r", encoding="utf-8") as fh:
        policy = json.load(fh)
    assert isinstance(policy.get("actions"), dict)
    for action in (
        "refund", "return_approval", "order_modification",
        "reshipment", "supplier_order", "fraud_disposition",
    ):
        assert action in policy["actions"], f"missing policy for {action}"
        spec = policy["actions"][action]
        assert spec.get("allowed_requesters"), f"{action} has no allowed_requesters"
        assert spec.get("default_terminal") in policy["terminal_outcomes"]
