"""Inventory evaluation + bulk-shortfall human handoff (agnostic CORE) — extracted verbatim from
recommend.suggest's inline block so the router stays thin and this logic is unit-testable.

For up to 8 candidates it runs the inventory agent's stock rule, annotates available/requested/can_fulfill,
and — for a BULK order (requested_qty > 1) where stock < requested_qty — enqueues a Sales approval and
emits the Inventory→Sales handoff + human-escalation trace events. It is NON-BLOCKING: any failure leaves
the recommendation flow intact (mirrors the original try/except: pass at every level).

Returns ``(insufficient_stock_skus, inv_shortage_approval_id)`` for the caller to thread downstream.
Mutates nothing the caller owns (candidates are read-only here). Vertical-blind: it speaks
sku/stock/requested_qty/approval + opaque agent-role labels — zero product vocabulary. Never raises.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple


def evaluate_inventory_handoff(
    candidates: Optional[List[Dict[str, Any]]],
    *,
    requested_qty: int,
    trace_id: Any,
    uid: Any,
    query: Any,
    role: Any,
    redis_client: Any,
    trace_fn: Callable,
    enqueue_approval_fn: Callable,
    emit_handoff_fn: Callable,
    inventory_agent_factory: Optional[Callable] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Evaluate stock for the top candidates and, on a bulk shortfall, request a human (Sales) handoff.

    All side-effecting collaborators are injected so the stage is testable and vertical-blind:
    ``trace_fn`` = log_trace_event, ``enqueue_approval_fn`` = enqueue_approval,
    ``emit_handoff_fn`` = _emit_agent_handoff. ``inventory_agent_factory`` defaults to the real agent.
    """
    insufficient_stock_skus: List[Dict[str, Any]] = []
    inv_shortage_approval_id: Optional[str] = None
    try:
        if inventory_agent_factory is not None:
            inv = inventory_agent_factory()
        else:
            from src.app.services.inventory_agent import InventoryAgent
            inv = InventoryAgent()
        logging.info("recommend.suggest: running inventory checks for up to 8 candidates")
        inv_evals = []
        for c in (candidates or [])[:8]:
            stock = int(c.get("stock") or 0)
            ctx = {"stock": stock}
            sku_val = c.get("sku") or ""
            try:
                res = inv.evaluate_stock_rule(sku_val, ctx)
                res["available_qty"] = stock
                res["requested_qty"] = requested_qty
                res["can_fulfill"] = stock >= requested_qty
                inv_evals.append({"sku": sku_val, **res})
                # Track insufficient stock for bulk orders
                if requested_qty > 1 and stock < requested_qty:
                    insufficient_stock_skus.append({"sku": sku_val, "available": stock, "requested": requested_qty})
            except Exception:
                inv_evals.append({"sku": sku_val, "rule_id": None, "action": "eval_failed", "escalate": False, "can_fulfill": False})
        if inv_evals:
            try:
                trace_fn(
                    trace_id=trace_id,
                    event_type="inventory_check",
                    source_type="agent",
                    source_id="Inventory_Agent",
                    target_type="system",
                    target_id=None,
                    payload={
                        "evaluations": inv_evals,
                        "requested_qty": requested_qty,
                        "insufficient_stock_count": len(insufficient_stock_skus),
                        "insufficient_stock_skus": insufficient_stock_skus[:5],  # Limit payload size
                    },
                )
            except Exception:
                pass
            # If bulk order cannot be fulfilled, propose a human handoff to Sales
            try:
                if insufficient_stock_skus:
                    try:
                        inv_shortage_approval_id = enqueue_approval_fn(
                            "inventory",
                            {
                                "uid": uid,
                                "query": query,
                                "requested_qty": requested_qty,
                                "insufficient_stock": insufficient_stock_skus[:10],
                            },
                            reason="insufficient_stock_bulk",
                            created_by=role,
                        )
                    except Exception:
                        inv_shortage_approval_id = None
                    emit_handoff_fn(
                        redis_client=redis_client,
                        from_agent="Inventory_Agent",
                        to_agent="Sales_Agent",
                        reason="insufficient_stock_bulk",
                        context={
                            "uid": uid,
                            "query": query,
                            "requested_qty": requested_qty,
                            "approval_id": inv_shortage_approval_id,
                            "insufficient_stock": insufficient_stock_skus[:10],
                        },
                        trace_id=trace_id,
                    )
                    # Emit explicit handoff event for trace consumers/tests
                    try:
                        trace_fn(
                            trace_id=trace_id,
                            event_type="handoff_requested",
                            source_type="agent",
                            source_id="Inventory_Agent",
                            target_type="agent",
                            target_id="Sales_Agent",
                            payload={
                                "reason": "insufficient_stock_bulk",
                                "requested_qty": requested_qty,
                                "insufficient_stock": insufficient_stock_skus[:5],
                                "approval_id": inv_shortage_approval_id,
                                "tags": ["inventory_insufficient_stock", "approval_required"],
                            },
                        )
                    except Exception:
                        pass
                    trace_fn(
                        trace_id=trace_id,
                        event_type="human_escalation",
                        source_type="agent",
                        source_id="Inventory_Agent",
                        target_type="human",
                        target_id="Sales",
                        payload={
                            "reason": "insufficient_stock_bulk",
                            "requested_qty": requested_qty,
                            "insufficient_stock": insufficient_stock_skus[:5],
                            "approval_id": inv_shortage_approval_id,
                            "tags": ["inventory_insufficient_stock", "approval_required"],
                        },
                    )
            except Exception:
                pass
    except Exception:
        # Non-blocking: recommendation flow continues even if inventory evaluation fails
        pass
    return insufficient_stock_skus, inv_shortage_approval_id
