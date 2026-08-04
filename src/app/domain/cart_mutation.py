"""Cart-mutation domain contract (V2 cart milestone C1 — GPT-5.6 review-5).

THE shared typed boundary between the resolver (model → plan), the persistence layer
(proposed plans), and the transactional executor. Review-5 #3/#5's core demand — "model
proposes, policy authorizes, human confirms when risky, transactional service executes" —
needs one contract every party imports; duck-typed dicts crossing a cart-mutation boundary
are how fields silently drift.

Three things live here, and ONLY here:
  • CartOp / CartMutationPlan     — the typed plan (moved from cart_resolver, which re-exports).
  • risk_tier()                   — the authorization policy: which plans may auto-execute and
                                    which require an explicit confirmation.
  • cart_content_hash()           — the optimistic-concurrency token: a plan proposed against
                                    one cart state must never apply to another (compare-and-
                                    swap by content, no draft_orders schema change needed).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# CLOSED operation vocabulary — the resolver clamps model output to this set.
ACTIONS = frozenset({"clear_all", "clear_previous", "remove_items", "set_quantity", "keep_only",
                     "replace_item"})


@dataclass(frozen=True)
class CartOp:
    """One clamped, SKU-bound cart operation. target_skus are REAL cart lines (or empty for
    whole-cart intents). A replacement names one existing target SKU plus one catalog-clamped
    replacement SKU. quantity is the resulting replacement-line quantity."""
    action: str
    target_skus: Tuple[str, ...] = ()
    quantity: Optional[int] = None
    replacement_sku: Optional[str] = None
    replacement_name: Optional[str] = None
    budget_max_cents: Optional[int] = None
    unit_price_cents: Optional[int] = None
    previous_quantity: Optional[int] = None
    allow_sourcing: bool = False

    def as_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"action": self.action, "target_skus": list(self.target_skus)}
        if self.quantity is not None:
            d["quantity"] = self.quantity
        if self.replacement_sku is not None:
            d["replacement_sku"] = self.replacement_sku
        if self.replacement_name is not None:
            d["replacement_name"] = self.replacement_name
        if self.budget_max_cents is not None:
            d["budget_max_cents"] = self.budget_max_cents
        if self.unit_price_cents is not None:
            d["unit_price_cents"] = self.unit_price_cents
        if self.previous_quantity is not None:
            d["previous_quantity"] = self.previous_quantity
        if self.allow_sourcing:
            d["allow_sourcing"] = True
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CartOp":
        return cls(action=str(d.get("action") or ""),
                   target_skus=tuple(str(s) for s in (d.get("target_skus") or [])),
                   quantity=(int(d["quantity"]) if d.get("quantity") is not None else None),
                   replacement_sku=(str(d["replacement_sku"])
                                    if d.get("replacement_sku") is not None else None),
                   replacement_name=(str(d["replacement_name"])
                                     if d.get("replacement_name") is not None else None),
                   budget_max_cents=(int(d["budget_max_cents"])
                                     if d.get("budget_max_cents") is not None else None),
                   unit_price_cents=(int(d["unit_price_cents"])
                                     if d.get("unit_price_cents") is not None else None),
                   previous_quantity=(int(d["previous_quantity"])
                                      if d.get("previous_quantity") is not None else None),
                   allow_sourcing=bool(d.get("allow_sourcing", False)))


@dataclass(frozen=True)
class CartMutationPlan:
    """The typed result. `ops` are fully bound and safe to consider; `ambiguous` names could not
    be bound to exactly one line — ANY ambiguity suspends the whole plan (ASK, never wipe)."""
    ops: Tuple[CartOp, ...] = ()
    ambiguous: Tuple[str, ...] = ()      # model-named targets code could not bind 1:1
    confidence: float = 0.0
    source: str = "default"              # model | default

    @property
    def is_empty(self) -> bool:
        return not self.ops and not self.ambiguous

    @property
    def needs_clarification(self) -> bool:
        return bool(self.ambiguous)

    def as_dict(self) -> Dict[str, Any]:
        return {"ops": [o.as_dict() for o in self.ops], "ambiguous": list(self.ambiguous),
                "confidence": round(self.confidence, 3), "source": self.source}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CartMutationPlan":
        return cls(ops=tuple(CartOp.from_dict(o) for o in (d.get("ops") or [])),
                   ambiguous=tuple(str(a) for a in (d.get("ambiguous") or [])),
                   confidence=float(d.get("confidence") or 0.0),
                   source=str(d.get("source") or "default"))


EMPTY_PLAN = CartMutationPlan()

# ── Authorization policy (review-5 #1): the PLATFORM decides what may auto-execute ──
RISK_AUTO = "auto"          # single-target, reversible, in-stock — execute + undo stash
RISK_CONFIRM = "confirm"    # destructive scope or compound — a human confirms the plan first
_AUTO_ACTIONS = frozenset({"remove_items", "set_quantity"})


def risk_tier(plan: CartMutationPlan) -> str:
    """auto ⇔ EXACTLY one op, EXACTLY one target, and a reversible per-line action.
    Everything else — whole-cart scope (clear_all/clear_previous/keep_only), compound plans,
    multi-target removes — requires explicit confirmation. The model's opinion (confidence)
    never lowers the tier; policy is deterministic over the plan's SHAPE."""
    if len(plan.ops) != 1:
        return RISK_CONFIRM
    op = plan.ops[0]
    if op.action not in _AUTO_ACTIONS:
        return RISK_CONFIRM
    if op.allow_sourcing:
        return RISK_CONFIRM
    if len(op.target_skus) != 1:
        return RISK_CONFIRM
    return RISK_AUTO


def cart_content_hash(items: List[Dict[str, Any]]) -> str:
    """Content-addressed cart version: sha256 over the sorted (sku, quantity) pairs. A plan
    carries the hash of the cart it was proposed against; apply re-hashes and refuses on
    mismatch (the cart changed underneath — stepper, another tab, another plan)."""
    pairs = sorted((str(it.get("sku") or ""), int(it.get("quantity") or 0))
                   for it in (items or []) if isinstance(it, dict) and it.get("sku"))
    return hashlib.sha256(json.dumps(pairs, separators=(",", ":")).encode("utf-8")).hexdigest()
