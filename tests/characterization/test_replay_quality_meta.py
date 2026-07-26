"""R8.1 — the expects-products decision that feeds empty-rate. One decision surface, bounded:
only a TOTALLY ungroundable turn (no node AND no requirements) is excused from expecting
products; a node-routed empty still counts (can never mask a routing/retrieval miss)."""
from types import SimpleNamespace

from tests.characterization.shadow_replay import (
    _diagnose_case,
    _expects_products,
    _merge_replay_session,
    _phase_telemetry,
    _prewarm_models,
    _product_expectations,
    _quality_case,
    _summarize_phase_telemetry,
)


def test_replay_prewarm_records_shared_readiness(monkeypatch):
    monkeypatch.setattr(
        "src.app.main._prewarm_router_models",
        lambda app: {"ready": True, "status": "ready", "router_model": "qwen"},
    )

    result = _prewarm_models()

    assert result["ready"] is True
    assert result["router_model"] == "qwen"
    assert result["elapsed_ms"] >= 0


def _core(lane="SEARCH", off_catalog=None, node=None, reqs=None, extras_error=False,
          compare_currency_conflict=None):
    extras = {"decision": {"node_handle": node, "requirements": reqs or {}}}
    if compare_currency_conflict:
        extras["compare_currency_conflict"] = compare_currency_conflict
    if extras_error:
        extras = None  # .get raises AttributeError → best-effort slice returns {}
    return SimpleNamespace(lane=lane, off_catalog=off_catalog, extras=extras)


def test_off_domain_ungroundable_is_not_an_empty_failure():
    # 'recommend a good pizza place near me' → SEARCH, node=None, no requirements → honesty
    assert _expects_products(_core(node=None, reqs={})) is False


def test_node_routed_empty_still_counts():
    # accessory_bag → routed to a REAL node (even an empty one) → the empty is a MISS, counted
    assert _expects_products(_core(node="el-7-8-2-4", reqs={})) is True


def test_requirements_without_node_still_counts():
    # bare workload ('play valorant') resolves floors even when node=None → reroute territory,
    # an empty there is a real failure, never excused
    assert _expects_products(_core(node=None, reqs={"gpu_vram_gb": [[">=", 4.0]]})) is True


def test_refusal_and_non_product_lanes_never_expect():
    assert _expects_products(_core(off_catalog={"class": "vp-2-2-1"}, node="vp-2-2-1")) is False
    assert _expects_products(_core(lane="POLICY_QUESTION", node=None)) is False


def test_cross_currency_named_compare_is_an_honest_clarification_not_empty_failure():
    conflict = {"settlement_currency": "USD", "excluded": [{"sku": "AUD-1"}]}
    assert _expects_products(_core(lane="COMPARE", node="el-6-11-2",
                                  compare_currency_conflict=conflict)) is False


def test_quality_and_diagnose_share_the_decision():
    core = _core(node=None, reqs={})
    assert _quality_case("off_domain", {}, core)["expects_products"] is False
    row = _diagnose_case("off_domain", 0, "pizza place near me", core, {"products": []})
    assert row["empty"] is False and row["node_handle"] is None


def test_battery_expectation_is_stable_when_model_clarifies():
    core = _core(node=None, reqs={})
    assert _quality_case(
        "budget_band:0", {"expects_products": True}, core,
    )["expects_products"] is True


def test_product_expectations_are_keyed_per_turn():
    assert _product_expectations([{
        "id": "followup",
        "turns": [
            {"query": "find laptops", "expects_products": True},
            {"query": "why?", "expects_products": False},
        ],
    }]) == {("followup", 0): True, ("followup", 1): False}


def test_degraded_core_without_extras_defaults_to_counting():
    # missing decision breadcrumbs must FAIL CLOSED for the metric: count the empty
    assert _expects_products(_core(node=None, reqs={}, extras_error=True)) is True


def test_replay_session_preserves_prior_subject_on_explanation_turn():
    prior = {
        "prior_node": "el-6-1",
        "shortlist_skus": ["LAP-1"],
        "accepted_constraints": {"quantity": 25, "exclude_brand": "Apple"},
    }
    core = SimpleNamespace(
        products=[],
        extras={"decision": {"lane": "EXPLAIN"}, "constraints_used": {}},
    )
    assert _merge_replay_session(prior, core) == prior


def test_phase_telemetry_separates_route_plan_and_retrieval_without_fake_narration():
    stages = [
        SimpleNamespace(as_dict=lambda: {"stage": "route+intent", "latency_ms": 5100.0}),
        SimpleNamespace(as_dict=lambda: {"stage": "plan:retrieve+fit_check", "latency_ms": 40.0}),
        SimpleNamespace(as_dict=lambda: {"stage": "bulk", "latency_ms": 2.0}),
    ]
    core = SimpleNamespace(stage_results=stages, extras={"evidence": {"latency_ms": 12.0}})

    row = _phase_telemetry(
        core, case_id="case", turn=0, total_latency_ms=5200.0,
        timed_out=False, fallback_used=False, model_mode="model",
    )

    assert row["route_intent_ms"] == 5100.0
    assert row["plan_ms"] == 40.0
    assert row["retrieval_ms"] == 12.0
    assert row["post_stage_ms"] == 2.0
    assert row["narration_ms"] is None
    assert row["narration_mode"] == "not_enrolled"


def test_phase_telemetry_summary_reports_fallback_latency_and_model_modes():
    summary = _summarize_phase_telemetry([
        {"total_ms": 100.0, "route_intent_ms": 80.0, "plan_ms": 15.0,
         "retrieval_ms": 5.0, "post_stage_ms": 2.0, "timed_out": False,
         "fallback_used": False, "model_mode": "model"},
        {"total_ms": 200.0, "route_intent_ms": 170.0, "plan_ms": 20.0,
         "retrieval_ms": 7.0, "post_stage_ms": 3.0, "timed_out": True,
         "fallback_used": True, "model_mode": "fallback:model_unavailable"},
    ])

    assert summary["p95_ms"]["total_ms"] == 200.0
    assert summary["timeouts"] == 1
    assert summary["fallbacks"] == 1
    assert summary["fallback_p95_ms"] == 200.0
    assert summary["model_modes"] == {"fallback:model_unavailable": 1, "model": 1}
    assert summary["narration"]["measured"] is False


def test_phase_telemetry_reports_narration_only_when_stage_enrolled():
    core = SimpleNamespace(
        stage_results=[],
        extras={"evidence": {}, "narration_telemetry": {"mode": "async", "latency_ms": 42.5}},
    )

    row = _phase_telemetry(
        core, case_id="case", turn=0, total_latency_ms=100.0,
        timed_out=False, fallback_used=False, model_mode="model",
    )
    summary = _summarize_phase_telemetry([row])

    assert row["narration_ms"] == 42.5
    assert row["narration_mode"] == "async"
    assert summary["narration"] == {
        "measured": True, "modes": {"async": 1}, "p95_ms": 42.5,
    }
