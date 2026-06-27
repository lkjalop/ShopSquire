"""Inventory + bulk-shortfall handoff stage — vertical-blind, non-blocking, side-effects injected.
A bulk shortfall must enqueue a Sales approval + emit the handoff/escalation traces; everything else
(single-unit, in-stock, agent failure) must be a quiet no-op that never breaks the recommend flow."""
from __future__ import annotations

from src.app.services.recommend_inventory_handoff_stage import evaluate_inventory_handoff as ev


class _FakeAgent:
    def evaluate_stock_rule(self, sku, ctx):
        return {"rule_id": "r1", "action": "ok", "escalate": False}


class _BoomAgent:
    def evaluate_stock_rule(self, sku, ctx):  # pragma: no cover - exercised via per-candidate try
        raise RuntimeError("rule engine down")


def _collectors():
    traces, approvals, handoffs = [], [], []

    def trace_fn(**kw):
        traces.append(kw)

    def enqueue_approval_fn(capability, payload, reason=None, created_by=None):
        approvals.append({"capability": capability, "payload": payload, "reason": reason, "created_by": created_by})
        return "appr-123"

    def emit_handoff_fn(**kw):
        handoffs.append(kw)

    return traces, approvals, handoffs, trace_fn, enqueue_approval_fn, emit_handoff_fn


def _run(candidates, requested_qty, agent=None, enqueue=None):
    traces, approvals, handoffs, trace_fn, enq, emit = _collectors()
    if enqueue is not None:
        enq = enqueue
    iss, approval_id = ev(
        candidates, requested_qty=requested_qty, trace_id="t1", uid="u1", query="q", role="buyer",
        redis_client=None, trace_fn=trace_fn, enqueue_approval_fn=enq, emit_handoff_fn=emit,
        inventory_agent_factory=lambda: (agent or _FakeAgent()),
    )
    return iss, approval_id, traces, approvals, handoffs


def test_single_unit_never_triggers_handoff():
    cands = [{"sku": "A", "stock": 0}]  # zero stock, but requested_qty=1 is not a bulk order
    iss, approval_id, traces, approvals, handoffs = _run(cands, requested_qty=1)
    assert iss == [] and approval_id is None
    assert approvals == [] and handoffs == []
    assert [t["event_type"] for t in traces] == ["inventory_check"]  # logged, no escalation


def test_bulk_in_stock_no_handoff():
    cands = [{"sku": "A", "stock": 50}]
    iss, approval_id, traces, approvals, handoffs = _run(cands, requested_qty=10)
    assert iss == [] and approval_id is None and handoffs == []


def test_bulk_shortfall_enqueues_and_emits_handoff_and_escalation():
    cands = [{"sku": "A", "stock": 3}, {"sku": "B", "stock": 100}]
    iss, approval_id, traces, approvals, handoffs = _run(cands, requested_qty=20)
    assert iss == [{"sku": "A", "available": 3, "requested": 20}]  # only the short SKU
    assert approval_id == "appr-123"
    assert len(approvals) == 1 and approvals[0]["reason"] == "insufficient_stock_bulk"
    assert len(handoffs) == 1 and handoffs[0]["from_agent"] == "Inventory_Agent" and handoffs[0]["to_agent"] == "Sales_Agent"
    types = [t["event_type"] for t in traces]
    assert types == ["inventory_check", "handoff_requested", "human_escalation"]
    assert handoffs[0]["context"]["approval_id"] == "appr-123"


def test_approval_enqueue_failure_is_swallowed_but_handoff_still_emitted():
    def boom_enqueue(*a, **k):
        raise RuntimeError("approval store down")
    cands = [{"sku": "A", "stock": 1}]
    iss, approval_id, traces, approvals, handoffs = _run(cands, requested_qty=5, enqueue=boom_enqueue)
    assert iss and approval_id is None          # approval failed → None, but shortfall still tracked
    assert len(handoffs) == 1                    # handoff still emitted with approval_id=None
    assert handoffs[0]["context"]["approval_id"] is None


def test_agent_construction_failure_is_non_blocking():
    iss, approval_id = ev(
        [{"sku": "A", "stock": 1}], requested_qty=5, trace_id="t", uid="u", query="q", role="b",
        redis_client=None, trace_fn=lambda **k: None,
        enqueue_approval_fn=lambda *a, **k: "x", emit_handoff_fn=lambda **k: None,
        inventory_agent_factory=lambda: (_ for _ in ()).throw(RuntimeError("no agent")),
    )
    assert iss == [] and approval_id is None     # total failure → quiet, recommend flow continues
