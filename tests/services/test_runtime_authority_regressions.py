"""Cross-boundary regressions found in the September runtime review."""
import threading
import time
from types import SimpleNamespace

import pytest

from src.app.services import local_model_roles as roles
from src.app.services.recommendation_core.router_model_call import execute_router_model
from src.app.services.recommendation_core.trace_ontology import build_execution_steps
from src.app.services.research_policy import active_research_policy, tenant_policy_auto_research_authorized


def call(transport, timeout=1, **kwargs):
    return roles.execute_local_model_role(
        "test", role="recommendation_turn_router", purpose="regression", prompt_id="test",
        model="fixture", digest="0" * 64, timeout_s=timeout, max_output_tokens=8,
        transport=transport, **kwargs,
    )


def test_timeout_keeps_resource_owned_until_transport_finishes(monkeypatch):
    monkeypatch.setenv("LOCAL_MODEL_MAX_CONCURRENCY", "1")
    roles._reset_local_model_scheduler_for_tests()
    release = threading.Event()
    finished = threading.Event()
    second_dispatched = threading.Event()
    entered = threading.Event()
    started = time.perf_counter()
    # This regression targets the running transport lease. Freeze only role
    # preflight accounting so its exact 50ms input reaches the 50ms-minimum
    # gateway. Gateway timeout and occupied-gate waits still use real time.
    monkeypatch.setattr(roles, 'time', SimpleNamespace(
        perf_counter=lambda: time.perf_counter() - started if entered.is_set() else 0.0))

    def slow(*args):
        entered.set()
        try:
            assert release.wait(3)
            return "late"
        finally:
            finished.set()

    try:
        with pytest.raises(roles.LocalModelFailure, match="model_execution_timeout"):
            call(slow, .05)
        assert entered.is_set(), 'the running-transport assertion requires actual dispatch'
        with pytest.raises(roles.LocalModelFailure, match="local_model_queue_timeout"):
            call(lambda *args: second_dispatched.set() or "bad", .05)
        assert not second_dispatched.is_set()
    finally:
        release.set()
        assert finished.wait(2)
    assert call(lambda *args: "recovered") == "recovered"


@pytest.mark.parametrize("code,outcome", [
    ("local_model_queue_timeout", "timeout"),
    ("local_model_deadline_exhausted", "timeout"),
    ("model_artifact_mismatch", "error"),
    ("router_model_http_error", "error"),
])
def test_router_retains_failure_identity(monkeypatch, code, outcome):
    monkeypatch.setenv("ROUTER_MODEL_ENABLED", "1")
    def fail(*args, **kwargs):
        raise roles.LocalModelFailure(code)
    monkeypatch.setattr(roles, "execute_local_model_role", fail)
    _, metrics = execute_router_model(
        "test", 1, model="fixture", http_post=None, injected_transport=True,
        gate=threading.Semaphore(1), runtime_contract={"queue_timeout_s": .1},
    )
    assert (metrics["failure_code"], metrics["outcome"]) == (code, outcome)
    assert "scheduler_role" not in metrics


def test_artifact_failure_does_not_inherit_previous_schedule(monkeypatch):
    call(lambda *args: "ok", execution_id="previous")
    monkeypatch.setattr(roles, "verify_ollama_artifact", lambda **kw: SimpleNamespace(status="mismatch"))
    with pytest.raises(roles.LocalModelFailure):
        roles.execute_local_model_role(
            "test", role="recommendation_turn_router", purpose="test", prompt_id="test",
            model="fixture", digest="a" * 64, timeout_s=1, max_output_tokens=8,
            execution_id="current",
        )
    metrics = roles.last_local_model_schedule_metrics()
    assert metrics["execution_id"] == "current"
    assert metrics["execution_ms"] == 0
    assert metrics["failure_code"] == "model_artifact_mismatch"


