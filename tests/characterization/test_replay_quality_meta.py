"""R8.1 — the expects-products decision that feeds empty-rate. One decision surface, bounded:
only a TOTALLY ungroundable turn (no node AND no requirements) is excused from expecting
products; a node-routed empty still counts (can never mask a routing/retrieval miss)."""
from types import SimpleNamespace

from tests.characterization.shadow_replay import _diagnose_case, _expects_products, _quality_case


def _core(lane="SEARCH", off_catalog=None, node=None, reqs=None, extras_error=False):
    extras = {"decision": {"node_handle": node, "requirements": reqs or {}}}
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


def test_quality_and_diagnose_share_the_decision():
    core = _core(node=None, reqs={})
    assert _quality_case("off_domain", {}, core)["expects_products"] is False
    row = _diagnose_case("off_domain", 0, "pizza place near me", core, {"products": []})
    assert row["empty"] is False and row["node_handle"] is None


def test_degraded_core_without_extras_defaults_to_counting():
    # missing decision breadcrumbs must FAIL CLOSED for the metric: count the empty
    assert _expects_products(_core(node=None, reqs={}, extras_error=True)) is True
