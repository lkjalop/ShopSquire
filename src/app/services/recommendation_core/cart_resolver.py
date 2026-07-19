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
  ops vocab (closed) : clear_all | clear_previous | remove_items | set_quantity | keep_only |
                       replace_item
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
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.app.domain.cart_mutation import (   # THE shared typed contract (C1) — re-exported
    EMPTY_PLAN,
    CartMutationPlan,
    CartOp,
)
from src.app.services.catalog_classifier import _plural_expand, _tokens
from src.app.services.recommendation_core.envelope import TurnEnvelope

logger = logging.getLogger("shopsquire.recommendation_core.cart_resolver")

LLMFn = Callable[[str, float], str]

# CLOSED operation vocabulary. Anything the model returns outside this set is dropped.
_ACTIONS = frozenset({"clear_all", "clear_previous", "remove_items", "set_quantity", "keep_only",
                      "replace_item"})
# actions that target specific named lines (vs. whole-cart intents)
_TARGETED = frozenset({"remove_items", "set_quantity", "keep_only", "replace_item"})
# BOUNDS (GPT-5.6 review-5 #9): a cart edit is a handful of changes, never a script. The model's
# output is capped BEFORE any op is considered; a runaway/hostile 500-op response is truncated,
# not iterated. Prompt lines are capped so a huge cart cannot balloon the prompt.
_MAX_OPS = 8
_MAX_TARGETS_PER_OP = 12
_MAX_PROMPT_LINES = 40
# Quantity: pure overflow sanity ONLY. cart.py._MAX_LINE_QTY (500) is THE per-line quantity gate
# — one authoritative bound; mirroring it here would be a second copy of a decision surface
# (the duplicated-parser drift class). An over-limit set_quantity passes through and surfaces as
# the handler's own quantity_out_of_range rejection, quoting the shopper's REAL number.
_MAX_QTY_SANITY = 1_000_000

# WHOLE-CART AUTHORIZATION (Track C / GPT-5.6 review-11b): a destructive whole-cart op must be backed
# by the SHOPPER'S OWN WORDS, not just the model's action — an emptied cart from a hallucinated
# clear_all, or a keep_only that silently drops everything else, is unrecoverable. The keep-intent
# check also catches the keep_only-vs-set_quantity misread ('make the Lenovo 15' carries no
# keep-intent word → the model's keep_only is rejected, we ASK, we never wipe the cart).
_CLEAR_INTENT = re.compile(
    r"\b(clear|empty|wipe|reset|remove (everything|all|it all)|delete (everything|all)|"
    r"get rid of (everything|all)|start over|scrap it all)\b", re.IGNORECASE)
_KEEP_INTENT = re.compile(
    r"\b(keep|only|just|except|all but|everything but|nothing but|leave (only|just))\b", re.IGNORECASE)
_REPLACE_INTENT = re.compile(r"\b(replace|swap|switch|substitute|instead of|in place of)\b", re.IGNORECASE)
_AFFORDABLE_QTY_INTENT = re.compile(
    r"\b(max(?:imum)? affordable|fit (?:it|them|the order) (?:in|within|under) (?:the )?budget|"
    r"keep (?:it|the order|the total) (?:in|within|under|at) (?:the )?(?:same )?(?:total )?budget|"
    r"adjust (?:the )?(?:unit )?quantity|how many (?:can|could) (?:i|we) afford)\b",
    re.IGNORECASE,
)

CatalogCandidatesFn = Callable[[str], List[Dict[str, Any]]]


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


def _line_token_index(lines: List[Dict[str, Any]]) -> List[Tuple[str, set]]:
    """(sku, expanded-token-set) per cart line — computed once per resolve."""
    return [(ln["sku"], {t for t in _plural_expand(set(_tokens(ln["name"]))) if len(t) > 1})
            for ln in lines]


def _distinctive_index(index: List[Tuple[str, set]]) -> List[Tuple[str, set]]:
    """Per-cart DOCUMENT-FREQUENCY scoring (GPT-5.6 review-5 #10 — replaces the electronics
    stoplist): a token appearing in MORE THAN ONE line's name cannot uniquely identify a line
    ('laptop' in an all-laptop cart, 'tablets' in a pharmacy cart), while a token unique to one
    line is a real identifier. Vertical-blind with ZERO vocabulary — works unchanged for
    furniture, clothing, medicine, groceries. A single-line cart keeps all its tokens: 'the
    laptop' with one laptop in the cart is unambiguous and binds."""
    if len(index) <= 1:
        return index
    df: Dict[str, int] = {}
    for _, toks in index:
        for t in toks:
            df[t] = df.get(t, 0) + 1
    return [(sku, {t for t in toks if df[t] == 1}) for sku, toks in index]


