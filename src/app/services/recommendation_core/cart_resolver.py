"""Cart-mutation resolver (V2 Phase 4 — cart milestone step 1).

THE SCREENSHOT CLASS. A compound cart edit — 'remove these two items and cut that one to 20
units' — is answered by legacy with a PRODUCT SEARCH, because natural-language cart intent is parsed
by a stack of FRONTEND regexes (App.tsx handleSend) plus a cart-BLIND backend keyword
classifier (chat.py:_classify_turn_intent, no cart lane). Whether an edit works depends on
which keywords the shopper happened to type ('deterministic suck'). This module is the
grounded replacement: ONE model judgment maps unbounded cart language to a CLOSED operation
vocabulary; deterministic clamps bind every target to a REAL cart line by SKU and every
quantity to sane bounds. The model MAPS; the platform BINDS and DECIDES.

Doctrine (same as turn_router): model-judged CLOSED-vocab → clamp → deterministic-fallback.
  ops vocab (closed) : clear_all | clear_previous | remove_items | set_quantity | keep_only
  target binding     : the model names cart lines in prose ('the 14-inch one'); code resolves
                       each name to a cart SKU by distinctive-token overlap (model numbers /
                       brand tokens outweigh generic 'laptop'). A name that binds to no line
                       — or ties two lines — is UNRESOLVED → surfaced in `ambiguous`, never
                       guessed. 'never guess-then-wipe' is the invariant the frontend
                       keepAfterClear comment documents as a live recording bug.
  quantity clamp     : set_quantity to an int in [0, _MAX_QTY]; 0 collapses to a remove.
  failure mode       : bad JSON / empty cart / no ops → empty plan (source=default); the
                       caller falls through to legacy. Degradation, never invention.

Never executes. This module PLANS. Execution (the cart API) is the caller's job, so a plan
can be diffed in shadow BEFORE it is ever allowed to mutate a real cart.

Model resolution ignores OLLAMA_SMALL/DEFAULT (vision-typed in real deployments — the
VL-chain lesson): ROUTER_MODEL → CLASSIFIER_MODEL → certified text default.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.app.services.catalog_classifier import _plural_expand, _tokens
from src.app.services.recommendation_core.envelope import TurnEnvelope

logger = logging.getLogger("shopsquire.recommendation_core.cart_resolver")

LLMFn = Callable[[str, float], str]

# CLOSED operation vocabulary. Anything the model returns outside this set is dropped.
_ACTIONS = frozenset({"clear_all", "clear_previous", "remove_items", "set_quantity", "keep_only"})
# actions that target specific named lines (vs. whole-cart intents)
_TARGETED = frozenset({"remove_items", "set_quantity", "keep_only"})
_MAX_QTY = 100_000            # a sane ceiling; the stock/authorization gate is the caller's job
# generic device words carry no distinguishing power between two laptop lines — a name that
# overlaps a cart line ONLY on these is not a real match (prevents 'the laptop' binding one of
# three laptops at random). Vertical-light: extend as new vertials are cart-served.
_GENERIC_TOKENS = frozenset({
    "laptop", "laptops", "computer", "computers", "pc", "pcs", "unit", "units", "item", "items",
    "product", "products", "device", "devices", "machine", "one", "ones", "model", "gb", "tb",
})


@dataclass(frozen=True)
class CartOp:
    """One clamped, SKU-bound cart operation. target_skus are REAL cart lines (or empty for
    whole-cart intents). quantity is set only for set_quantity."""
    action: str
    target_skus: Tuple[str, ...] = ()
    quantity: Optional[int] = None

    def as_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"action": self.action, "target_skus": list(self.target_skus)}
        if self.quantity is not None:
            d["quantity"] = self.quantity
        return d


@dataclass(frozen=True)
class CartMutationPlan:
    """The typed result. `ops` are fully bound and safe to execute; `ambiguous` names could not
    be bound to exactly one line — the caller must ASK, never wipe on a guess."""
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


EMPTY_PLAN = CartMutationPlan()


def _resolver_model() -> str:
    return (os.getenv("ROUTER_MODEL") or os.getenv("CLASSIFIER_MODEL") or "qwen3:14b")


def _default_llm_fn(prompt: str, timeout: float) -> str:
    try:
        import httpx
        url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
        model = _resolver_model()
        payload = {"model": model, "prompt": prompt, "stream": False, "format": "json",
                   "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
                   "options": {"temperature": 0, "num_predict": 320}}
        if "qwen3" in model.lower():
            payload["think"] = False
        r = httpx.post(f"{url}/api/generate", json=payload, timeout=max(2.0, float(timeout or 12.0)))
        data = r.json() or {}
        if r.status_code != 200 or data.get("error"):
            logger.warning("cart resolver model call failed: http=%s error=%s model=%s",
                           r.status_code, str(data.get("error"))[:120], model)
            return ""
        return str(data.get("response", "") or "")
    except Exception as exc:
        logger.warning("cart resolver model call failed: %s model=%s", repr(exc)[:120], _resolver_model())
        return ""


def _cart_lines(envelope: TurnEnvelope) -> List[Dict[str, Any]]:
    """Cart lines with a usable SKU + display name. Defensive: the read model may hand us
    partially-hydrated rows."""
    out: List[Dict[str, Any]] = []
    for line in (envelope.cart or []):
        if not isinstance(line, dict):
            continue
        sku = str(line.get("sku") or "").strip()
        if not sku:
            continue
        name = str(line.get("name") or line.get("title") or "").strip()
        try:
            qty = int(line.get("quantity") or line.get("qty") or 1)
        except (TypeError, ValueError):
            qty = 1
        out.append({"sku": sku, "name": name, "quantity": qty})
    return out


def _distinctive(toks: set) -> set:
    """Tokens that actually distinguish one cart line from another: drop generic device words
    and 1-char noise. 'the acme pro x1' → {acme, pro, x1}, not {product}."""
    return {t for t in toks if len(t) > 1 and t not in _GENERIC_TOKENS}


def _bind_name_to_sku(name: str, lines: List[Dict[str, Any]]) -> Optional[str]:
    """Resolve a model-named target to exactly one cart line's SKU by distinctive-token overlap.
    Returns the SKU on a clear single winner; None when nothing matches OR two lines tie (the
    ambiguous case — ASK, never guess). A bare SKU that names a line directly also binds."""
    if not name or not lines:
        return None
    # direct SKU reference (the model may echo a SKU it was shown)
    name_l = name.strip().lower()
    for ln in lines:
        if ln["sku"].lower() == name_l:
            return ln["sku"]
    name_toks = _distinctive(_plural_expand(set(_tokens(name))))
    if not name_toks:
        return None
    scored: List[Tuple[int, str]] = []
    for ln in lines:
        line_toks = _distinctive(_plural_expand(set(_tokens(ln["name"]))))
        overlap = len(name_toks & line_toks)
        if overlap:
            scored.append((overlap, ln["sku"]))
    if not scored:
        return None
    scored.sort(key=lambda t: t[0], reverse=True)
    if len(scored) >= 2 and scored[0][0] == scored[1][0]:
        return None   # tie → ambiguous, do not guess
    return scored[0][1]


def _build_prompt(envelope: TurnEnvelope, lines: List[Dict[str, Any]]) -> str:
    cart_lines = "\n".join(
        f"  [{i}] {ln['name'] or ln['sku']}  (qty {ln['quantity']})" for i, ln in enumerate(lines)
    ) or "  (cart is empty)"
    return (
        "You edit a shopping cart. Translate the shopper's message into cart operations over "
        "the lines below. Refer to a line by its NAME as shown — never invent products not in "
        "the cart.\n\n"
        f'MESSAGE: "{envelope.query[:400]}"\n\n'
        f"CART LINES:\n{cart_lines}\n\n"
        "ACTIONS (use only these):\n"
        "- clear_all: empty the whole cart.\n"
        "- clear_previous: remove only items carried over from an earlier session (keep what "
        "was added now).\n"
        "- remove_items: remove specific named lines (list their names in \"targets\").\n"
        "- set_quantity: change one named line to a number (\"targets\":[name], "
        "\"quantity\":<int>).\n"
        "- keep_only: remove everything EXCEPT the named lines (list keepers in \"targets\").\n\n"
        "Rules:\n"
        "- A message can hold MORE THAN ONE operation ('remove A and B, set C to 20' = a "
        "remove_items op AND a set_quantity op).\n"
        "- Only emit an operation the shopper actually asked for. If they are just asking a "
        "question or searching for products, return an empty ops list.\n"
        "- Put the shopper's own words for each target in \"targets\"; the platform matches "
        "them to real lines.\n\n"
        'Return JSON: {"ops": [{"action": "<action>", "targets": ["<name>", ...], '
        '"quantity": <int or null>}], "confidence": <0.0-1.0>}\nJSON:'
    )


def resolve_cart_mutation(envelope: TurnEnvelope, *, llm_fn: Optional[LLMFn] = None,
                          timeout: float = 12.0) -> CartMutationPlan:
    """One model judgment → clamped, SKU-bound plan. Never raises; every failure path is the
    empty plan (source=default), which tells the caller to fall through to legacy.

    An empty cart still resolves whole-cart intents to nothing actionable (there is nothing to
    clear), so the caller can answer 'your cart is already empty' rather than searching."""
    lines = _cart_lines(envelope)
    if not envelope.query:
        return EMPTY_PLAN

    fn = llm_fn or _default_llm_fn
    try:
        raw = fn(_build_prompt(envelope, lines), timeout)
        data = json.loads(raw) if raw else None
    except Exception:
        data = None
    if not isinstance(data, dict):
        return EMPTY_PLAN

    try:
        conf = max(0.0, min(1.0, float(data.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        conf = 0.0

    ops: List[CartOp] = []
    ambiguous: List[str] = []
    for raw_op in (data.get("ops") or []):
        if not isinstance(raw_op, dict):
            continue
        action = str(raw_op.get("action") or "").strip().lower()
        if action not in _ACTIONS:
            continue

        # whole-cart intents carry no targets to bind
        if action in ("clear_all", "clear_previous"):
            ops.append(CartOp(action=action))
            continue

        # targeted intents: bind each named target to a real line, or record it ambiguous
        raw_targets = raw_op.get("targets") or []
        if isinstance(raw_targets, str):
            raw_targets = [raw_targets]
        bound: List[str] = []
        for t in raw_targets:
            t_str = str(t or "").strip()
            if not t_str:
                continue
            sku = _bind_name_to_sku(t_str, lines)
            if sku is None:
                ambiguous.append(t_str)
            elif sku not in bound:
                bound.append(sku)

        if action == "set_quantity":
            # exactly one bound target + a clamped integer quantity. Guarded (not try/except:
            # continue) so this stays a zero-silent-swallow module: a set_quantity with no
            # numeric quantity is simply not actionable and is skipped.
            qraw = raw_op.get("quantity")
            if isinstance(qraw, bool) or not isinstance(qraw, (int, float)):
                continue
            qty = max(0, min(_MAX_QTY, int(qraw)))
            if len(bound) != 1:
                continue                      # zero or multiple targets → surfaced via `ambiguous`
            if qty == 0:
                ops.append(CartOp(action="remove_items", target_skus=(bound[0],)))
            else:
                ops.append(CartOp(action="set_quantity", target_skus=(bound[0],), quantity=qty))
            continue

        # remove_items / keep_only: apply the bound targets; unbound names already recorded
        if bound:
            ops.append(CartOp(action=action, target_skus=tuple(bound)))

    if not ops and not ambiguous:
        return EMPTY_PLAN
    return CartMutationPlan(ops=tuple(ops), ambiguous=tuple(dict.fromkeys(ambiguous)),
                            confidence=conf, source="model")
