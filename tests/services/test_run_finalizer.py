"""recommend_response_finalizer.run_finalizer — extracted route wrapper (D1 step 4).

It runs the canonical finalizer, demotes off-category items, writes results+products into payload,
and returns (results, finalizer_ran). On finalizer failure it returns (results, False) so the late
fallback pass still annotates.
"""
from __future__ import annotations

from types import SimpleNamespace

from src.app.services.recommend_response_finalizer import run_finalizer


def _fin_result(results, oos_removed=None, contract_valid=True, violations=None):
    return SimpleNamespace(results=results, oos_removed=oos_removed or [],
                           contract_valid=contract_valid, contract_violations=violations or [])


def test_finalizer_writes_payload_and_returns_ran():
    payload = {}
    final = [{"sku": "A"}, {"sku": "B"}]
    out, ran = run_finalizer(
        results=[{"sku": "A"}], constraints={}, uid="u", kv={}, query="laptop", payload=payload,
        demote_off_category=lambda r, q: final,  # stand-in demoter returns the final list
        finalize_fn=lambda **k: _fin_result([{"sku": "A"}]),
    )
    assert ran is True
    assert out == final and payload["results"] == final and payload["products"] == final


def test_oos_removed_and_contract_violations_surface():
    payload = {}
    run_finalizer(
        results=[{"sku": "A"}], constraints={}, uid="u", kv={}, query="q", payload=payload,
        demote_off_category=lambda r, q: r,
        finalize_fn=lambda **k: _fin_result([{"sku": "A"}], oos_removed=["X", "Y"],
                                            contract_valid=False, violations=["v1", "v2"]),
    )
    assert payload["oos_removed_count"] == 2
    assert payload["_contract_violations"] == ["v1", "v2"]


def test_stock_filter_preference_passed_through():
    seen = {}
    def _fake(**k):
        seen.update(k)
        return _fin_result(k["results"])
    run_finalizer(
        results=[{"sku": "A"}], constraints={}, uid="u",
        kv={"stock_filter_preference": "in_stock_only"}, query="q", payload={},
        demote_off_category=lambda r, q: r, finalize_fn=_fake,
    )
    assert seen["stock_filter_opted"] is True


def test_finalizer_failure_returns_ran_false_and_keeps_results():
    payload = {}
    original = [{"sku": "A"}]
    def _boom(**k):
        raise RuntimeError("finalizer down")
    out, ran = run_finalizer(
        results=original, constraints={}, uid="u", kv={}, query="q", payload=payload,
        demote_off_category=lambda r, q: r, finalize_fn=_boom,
    )
    assert ran is False and out == original  # pre-finalized results preserved for the fallback pass


def test_default_demoter_used_when_not_injected():
    # No demote_off_category injected -> module-local default is used (no crash).
    payload = {}
    out, ran = run_finalizer(
        results=[{"sku": "A"}, {"sku": "B"}], constraints={}, uid="u", kv={}, query="q",
        payload=payload, finalize_fn=lambda **k: _fin_result(k["results"]),
    )
    assert ran is True and isinstance(out, list)