def _bind_name_to_sku(name: str, lines: List[Dict[str, Any]],
                      distinctive: Optional[List[Tuple[str, set]]] = None) -> Optional[str]:
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
    name_toks = {t for t in _plural_expand(set(_tokens(name))) if len(t) > 1}
    if not name_toks:
        return None
    if distinctive is None:
        distinctive = _distinctive_index(_line_token_index(lines))
    scored: List[Tuple[int, str]] = []
    for sku, line_toks in distinctive:
        overlap = len(name_toks & line_toks)
        if overlap:
            scored.append((overlap, sku))
    if not scored:
        return None
    scored.sort(key=lambda t: t[0], reverse=True)
    if len(scored) >= 2 and scored[0][0] == scored[1][0]:
        return None   # tie → ambiguous, do not guess
    return scored[0][1]


def _default_catalog_candidates(tenant_id: str) -> List[Dict[str, Any]]:
    """Bounded active catalog projection used only when the model proposes a replacement.

    The model supplies language, never identity. This read supplies the finite SKU vocabulary
    against which the replacement is clamped. A production-sized catalog should back the same
    contract with its search index; the resolver does not depend on storage details.
    """
    try:
        from src.app.models.db import db_session
        from src.app.services.catalog_read_model import search_variants

        with db_session() as db:
            variants = search_variants(db, tenant_id=tenant_id, limit=500)
        return [{"sku": v.sku, "name": v.title, "brand": v.brand,
                 "price_cents": v.price_cents, "active": v.active} for v in variants if v.active]
    except Exception as exc:
        logger.warning("replacement catalog read failed: %s", repr(exc)[:120])
        return []