@pytest.mark.parametrize("profile", ["buyer-consent-v1", "missing"])
def test_legacy_override_cannot_widen_reported_policy(monkeypatch, profile):
    monkeypatch.setenv("RESEARCH_POLICY_PROFILE", profile)
    monkeypatch.setenv("EXTERNAL_RESEARCH_AUTO_AUTHORIZED", "1")
    policy = active_research_policy()
    assert tenant_policy_auto_research_authorized() == bool(
        policy["external_research_enabled"] and policy["auto_authorize_read_only"]
    ) is False


def test_failed_proposal_cannot_appear_as_accepted_authority():
    steps = build_execution_steps(SimpleNamespace(extras={"decision": {
        "source": "fallback:model_execution_failed", "requirements": {"ram_gb": [[">=", 16]]},
    }}))
    assert steps[0]["status"] == steps[1]["status"] == "degraded"
    assert steps[1]["input_provenance"]["requirements_verified"] is False


@pytest.mark.parametrize("host", ["10.0.0.1", "169.254.169.254", "internal.example"])
def test_private_allowance_does_not_authorize_internal_networks(host):
    from src.app.adapters.external_research_httpx import _host_is_safe
    assert not _host_is_safe(host, allow_private=True,
        resolver=lambda *args: [(2, 1, 6, "", ("10.0.0.1", 0))])


def test_private_allowance_accepts_only_literal_loopback():
    from src.app.adapters.external_research_httpx import _host_is_safe
    assert _host_is_safe("127.0.0.1", allow_private=True, resolver=lambda *args: [])


def test_explicit_consent_uses_buyer_basis_without_automatic_policy(monkeypatch):
    from src.app.services.chat_research_entry import research_entry_authorization
    monkeypatch.setenv("RESEARCH_POLICY_PROFILE", "buyer-consent-v1")
    entry = research_entry_authorization(payload={"external_research_consent": True}, submitted_query="Blender")
    assert entry.authorized and not entry.policy_authorized and entry.basis == "buyer_action"
    denied = research_entry_authorization(payload={"external_research_consent": "false"}, submitted_query="Blender")
    assert not denied.authorized


def test_terminal_does_not_claim_fit_when_committed_products_are_held():
    from src.app.services.chat_terminal_projection import project_chat_terminal
    out = {"shopping_case_revision": 2, "subject_role": "PROCURE_SUBJECT",
           "assistant_message": "Yes, your budget is ample. Strong fits start at $899.",
           "research_outcome": {"case_id":"c1", "case_revision":2, "catalog_authority":"unknown"}}
    products = project_chat_terminal(out=out, server_research_result=None, server_research_failure=None,
        params_case_patch_idempotency_key="k", ambiguity_exploration=None, active_shopping_case_id="c1",
        decision_trace_id="t", data={}, products=[], effective_turn_facts=lambda *a, **kw: {})
    assert not products and out["terminal_outcome"]["recommendation_status"] == "held"
    assert "remain unresolved" in out["assistant_message"]
    assert "ample" not in out["assistant_message"]


@pytest.mark.parametrize("profile", ["buyer-consent-v1", "demo-safe-auto-v1"])
def test_explicit_revocation_wins_over_consent_phrase(monkeypatch, profile):
    from src.app.services.chat_research_entry import research_entry_authorization
    monkeypatch.setenv("RESEARCH_POLICY_PROFILE", profile)
    entry = research_entry_authorization(payload={"external_research_consent": False},
        submitted_query="yes, research official requirements online")
    assert not entry.authorized and entry.basis == "none"


def test_executed_discovery_supersedes_preflight_unknown_reachability():
    from src.app.services.research_outcome import _failure_code
    receipt = {"provider_capability":"WEB_DISCOVERY", "external_call_dispatched":True,
               "execution_status":"completed"}
    rows = [{"error_code":"discovery_reachability_not_observed"}, receipt]
    assert _failure_code(rows) is None
    receipt.update(execution_status="failed", error="discovery_transport_error:JSONDecodeError")
    assert _failure_code(rows) == "discovery_transport_error:JSONDecodeError"