def _bind_catalog_product(name: str, candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Bind a model-named replacement to exactly one active catalog SKU; ties fail closed."""
    ref = str(name or "").strip()
    if not ref:
        return None
    ref_l = ref.lower()
    for item in candidates:
        if str(item.get("sku") or "").lower() == ref_l:
            return item
    ref_tokens = {t for t in _plural_expand(set(_tokens(ref))) if len(t) > 1}
    if not ref_tokens:
        return None
    scored: List[Tuple[int, int, Dict[str, Any]]] = []
    for item in candidates:
        haystack = " ".join((str(item.get("name") or ""), str(item.get("brand") or ""),
                             str(item.get("sku") or "")))
        item_tokens = {t for t in _plural_expand(set(_tokens(haystack))) if len(t) > 1}
        overlap = len(ref_tokens & item_tokens)
        if overlap:
            scored.append((overlap, int(ref_l in haystack.lower()), item))
    if not scored:
        return None
    scored.sort(key=lambda value: (value[0], value[1]), reverse=True)
    if len(scored) > 1 and scored[0][:2] == scored[1][:2]:
        return None
    return scored[0][2]


def _build_prompt(envelope: TurnEnvelope, lines: List[Dict[str, Any]]) -> str:
    shown = lines[:_MAX_PROMPT_LINES]
    cart_lines = "\n".join(
        f"  [{i}] {ln['name'] or ln['sku']}  (qty {ln['quantity']})" for i, ln in enumerate(shown)
    ) or "  (cart is empty)"
    if len(lines) > _MAX_PROMPT_LINES:
        cart_lines += f"\n  … and {len(lines) - _MAX_PROMPT_LINES} more lines (refer to them by name)"
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
        "- replace_item: replace one existing named line with a different product the shopper "
        "named (\"targets\":[old name], \"replacement\":new product name). Set "
        "\"quantity_mode\":\"max_affordable\" only when the shopper asks to adjust quantity "
        "to a stated total budget.\n\n"
        "Rules:\n"
        "- A message can hold MORE THAN ONE operation ('remove A and B, set C to 20' = a "
        "remove_items op AND a set_quantity op).\n"
        "- Only emit an operation the shopper actually asked for. If they are just asking a "
        "question or searching for products, return an empty ops list.\n"
        "- Put the shopper's own words for each target in \"targets\"; the platform matches "
        "them to real lines.\n\n"
        'Return JSON: {"ops": [{"action": "<action>", "targets": ["<name>", ...], '
        '"replacement": "<new product or null>", "quantity": <int or null>, '
        '"quantity_mode": "max_affordable|preserve|null"}], "confidence": <0.0-1.0>}\nJSON:'
    )


def resolve_cart_mutation(envelope: TurnEnvelope, *, llm_fn: Optional[LLMFn] = None,
                          timeout: float = 12.0,
                          catalog_candidates_fn: Optional[CatalogCandidatesFn] = None) -> CartMutationPlan:
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
    except Exception as exc:
        # observable, not invisible (review-5 #9): a parse/model failure means the lane is dark
        # for this turn — the caller falls through, but ops must be able to see how often.
        logger.debug("cart resolver model/parse failure → empty plan: %s", repr(exc)[:100])
        data = None
    if not isinstance(data, dict):
        return EMPTY_PLAN

    try:
        conf = max(0.0, min(1.0, float(data.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        conf = 0.0

    raw_ops = data.get("ops") or []
    if isinstance(raw_ops, list) and len(raw_ops) > _MAX_OPS:
        logger.debug("cart resolver ops capped: %d → %d", len(raw_ops), _MAX_OPS)
        raw_ops = raw_ops[:_MAX_OPS]
    line_index = _line_token_index(lines)
    distinctive = _distinctive_index(line_index)
    distinctive_map = dict(distinctive)
    # The SHOPPER's OWN words (not the model's resolved target) — used to catch an under-specified
    # reference the model resolved by GUESSING a specific line ('add 5 more Lenovo' with two Lenovos).
    q_tokens = {t for t in _plural_expand(set(_tokens(envelope.query))) if len(t) > 1}
    ops: List[CartOp] = []
    ambiguous: List[str] = []
    for raw_op in raw_ops:
        if not isinstance(raw_op, dict):
            continue
        action = str(raw_op.get("action") or "").strip().lower()
        if action not in _ACTIONS:
            continue

        # whole-cart intents carry no targets to bind. Track C: a destructive clear must be backed by
        # the shopper's own clear-intent words — never execute a model-hallucinated empty-the-cart.
        if action in ("clear_all", "clear_previous"):
            if not _CLEAR_INTENT.search(envelope.query or ""):
                ambiguous.append("clear the whole cart")   # surface for confirmation, don't auto-wipe
                continue
            ops.append(CartOp(action=action))
            continue

        # targeted intents: bind each named target to a real line, or record it ambiguous
        raw_targets = raw_op.get("targets") or []
        if isinstance(raw_targets, str):
            raw_targets = [raw_targets]
        bound: List[str] = []
        for t in raw_targets[:_MAX_TARGETS_PER_OP]:
            t_str = str(t or "").strip()
            if not t_str:
                continue
            sku = _bind_name_to_sku(t_str, lines, distinctive)
            # SHOPPER-AMBIGUITY gate: the model can resolve an under-specified reference by GUESSING a
            # specific line ('add 5 more Lenovo' → it picks the FIRST Lenovo). Judge by the SHOPPER'S
            # words, not the model's target: if the query matches MULTIPLE cart lines and does NOT
            # carry a token distinctive to the bound line, we must ASK which product — never guess
            # whose quantity to change. Single-line / uniquely-named references pass through.
            if sku is not None:
                q_matches = {s for s, toks in line_index if q_tokens & toks}
                if len(q_matches) > 1 and not (q_tokens & distinctive_map.get(sku, set())):
                    ambiguous.append(", ".join(ln["name"] for ln in lines if ln["sku"] in q_matches))
                    continue
            if sku is None:
                ambiguous.append(t_str)
            elif sku not in bound:
                bound.append(sku)

        if action == "set_quantity":
            # exactly one bound target + an INTEGER quantity. Guarded (not try/except: continue)
            # so this stays a zero-silent-swallow module. A fractional quantity (2.9) is NOT a
            # cart quantity — dropped, never silently truncated to 2 (review-5 #9). Values above
            # the sanity ceiling are dropped; the real per-line gate (cart.py._MAX_LINE_QTY=500)
            # stays authoritative and rejects with the shopper's true number.
            qraw = raw_op.get("quantity")
            if isinstance(qraw, bool) or not isinstance(qraw, (int, float)):
                continue
            if isinstance(qraw, float) and not qraw.is_integer():
                continue
            qty = int(qraw)
            if qty < 0 or qty > _MAX_QTY_SANITY:
                continue
            if len(bound) != 1:
                continue                      # zero or multiple targets → surfaced via `ambiguous`
            if qty == 0:
                ops.append(CartOp(action="remove_items", target_skus=(bound[0],)))
            else:
                current_qty = int(next((line["quantity"] for line in lines
                                        if line["sku"] == bound[0]), 0))
                ops.append(CartOp(action="set_quantity", target_skus=(bound[0],), quantity=qty,
                                  previous_quantity=current_qty,
                                  allow_sourcing=qty > current_qty))
            continue

        if action == "replace_item":
            if not _REPLACE_INTENT.search(envelope.query or ""):
                ambiguous.append("replace the cart item")
                continue
            if len(bound) != 1:
                continue
            replacement_ref = str(raw_op.get("replacement") or "").strip()
            candidates_fn = catalog_candidates_fn or _default_catalog_candidates
            replacement = _bind_catalog_product(replacement_ref, candidates_fn(envelope.tenant_id))
            if replacement is None:
                ambiguous.append(replacement_ref or "the replacement product")
                continue
            replacement_sku = str(replacement.get("sku") or "")
            if not replacement_sku or replacement_sku == bound[0]:
                ambiguous.append(replacement_ref or "the replacement product")
                continue
            try:
                unit_price = int(replacement.get("price_cents"))
            except (TypeError, ValueError):
                unit_price = 0
            old_line = next((line for line in lines if line["sku"] == bound[0]), None)
            qty = int((old_line or {}).get("quantity") or 1)
            budget_max_cents: Optional[int] = None
            from src.app.services.budget_grammar import classify_budget_scope, parse_budget
            parsed = parse_budget(envelope.query)
            if (parsed and parsed.budget_max is not None
                    and classify_budget_scope(envelope.query) == "total"):
                budget_max_cents = int(parsed.budget_max) * 100
            mode = str(raw_op.get("quantity_mode") or "").strip().lower()
            if mode == "max_affordable" and _AFFORDABLE_QTY_INTENT.search(envelope.query or ""):
                if not budget_max_cents or unit_price <= 0:
                    ambiguous.append("the total budget or replacement price")
                    continue
                qty = budget_max_cents // unit_price
                if qty < 1:
                    ambiguous.append("a replacement affordable within the total budget")
                    continue
            elif budget_max_cents and unit_price > 0 and qty * unit_price > budget_max_cents:
                ambiguous.append("whether to reduce quantity to fit the total budget")
                continue
            ops.append(CartOp(action="replace_item", target_skus=(bound[0],), quantity=qty,
                              replacement_sku=replacement_sku,
                              replacement_name=str(replacement.get("name") or replacement_sku),
                              budget_max_cents=budget_max_cents,
                              unit_price_cents=unit_price or None,
                              previous_quantity=int((old_line or {}).get("quantity") or 1),
                              allow_sourcing=True))
            continue

        # keep_only is destructive (it removes every OTHER line) — require the shopper's keep-intent
        # words (Track C). This also catches the keep_only-vs-set_quantity misread ('make the Lenovo
        # 15' has no keep-intent word → the model's keep_only is rejected → we ASK, never wipe).
        if action == "keep_only" and not _KEEP_INTENT.search(envelope.query or ""):
            ambiguous.append("keep only " + (", ".join(
                ln["name"] for ln in lines if ln["sku"] in set(bound)) or "the named items"))
            continue

        # remove_items / keep_only: apply the bound targets; unbound names already recorded
        if bound:
            ops.append(CartOp(action=action, target_skus=tuple(bound)))

    removed = {sku for op in ops if op.action == "remove_items" for sku in op.target_skus}
    changed = {sku for op in ops if op.action == "set_quantity" for sku in op.target_skus}
    for sku in sorted(removed & changed):
        name = next((line["name"] for line in lines if line["sku"] == sku), sku)
        ambiguous.append(f"conflicting remove and quantity changes for {name}")

    if not ops and not ambiguous:
        return EMPTY_PLAN
    return CartMutationPlan(ops=tuple(ops), ambiguous=tuple(dict.fromkeys(ambiguous)),
                            confidence=conf, source="model")
