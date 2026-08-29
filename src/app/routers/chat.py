from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
import base64
import hashlib
import os
from threading import RLock
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.deps import get_redis
from src.app.models.db import get_db
from src.app.services.memory import Memory
from src.app.services.llm_provider import select_ollama_model, ollama_generate, is_complex_query, score_query_complexity
from src.app.services.search_events import log_search_event
from src.app.services.image_intent_router import classify_image_intent
from src.app.services.decision_log import log_trace_event
from src.app.services.copywriting import maybe_apply_copywriting
from src.app.services.answer_quality import apply_answer_quality
from src.app.services.response_normalizer import ResponseNormalizer
from src.app.services.price_conversion import cents_to_dollars, dollars_to_cents
from src.app.security.dread_scorer import compute_dread
from src.app.security.framework_correlation import correlate_security_analysis
from src.app.security.qr_legitimacy import derive_qr_legitimacy_details
from src.app.services.recommendation_core.envelope import LANES as RECOMMENDATION_LANES

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

_CHAT_REPLAY_LOCAL: Dict[str, float] = {}
_CHAT_REPLAY_LOCK = RLock()


def _authoritative_backend_lane(data: Dict[str, Any]) -> Optional[str]:
    """Resolve the finalized V2 lane without promoting unrecognized payload values."""
    lane = str(data.get("turn_intent") or "").strip().upper()
    if not lane and data.get("policy_answered") is True:
        lane = "POLICY_QUESTION"
    return lane if lane in RECOMMENDATION_LANES else None


def _request_tenant_id(request: Request | None) -> str:
    """Return the tenant already authorized by the authentication dependency."""
    identity = (
        getattr(getattr(request, "state", None), "operator_identity", None)
        if request is not None else None
    )
    tenant_id = str(getattr(identity, "tenant_id", "") or "").strip()
    if tenant_id:
        return tenant_id
    from src.app.platform.tenant_context import current_tenant_id
    return str(current_tenant_id() or "default")


def _chat_in_progress(*, idempotency_key: str = "") -> Dict[str, Any]:
    return {
        "status": "in_progress",
        "retryable": True,
        "retry_after_ms": 750,
        "idempotency_key": str(idempotency_key or "")[:128] or None,
        "assistant_message": (
            "I’m still working on that request. Retrying with the same "
            "request key will return the completed result without running it twice."
        ),
    }


def _chat_request_timeout_seconds() -> float:
    try:
        configured = float(os.getenv("CHAT_REQUEST_TIMEOUT_SEC", "30") or 30)
    except (TypeError, ValueError):
        configured = 30.0
    return max(0.1, min(configured, 120.0))


def _resolve_uid(payload: Dict[str, Any] | None, request: Request | None = None) -> str:
    raw = str((payload or {}).get("uid") or "").strip()
    if raw and raw.lower() != "demo-user":
        return raw[:128]
    session_id = str((payload or {}).get("session_id") or "").strip()
    if session_id:
        return f"anon:{session_id[:96]}"
    if request and request.client and request.client.host:
        safe_host = re.sub(r"[^a-zA-Z0-9:._-]", "", str(request.client.host))
        if safe_host:
            return f"anon:{safe_host[:96]}"
    return f"anon:{uuid.uuid4().hex[:16]}"


def _normalize_recent_messages(raw: Any, *, limit: int = 16) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    rows = raw if isinstance(raw, list) else []
    for item in rows:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant", "system"} or not content:
            continue
        out.append({"role": role[:10], "content": content[:500]})
    return out[-max(1, int(limit or 1)) :]


def _extract_confirmed_slots(*, query: str, response: Dict[str, Any] | None = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    budget = _extract_budget_bounds(query)
    if budget.get("budget_min") is not None:
        out["budget_min"] = budget.get("budget_min")
    if budget.get("budget_max") is not None:
        out["budget_max"] = budget.get("budget_max")
    # Preserve whole-order budget semantics across the CART_MUTATE short circuit. Without these
    # typed fields, a later quantity change falls back to the budget from the original search.
    try:
        from src.app.services.budget_grammar import classify_budget_scope, parse_budget

        budget_scope = classify_budget_scope(query)
        parsed_budget = parse_budget(query)
        if budget_scope == "total" and parsed_budget and parsed_budget.budget_max is not None:
            total_budget = int(parsed_budget.budget_max)
            if total_budget > 0:
                out["budget_scope"] = "total"
                out["total_budget_cents"] = total_budget * 100
                out["budget_max"] = total_budget
        elif budget_scope == "per_unit":
            out["budget_scope"] = "per_unit"
    except Exception:
        logger.warning("confirmed-slot budget parsing failed", exc_info=True)
    brands = _extract_brand_mentions(query)
    if brands:
        out["brands"] = brands[:6]

    data = response if isinstance(response, dict) else {}
    applied = data.get("nqe_selection_applied") if isinstance(data.get("nqe_selection_applied"), dict) else {}
    used = data.get("constraints_used") if isinstance(data.get("constraints_used"), dict) else {}
    # LONG-HORIZON qty memory: the bulk unit count survives non-qty turns the same way budget does —
    # turn 1 "need 25 laptops", turn 3 "which has the best battery?" must still know it's a 25-unit
    # conversation (Add buttons + procurement previews read requested_quantity every turn).
    _rq = data.get("requested_quantity")
    if isinstance(_rq, (int, float)) and 1 <= int(_rq) <= 1000:
        out["order_quantity"] = int(_rq)
    decision = data.get("decision") if isinstance(data.get("decision"), dict) else {}
    exact_product_sku = str(decision.get("exact_product_sku") or "").strip()
    if exact_product_sku:
        out["exact_product_sku"] = exact_product_sku
    for key in ("budget_min", "budget_max", "use_case", "gpu_preference", "availability", "condition", "buyer_persona", "issue_type"):
        v = applied.get(key)
        if v is None:
            v = used.get(key)
        if v is not None:
            out[key] = v
    for key in ("brands", "specs", "brand_excludes", "use_case_tags"):
        vv = applied.get(key)
        if vv is None:
            vv = used.get(key)
        if isinstance(vv, list) and vv:
            out[key] = vv[:12]
    # The legacy chat extractor sees every catalog brand token as positive.  Reconcile it
    # with the shared core's clamped exclusion before persisting session memory.
    excluded = {str(v).strip().lower() for v in (out.get("brand_excludes") or []) if str(v).strip()}
    if excluded and isinstance(out.get("brands"), list):
        kept = [v for v in out["brands"] if str(v).strip().lower() not in excluded]
        if kept:
            out["brands"] = kept
        else:
            out.pop("brands", None)
    if isinstance(data.get("product_identity"), dict):
        ident = data.get("product_identity") or {}
        if ident.get("constraints"):
            out["image_identity"] = ident.get("constraints")
    return out


def _chat_replay_mark_once(redis, *, replay_key: str, ttl_seconds: int) -> bool:
    ttl = max(1, int(ttl_seconds or 1))
    redis_key = f"chat:replay:{replay_key}"
    try:
        # NX+EX ensures only the first request in the replay window is accepted.
        ok = redis.set(redis_key, "1", ex=ttl, nx=True)
        return bool(ok)
    except Exception:
        now = time.time()
        with _CHAT_REPLAY_LOCK:
            exp = float(_CHAT_REPLAY_LOCAL.get(replay_key) or 0.0)
            if exp > now:
                return False
            _CHAT_REPLAY_LOCAL[replay_key] = now + ttl
            stale = [k for k, v in _CHAT_REPLAY_LOCAL.items() if float(v or 0.0) <= now]
            for k in stale[:128]:
                _CHAT_REPLAY_LOCAL.pop(k, None)
        return True


def _store_chat_message(
    db,
    *,
    uid: str,
    role: str,
    content: str,
    trace_id: str | None,
    session_id: str | None = None,
    tenant_id: str | None = None,
    session_epoch: str | None = None,
) -> str | None:
    from src.app.services.chat_persistence import store_chat_message

    return store_chat_message(
        db,
        uid=uid,
        role=role,
        content=content,
        trace_id=trace_id,
        session_id=session_id,
        tenant_id=tenant_id,
        session_epoch=session_epoch,
    )


def _extract_budget_bounds(query: str) -> Dict[str, int | None]:
    """Parse a budget from natural phrasings into {budget_min, budget_max}. Handles ranges (between/from/
    bare 'X to Y'/'$X-$Y'), ceilings (under/below/up to), floors (over/at least), PER-UNIT budgets
    ('$1900 each', 'per laptop'), and fuzzy amounts ('budget about 1900', 'spend ~$2000', a lone '$1900').
    Amounts require 3+ digits so quantities like '15 laptops' are never read as a price.

    Delegates FIRST to the canonical budget_grammar; local patterns are legacy fallback only."""
    from src.app.services.budget_grammar import parse_budget as _canon
    _bp = _canon(query)
    if _bp is not None and _bp.found:
        return {"budget_min": _bp.budget_min, "budget_max": _bp.budget_max}
    q = str(query or "").lower()

    def _n(s: str) -> int:
        return int(str(s).replace(",", ""))

    # 1) explicit range — between/from X to/and/- Y, "$X-$Y", or a bare "X to Y" (both 3-5 digit)
    m = (re.search(r"\b(?:between|from)\s*\$?([\d,]{3,7})\s*(?:and|to|\-|–)\s*\$?([\d,]{3,7})", q)
         or re.search(r"\$\s*([\d,]{3,6})\s*(?:to|\-|–)\s*\$?\s*([\d,]{3,6})", q)
         or re.search(r"\b(\d{3,5})\s*(?:to|\-|–)\s*(\d{3,5})\b", q))
    if m:
        lo, hi = _n(m.group(1)), _n(m.group(2))
        return {"budget_min": min(lo, hi), "budget_max": max(lo, hi)}
    # 2) ceiling
    m = re.search(r"\b(?:under|below|max(?:imum)?|up to|no more than|less than)\s*\$?([\d,]{3,7})\b", q)
    if m:
        return {"budget_min": None, "budget_max": _n(m.group(1))}
    # 3) floor
    m = re.search(r"\b(?:over|above|min(?:imum)?|at least|more than)\s*\$?([\d,]{3,7})\b", q)
    if m:
        return {"budget_min": _n(m.group(1)), "budget_max": None}
    # 4) per-unit ceiling — "1900 each", "$1,800 per laptop/unit/device/seat/pc/person"
    m = re.search(r"\$?([\d,]{3,7})\s*(?:each\b|a ?piece\b|apiece\b|per\s+(?:unit|laptop|device|machine|seat|pc|person|user))", q)
    if m:
        return {"budget_min": None, "budget_max": _n(m.group(1))}
    # 5) budget/spend/afford amount (optionally fuzzy) — "budget is about 1900", "can spend 2000"
    m = re.search(r"(?:budget|spend|afford\w*)\b[^\d$]{0,18}\$?([\d,]{3,7})", q)
    if m:
        return {"budget_min": None, "budget_max": _n(m.group(1))}
    # 6) fuzzy/lone money amount — "about $1900", "around 2000", or a lone "$1900" not part of a range
    m = (re.search(r"(?:about|around|approx\w*|roughly|~)\s*\$?\s*([\d,]{3,7})", q)
         or re.search(r"\$\s*([\d,]{3,6})\b(?!\s*(?:to|\-|–))", q))
    if m:
        return {"budget_min": None, "budget_max": _n(m.group(1))}
    return {"budget_min": None, "budget_max": None}


def _is_budget_query_text(query: str | None) -> bool:
    q = str(query or "").strip().lower()
    if not q:
        return False
    if any(
        tok in q
        for tok in (
            "budget",
            "under",
            "below",
            "up to",
            "between",
            "only have",
            "is that enough",
            "is this enough",
            "for high school",
            "for school",
            "for university",
            "for work",
            "for gaming",
        )
    ):
        return True
    bounds = _extract_budget_bounds(q)
    return bounds.get("budget_min") is not None or bounds.get("budget_max") is not None or bool(
        re.search(r"\$\s*\d{3,5}\b", q)
    )


_DEFICIT_OBS_RE = re.compile(
    r"only\s+have\s+a?\s*few|few\s+in\s+stock|limited\s+stock|not\s+enough\s+(?:in\s+)?stock|"
    r"wait\w*\s+(?:for|on)\s+(?:a\s+)?(?:re-?order|re-?stock|restock|backorder|back-?order|the\s+rest|stock)|"
    r"ok\s+(?:to\s+|with\s+)?wait|back-?order|re-?order",
    re.I,
)
_BULK_QTY_RE = re.compile(r"\b(\d{2,5})\s+[a-z][a-z\s]{0,24}?(?:laptop|desktop|monitor|tablet|unit|machine|device|pc)s?\b", re.I)


def _strip_deficit_observation(q: str) -> str:
    """Remove the shortfall-observation tail from a deficit-reorder query so retrieval sees only
    the bulk need. 'i need 50 dell laptops but you only have a few in stock, am i ok waiting for a
    reorder?' -> 'i need 50 dell laptops'. Conservative: only cuts at an observation connector so
    a plain bulk request is never truncated."""
    cut = re.split(
        r"\b(?:but|and)\s+(?:you|i|we)\s+(?:only\s+have|have\s+only|think|know)\b|"
        r"\bbut\s+(?:you\s+)?(?:only\s+have|have\s+a?\s*few|few\s+in\s+stock|limited\s+stock)\b|"
        r",?\s*(?:am\s+i\s+ok|is\s+it\s+ok|ok\s+(?:to\s+|with\s+)?wait)\b",
        q, maxsplit=1, flags=re.I,
    )[0].strip().rstrip(",")
    return cut if len(cut) >= 6 else q


def _is_deficit_reorder_query(q: str) -> bool:
    """A bulk QUANTITY need + a deficit/reorder OBSERVATION ("i need 50 dell laptops but you only
    have a few in stock, ok waiting for a reorder?"). The buyer is acknowledging a shortfall and
    asking about backorder — NOT requesting a low-stock filter. Without this it hit
    _classify_turn_intent's `"only " in q` -> FILTER -> the "few in stock" filter zeroed retrieval
    (live: 0 products, backorder capability fact never reached the answer). Routing it to SEARCH
    lets the bulk-sourcing path run (products + sourcing preview + the reorder-consent narration)."""
    if not _DEFICIT_OBS_RE.search(q):
        return False
    return bool(_BULK_QTY_RE.search(q)) or bool(re.search(r"\b\d{2,5}\b", q))


def _classify_turn_intent(query: str) -> str:
    q = str(query or "").strip().lower()
    if not q:
        return "SEARCH"
    # Deficit/reorder-consent BEFORE the FILTER branch: a "you only have a few in stock, ok to
    # wait for a reorder?" turn is a bulk-sourcing intent, not a stock filter (2026-07-09).
    if _is_deficit_reorder_query(q):
        return "SEARCH"
    # CLAIM-CHECKED support detection (shared predicate with recommend.py's classifier): only a genuine
    # post-purchase claim routes to the support lane. The old bare keyword list here hijacked pre-sales
    # policy questions ("what is your warranty policy?") into photo-triage with zero products.
    from src.app.services.answer_quality import is_support_claim, policy_faq_answer
    if is_support_claim(q):
        return "SUPPORT_CLAIM"
    if policy_faq_answer(q) is not None:
        return "POLICY_QUESTION"
    if (
        " vs " in q
        or "compare" in q
        or "difference" in q
        or "show both" in q
        or "which is better" in q
    ):
        return "COMPARE"
    if (
        q.startswith("why ")
        or " why " in q
        or "explain" in q
        or "reason" in q
        or "if not why" in q
        or "overkill" in q
        or "should i" in q
    ):
        return "EXPLAIN"
    if (
        "under $" in q
        or "between $" in q
        or "budget" in q
        or "price range" in q
        or "widen" in q
        or "increase" in q
        or "decrease" in q
        or "only " in q
        or " with " in q
        or "without " in q
    ):
        return "FILTER"
    return "SEARCH"


def _is_budget_question(item: Dict[str, Any]) -> bool:
    text = str((item or {}).get("text") or "").lower()
    qid = str((item or {}).get("id") or "").lower()
    return any(
        tok in text or tok in qid
        for tok in ("budget", "price range", "price", "widen_budget", "budget_range", "increase_match_space")
    )


def _cart_mutation_short_circuit(
    data: Any,
    *,
    q: str,
    uid: str,
    db,
    redis=None,
    tenant_id: str | None = None,
    session_id: str | None = None,
    session_epoch: str | None = None,
    persist_conversation: bool = True,
) -> Optional[Dict[str, Any]]:
    """CART-MUTATION short-circuit (V2 cart lane, extracted for testability): when the suggest
    hop returns a cart_mutation payload (RECOMMEND_CART_SERVE=on), build the MINIMAL chat
    response — the product/answer-quality/copywriting machinery below chat_query is irrelevant
    (and message-REWRITING) for a cart edit. Forwards the C1 card fields verbatim
    (needs_confirmation/plan_id/ops ride inside cart_mutation). Returns None when this turn is
    not a cart mutation. /chat/stream inherits (it emits chat_query's result verbatim)."""
    if not isinstance(data, dict) or data.get("cart_mutation") is None:
        return None
    tid = data.get("decision_trace_id") or data.get("decision_id") or data.get("trace_id")
    msg = str(data.get("assistant_message") or data.get("message") or "").strip()
    try:
        if not persist_conversation:
            raise RuntimeError("temporary_chat")
        _store_chat_message(
            db,
            tenant_id=tenant_id,
            uid=uid,
            session_id=session_id,
            session_epoch=session_epoch,
            role="user",
            content=q,
            trace_id=tid,
        )
        if msg:
            _store_chat_message(
                db,
                tenant_id=tenant_id,
                uid=uid,
                session_id=session_id,
                session_epoch=session_epoch,
                role="assistant",
                content=msg,
                trace_id=tid,
            )
    except Exception as _cm_exc:
        if persist_conversation:
            logger.debug("cart-mutation chat persist skipped: %s", repr(_cm_exc)[:100])
    multi_intent = None
    try:
        enabled = str(os.getenv("MULTI_INTENT_PLANNER_ENABLED", "")).strip().lower() in (
            "1", "true", "yes", "on",
        )
        if not enabled:
            from src.app.feature_flags import get_flags as _get_flags

            enabled = bool(_get_flags().get("MULTI_INTENT_PLANNER_ENABLED", False))
        if enabled:
            from src.app.services.multi_intent_live import plan_live

            multi_intent = plan_live(str(q or ""), str(uid))
    except Exception as exc:
        # A cart action is still bounded by its own confirmation contract. Keep
        # the planner failure visible instead of silently dropping the other
        # obligations from a mixed buyer turn.
        multi_intent = {
            "warnings": [f"multi_intent planner error: {str(exc)[:120]}"],
            "needs_confirmation": True,
            "plan": [],
        }
    response_slots = _extract_confirmed_slots(query=q, response=data)
    persisted_slots = dict(response_slots)
    mutation = data.get("cart_mutation") if isinstance(data.get("cart_mutation"), dict) else {}
    if mutation.get("needs_confirmation"):
        # A proposal is not accepted case state. The authoritative quantity
        # remains the persisted cart line until the apply endpoint commits.
        persisted_slots.pop("order_quantity", None)
        persisted_slots.pop("quantity", None)
    out = {
        "products": [],
        "view_mode": "cards",
        "assistant_message": msg,
        "cart_mutation": data.get("cart_mutation"),
        "cart_updated": bool(data.get("cart_updated")),
        "cart": data.get("cart"),
        "multi_intent": multi_intent,
        "turn_intent": "CART_MUTATE",
        "execution_mode": data.get("execution_mode") or "v2_served",
        "execution_lane": data.get("execution_lane") or "CART_MUTATE",
        "delegation_reason": data.get("delegation_reason"),
        "action_executed": bool(data.get("action_executed")),
        # Read-only case status/summary responses intentionally keep the buyer's
        # current product/cart/procurement panel in place. This is a typed UI
        # contract, not an inference from an empty product list.
        # A cart amendment is an in-place operation on the visible cart/procurement case.  An
        # empty products list is not permission to replace that view with search results.
        "preserve_current_view": True,
        "case_operation": data.get("case_operation"),
        "case_anchor": data.get("case_anchor") if isinstance(data.get("case_anchor"), dict) else None,
        "state_changed": data.get("state_changed"),
        # Bounded delivery/payment amendments are accepted by the recommendation
        # reducer and then committed later by the cart sourcing boundary.  Keep
        # the canonical constraints at the HTTP/SSE edge; dropping them here made
        # the UI acknowledge the amendment while confirming the old requirements.
        "constraints_used": (
            data.get("constraints_used")
            if isinstance(data.get("constraints_used"), dict) else {}
        ),
        "decision_trace_id": tid,
        "trace_id": tid,
        "next_questions": [],
        "confirmed_slots": response_slots,
        "requested_quantity": (
            data.get("requested_quantity")
            if data.get("requested_quantity") is not None
            else response_slots.get("order_quantity")
        ),
        "explanation": (
            data.get("explanation")
            if isinstance(data.get("explanation"), dict) else None
        ),
        "delivery_feasibility": (
            data.get("delivery_feasibility")
            if isinstance(data.get("delivery_feasibility"), dict) else None
        ),
        "case_obligations": (
            data.get("case_obligations")
            if isinstance(data.get("case_obligations"), list) else []
        ),
        "policy_answer": (
            data.get("policy_answer") if isinstance(data.get("policy_answer"), dict) else None
        ),
        "support_handoff": (
            data.get("support_handoff") if isinstance(data.get("support_handoff"), dict) else None
        ),
        "supplier_status": (
            data.get("supplier_status") if isinstance(data.get("supplier_status"), dict) else None
        ),
        "timing_breakdown": (
            data.get("timing_breakdown")
            if isinstance(data.get("timing_breakdown"), dict)
            else {}
        ),
        "blocked": False,
        "needs_human_review": False,
        "security_route": "allow",
    }
    try:
        if not persist_conversation:
            raise RuntimeError("temporary_chat")
        _persist_chat_structured_state(
            redis=redis,
            uid=uid,
            query=q,
            products=[],
            trace_id=str(tid or "") or None,
            assistant_message=msg,
            confirmed_slots=persisted_slots,
            tenant_id=tenant_id,
            session_epoch=session_epoch,
        )
    except Exception:
        if persist_conversation:
            logger.warning("cart-mutation structured-state persistence failed", exc_info=True)
    return out


def _budget_range_from_slots(slots: Dict[str, Any] | None, query: str) -> Dict[str, int | None]:
    out = _extract_budget_bounds(query)
    s = slots if isinstance(slots, dict) else {}
    if out.get("budget_min") is None and s.get("budget_min") is not None:
        try:
            out["budget_min"] = int(float(s.get("budget_min")))
        except Exception:
            pass
    if out.get("budget_max") is None and s.get("budget_max") is not None:
        try:
            out["budget_max"] = int(float(s.get("budget_max")))
        except Exception:
            pass
    return out


from src.app.services.chat_turn_projection import (
    _brand_hint_from_text, _build_anchor_sections, _build_right_panel_contract,
    _compute_widened_budget, _derive_image_security_posture,
    _extract_brand_mentions, _extract_image_cv_signals,
    _extract_image_product_identity, _image_anchor_hint,
    _include_adaptive_metadata, _merge_material_nqe_answer,
)

def _derive_attack_intent_and_repercussions(cv_signals: Dict[str, Any] | None) -> tuple[str, str]:
    """Map detected CV signals to a plain-English attacker intent + likely repercussions.

    Briefs the human SOC reviewer on *why* an upload was flagged and what could go
    wrong if the image-derived signals were trusted blindly.
    """
    s = cv_signals if isinstance(cv_signals, dict) else {}
    intents: List[str] = []
    repercussions: List[str] = []
    if s.get("qr_prompt_injection") or s.get("qr_external_url_detected") or s.get("qr_code_detected"):
        intents.append(
            "QR-borne indirect prompt injection / redirect to an external "
            "(possible credential-harvest or malware) URL"
        )
        repercussions.append(
            "agent goal hijack, shopper redirected to a malicious site, possible "
            "credential/account compromise"
        )
    if s.get("ocr_prompt_injection"):
        intents.append("text-in-image prompt injection to override system instructions")
        repercussions.append("policy bypass, unauthorised tool or action execution by the agent")
    if s.get("steg_suspicious"):
        intents.append("steganographic payload smuggling (covert data/command channel)")
        repercussions.append("covert data exfiltration or staged second-stage payload delivery")
    if float(s.get("adversarial_score") or 0.0) >= 0.5:
        intents.append("adversarial perturbation crafted to evade the CV classifiers")
        repercussions.append("model evasion, mislabelled product, downstream fraud")
    if s.get("manipulation_detected"):
        intents.append("image manipulation / forgery")
        repercussions.append("return or warranty fraud, fabricated evidence")
    if s.get("encoded_payload_detected") or s.get("polyglot_suspected"):
        intents.append("encoded / polyglot file payload (a file valid as two formats at once)")
        repercussions.append("parser confusion, sandbox escape, malware delivery")
    if not intents:
        intents.append("untrusted or anomalous image upload")
        repercussions.append("elevated review required before any image-derived signal can be trusted")
    return "; ".join(intents), "; ".join(repercussions)


def _summarize_recognized_product(labels: List[str] | None) -> Optional[str]:
    """Best-effort short human label for what the image shows, from SAFE visual labels.

    Lets us keep shopping context in the user-facing message even when the image
    was flagged — we still recognised the product, we just quarantined the
    malicious channel (QR/OCR/steg). Returns None when nothing is recognisable.
    """
    toks = [str(x).lower() for x in (labels or []) if str(x).strip()]
    if not toks:
        return None
    blob = " ".join(toks)
    _is_gaming = any(
        t in blob for t in ("gaming", "rog", "legion", "raider", "predator", "nitro", "alienware", "omen", "tuf")
    )
    if any(t in blob for t in ("laptop", "notebook", "macbook")):
        return "gaming laptop" if _is_gaming else "laptop"
    if any(t in blob for t in ("desktop", "tower", "workstation")) or "pc" in toks:
        return "gaming PC" if _is_gaming else "desktop PC"
    if any(t in blob for t in ("phone", "smartphone", "iphone")):
        return "phone"
    if any(t in blob for t in ("tablet", "ipad")):
        return "tablet"
    if any(t in blob for t in ("monitor", "display", "screen")):
        return "monitor"
    if any(t in blob for t in ("headphone", "headset", "earphone")):
        return "headset"
    return toks[0]


def _assess_image_compromise_breach(
    *,
    merged_text: str,
    cv_signals: Dict[str, Any] | None,
    source_ip: str | None,
    uid: str | None,
    image_hash: str | None,
    posture: Dict[str, Any],
    request: Any = None,
) -> Dict[str, Any]:
    """Run a synchronous breach assessment for a compromised image upload.

    Enriches the requester IP via ASN/GeoIP (known-bad-actor scoring), maps the
    attack to MITRE ATLAS / OWASP tags, and notifies humans by persisting a
    security event that auto-routes to an incident + WORM audit. Returns a
    structured summary for the chat response.

    NEVER blocks the recommendation — this is the warn-and-continue path.
    """
    from src.app.security.observer import analyze_payload, emit_security_event

    intent, repercussions = _derive_attack_intent_and_repercussions(cv_signals)
    sec_payload: Dict[str, Any] = {
        "query": str(merged_text or "")[:1000],
        "source": "chat_image_compromise",
    }
    if source_ip:
        sec_payload["ip"] = source_ip
    if uid:
        sec_payload["uid"] = uid
    if cv_signals:
        sec_payload["cv_signals"] = cv_signals

    severity = str(posture.get("severity") or "high")
    details: Dict[str, Any] = {}
    try:
        analysis = analyze_payload(sec_payload)
        if isinstance(analysis, dict):
            severity = str(analysis.get("severity") or severity)
            details = analysis.get("details") if isinstance(analysis.get("details"), dict) else {}
    except Exception:
        details = {}

    geo: Dict[str, Any] = {}
    signals: Dict[str, Any] = {}
    try:
        geo = ((details.get("network") or {}).get("geo")) or {}
        signals = details.get("signals") or {}
    except Exception:
        geo, signals = {}, {}

    # Known-bad-actor determination via ASN / GeoIP risk.
    bad_asn: set = set()
    try:
        from src.app.security.observer import _load_bad_asn
        bad_asn = set(_load_bad_asn())
    except Exception:
        bad_asn = set()
    is_bad_actor = bool(
        signals.get("ip_risk")
        or float(geo.get("risk") or 0.0) >= 0.7
        or geo.get("is_hosting")
        or geo.get("is_vpn")
        or (geo.get("asn") in bad_asn if geo.get("asn") is not None else False)
    )
    ip_assessment = {
        "ip_hash": ((details.get("network") or {}).get("ip_hash")),
        "asn": geo.get("asn"),
        "asn_org": geo.get("asn_org"),
        "country": geo.get("country"),
        "is_hosting": bool(geo.get("is_hosting")),
        "is_vpn": bool(geo.get("is_vpn")),
        "risk": float(geo.get("risk") or 0.0),
        "known_bad_actor": is_bad_actor,
        "geo_country_mismatch": bool(signals.get("geo_country_mismatch")),
    }

    # Notify humans: persist a security event that auto-routes to an incident + WORM.
    human_notified = False
    try:
        emit_security_event(
            path="/api/v1/chat/image-compromise",
            payload={
                **sec_payload,
                "attack_intent": intent,
                "repercussions": repercussions,
                "image_hash": str(image_hash or "")[:64],
                "ip_assessment": ip_assessment,
            },
            request=request,
        )
        human_notified = True
    except Exception:
        human_notified = False

    assessment = {
        "severity": severity,
        "attack_intent": intent,
        "potential_repercussions": repercussions,
        "ip_assessment": ip_assessment,
        "mitre_atlas": (details.get("mitre_atlas") or [])[:8],
        "owasp_llm_top10": (details.get("owasp_llm_top10") or [])[:8],
        "owasp_agentic_top10": (details.get("owasp_agentic_top10") or [])[:8],
        "human_notified": human_notified,
        "route": str(posture.get("route") or "escalate"),
    }
    try:
        log_trace_event(
            trace_id=None,
            event_type="image_compromise_breach_assessment",
            source_type="agent",
            source_id="Security_Observer_Agent",
            target_type="chat",
            target_id=uid,
            payload={
                "severity": severity,
                "attack_intent": intent,
                "known_bad_actor": is_bad_actor,
                "asn": geo.get("asn"),
                "country": geo.get("country"),
                "image_hash": str(image_hash or "")[:64],
            },
        )
    except Exception:
        pass
    return assessment


def _derive_qr_details(sig: Dict[str, Any] | None, posture: Dict[str, Any] | None = None) -> Dict[str, Any]:
    p = posture if isinstance(posture, dict) else {}
    route = str(p.get("route") or "allow")
    return derive_qr_legitimacy_details(sig, policy_route=route)


def _image_trust_channels(posture: Dict[str, Any] | None) -> Dict[str, bool]:
    posture = posture or {}
    route = str(posture.get("route") or "allow")
    if posture.get("analysis_pending"):
        return {"visual_embedding_trusted": False, "ocr_trusted": False, "qr_trusted": False}
    if posture.get("analysis_degraded") and not posture.get("security_risk"):
        return {"visual_embedding_trusted": True, "ocr_trusted": False, "qr_trusted": False}
    if route == "allow":
        return {"visual_embedding_trusted": True, "ocr_trusted": True, "qr_trusted": True}
    if route == "visual_sanitized":
        return {"visual_embedding_trusted": True, "ocr_trusted": False, "qr_trusted": False}
    if route == "escalate":
        return {"visual_embedding_trusted": True, "ocr_trusted": False, "qr_trusted": False}
    return {"visual_embedding_trusted": False, "ocr_trusted": False, "qr_trusted": False}


def _frameworks_for_image_security(*, signals: Dict[str, Any], severity: str) -> Dict[str, Any]:
    norm = {str(k): bool(v) for k, v in (signals or {}).items()}
    dread = compute_dread(signals={}, cv_signals=norm, severity=severity or "warn")
    corr = correlate_security_analysis(
        channel="image",
        severity=severity,
        tags=[],
        reasons=[],
        threat_correlation={"mitre_attack": [], "dread": dread},
        signals=norm,
        evidence={},
    )
    return {
        "mitre_atlas": corr.get("mitre_atlas") or [],
        "mitre_attack": corr.get("mitre_attack") or [],
        "owasp_llm_top10": corr.get("owasp_llm_top10") or [],
        "stride_categories": corr.get("stride_categories") or [],
        "pasta": corr.get("pasta") or {},
        "pasta_stage": corr.get("pasta_stage"),
        "dread": dread,
        "cvss": corr.get("cvss") or {},
        "compliance": corr.get("compliance") or {},
        "lev": corr.get("lev") or {},
    }


def _decode_image_b64(image_obj: Dict[str, Any] | None) -> bytes:
    from src.app.services.chat_image_normalization import decode_image_b64

    return decode_image_b64(image_obj)


def _stash_image_blob_for_recommend(mem: Memory, uid: str, image_hash: str, image_bytes: bytes) -> None:
    if not uid or not image_hash or not image_bytes:
        return
    max_bytes = int(os.getenv("CHAT_IMAGE_BLOB_CACHE_MAX_BYTES", "262144") or 262144)
    if len(image_bytes) > max_bytes:
        return
    kv = mem.get_kv(uid) or {}
    blob_cache = kv.get("image_blob_cache") if isinstance(kv.get("image_blob_cache"), dict) else {}
    blob_cache[str(image_hash)] = base64.b64encode(image_bytes).decode("ascii")
    # Keep only latest 2 blobs to bound session size.
    keys = list(blob_cache.keys())
    if len(keys) > 2:
        for k in keys[:-2]:
            blob_cache.pop(k, None)
    kv["image_blob_cache"] = blob_cache
    mem.set_kv(uid, kv)


def _persist_chat_structured_state(
    *,
    redis,
    uid: str,
    query: str,
    products: List[Dict[str, Any]] | None,
    trace_id: str | None,
    assistant_message: str | None = None,
    recent_messages: List[Dict[str, Any]] | None = None,
    confirmed_slots: Dict[str, Any] | None = None,
    semantic_resolution: Dict[str, Any] | None = None,
    case_anchor: Dict[str, Any] | None = None,
    tenant_id: str | None = None,
    session_epoch: str | None = None,
) -> None:
    from src.app.services.chat_persistence import persist_chat_structured_state

    return persist_chat_structured_state(
        redis=redis, uid=uid, query=query, products=products, trace_id=trace_id,
        budget=_extract_budget_bounds(query), brands=_extract_brand_mentions(query),
        assistant_message=assistant_message, recent_messages=recent_messages,
        confirmed_slots=confirmed_slots, semantic_resolution=semantic_resolution,
        case_anchor=case_anchor, tenant_id=tenant_id, session_epoch=session_epoch,
    )
async def _idem_single_flight(
    redis,
    key: str,
    producer,
    *,
    wait_timeout_seconds: float = 2.0,
):
    from src.app.services.chat_transport import idempotent_single_flight

    return await idempotent_single_flight(
        redis, key, producer, wait_timeout_seconds=wait_timeout_seconds,
        in_progress_factory=lambda idem_key: _chat_in_progress(idempotency_key=idem_key),
        logger=logger,
    )


async def _call_recommend_in_process(
    request: Request,
    params: Dict[str, Any],
    *,
    redis: Any,
    db: Any,
    role: str,
    cancellation: Any = None,
) -> tuple[int, Dict[str, Any]]:
    from src.app.services.chat_recommendation_dispatch import dispatch_chat_recommendation

    return await dispatch_chat_recommendation(
        request, params, redis=redis, db=db, role=role,
        tenant_id_resolver=_request_tenant_id, cancellation=cancellation,
    )


@router.post("/query")
async def chat_query(
    request: Request,
    payload: Dict,
    redis=Depends(get_redis),
    db=Depends(get_db),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    """Single-flight entry (review-7 P0). Idempotency-Key rides both /chat/stream and this
    fallback; when present, the second in-flight duplicate returns the first's cached result
    rather than double-resolving. No key (or no redis) → straight through."""
    idem = (request.headers.get("Idempotency-Key") or request.headers.get("idempotency-key")
            or (payload or {}).get("idempotency_key"))

    async def _run() -> Dict[str, Any]:
        if not idem or redis is None:
            return await _chat_query_impl(request, payload, redis, db, role)
        try:
            configured_wait = float(
                os.getenv("CHAT_SINGLE_FLIGHT_WAIT_SEC", "2") or 2,
            )
        except (TypeError, ValueError):
            configured_wait = 2.0
        wait_budget = min(
            max(0.05, _chat_request_timeout_seconds() - 0.1),
            max(0.05, configured_wait),
        )
        return await _idem_single_flight(
            redis,
            f"chat:idem:{str(idem)[:128]}",
            lambda: _chat_query_impl(request, payload, redis, db, role),
            wait_timeout_seconds=wait_budget,
        )

    try:
        return await asyncio.wait_for(
            _run(),
            timeout=_chat_request_timeout_seconds(),
        )
    except asyncio.TimeoutError:
        return _chat_in_progress(idempotency_key=str(idem or ""))


def _effective_chat_query(payload: Dict[str, Any]) -> tuple[str, bool, Any]:
    """Normalize typed and transcribed input before any routing decision.

    A transcript is provenance, not a second semantic channel. When the browser
    submits both fields, the typed query remains authoritative and both must be
    semantically identical by frontend contract.
    """
    source = payload or {}
    typed = str(source.get("query") or "").strip()
    voice = source.get("voice_transcript")
    voice_text = str(voice or "").strip() if isinstance(voice, str) else ""
    return typed or voice_text, bool(voice_text), source.get("voice_confidence")


async def _chat_query_impl(request: Request, payload: Dict, redis, db, role: str) -> Dict:
    """Chat query wrapper that delegates to recommendation endpoint and
    returns a canonical UI-friendly shape.

    Accepts two payload formats:
    Legacy:  { query, uid, image_labels?, image_ocr_text?, image_hash?, image_intent? }
    New:     { query, uid, images?: [{labels, ocr_text, hash, damage_score, confidence}],
               image_intent?, voice_transcript?, voice_confidence?, recent_messages? }
    """
    q, voice_used, voice_confidence = _effective_chat_query(payload)
    from src.app.services.buyer_evidence_source_resolution import (
        extract_submitted_source_url,
        remove_submitted_source_urls,
    )

    # Prefer the URL actually present in the buyer utterance.  The browser hint
    # is accepted only when the text transport omitted it; it never overrides
    # what the buyer submitted.
    submitted_source_url = (
        extract_submitted_source_url(q)
        or str((payload or {}).get("buyer_source_url") or "").strip()[:2000]
    )
    # URL bytes are evidence input, not semantic workload prose. Isolate them
    # before model routing, case-purpose persistence, retrieval, or trace copy.
    if submitted_source_url:
        q = remove_submitted_source_urls(q)
    submitted_query = q
    voice_transcript = q if voice_used else None

    # -----------------------------------------------------------------------
    # Normalize multimodal image payload (new array format → legacy flat)
    # -----------------------------------------------------------------------
    from src.app.services.chat_image_normalization import normalize_chat_images

    normalized_images = normalize_chat_images(payload)
    images_array = normalized_images.images
    image_labels_in = normalized_images.labels
    image_ocr_text_in = normalized_images.ocr_text
    image_hash_in = normalized_images.image_hash
    image_intent_in = normalized_images.intent
    image_product_identity_in = normalized_images.product_identity
    image_cv_signals_in = normalized_images.cv_signals
    damage_score_in = normalized_images.damage_score
    is_product_photo_in = normalized_images.is_product_photo
    image_blob_bytes = normalized_images.blob
    has_image = normalized_images.has_image
    image_security_posture = _derive_image_security_posture(image_cv_signals_in)
    breach_assessment: Optional[Dict[str, Any]] = None
    # How the (untrusted) image was handled downstream:
    #   "sanitized_visual" = kept safe product recognition, quarantined QR/OCR/steg
    #   "text_only_fallback" = pixels themselves suspect (adversarial/manipulated) → ask to clarify
    image_handling_mode: Optional[str] = None
    recognized_image_label: Optional[str] = None

    if not q.strip():
        raise HTTPException(status_code=400, detail="query_required")

    # Resolve literal game identities from bounded local provider data before
    # any model or catalogue deadline. This is evidence preflight only: it does
    # not rank products or grant commerce authority. It guarantees that a known
    # title's canonical identity survives model variation and timeout recovery.
    preflight_workload_evidence: list[Dict[str, Any]] = []
    try:
        from src.app.services.recommendation_core.literal_workload_identity import (
            literal_game_identity_candidate,
        )
        from src.app.services.connectors.workload_evidence import default_registry

        for workload_kind, workload_name in literal_game_identity_candidate(q):
            resolved = default_registry().resolve(
                workload_kind, workload_name, allow_live=False,
            )
            if resolved is not None:
                preflight_workload_evidence.append(resolved.to_dict())
    except Exception:
        logger.debug("literal workload identity preflight skipped", exc_info=True)

    uid = _resolve_uid(payload, request)
    session_id = str((payload or {}).get("session_id") or "")[:128] or None
    tenant_id = _request_tenant_id(request)
    session_epoch = session_id or uid
    memory_mode = str((payload or {}).get("memory_mode") or "standard").strip().lower()
    if memory_mode not in {"standard", "temporary"}:
        raise HTTPException(status_code=400, detail="invalid_memory_mode")
    persist_conversation = memory_mode == "standard"
    source_ip = request.client.host if request and request.client else ""
    # TEXT prompt-injection tally (ledger-only, no behavior change): classic override phrasings are
    # already harmless here (they fall through to a normal product turn — the LLM never sees them as
    # instructions), but every attempt is RECORDED as a refused_request so security/QA see the pressure.
    try:
        if re.search(r"\b(?:ignore|disregard|forget|override)\b.{0,40}\b(?:instructions?|prompts?|rules?|polic\w+|previous|above)\b"
                     r"|\byou\s+are\s+now\b|\bsystem\s+prompt\b|\bjailbreak\b|\bdeveloper\s+mode\b", q, re.I):
            from src.app.services.capability_gap import GAP_REFUSED_REQUEST, record_gap
            from src.app.deps import hash_uid as _huid
            from src.app.models.db import db_session as _db_session
            with _db_session() as _idb:
                record_gap(_idb, category=GAP_REFUSED_REQUEST, utterance=str(q)[:300],
                           refusal_reason="prompt_injection_suspected", surface="chat",
                           uid_hash=_huid(uid) if uid else None)
    except Exception as _inj_exc:
        logger.debug("injection ledger write failed: %s", _inj_exc)
    turn_intent = _classify_turn_intent(q)
    # Deficit-reorder: the buyer's shortfall OBSERVATION ("but you only have a few in stock, am i
    # ok waiting for a reorder?") is not a retrieval constraint — suggest()'s parser reads
    # "few in stock" as a low-stock filter and zeroes results. Strip the observation so retrieval
    # sees the clean bulk request ("50 dell laptops" -> products + sourcing preview); the reorder
    # intent is preserved via _deficit_reorder so the availability/backorder answer still fires.
    _deficit_reorder = _is_deficit_reorder_query(q)
    _query_for_retrieval = q
    if _deficit_reorder:
        _query_for_retrieval = _strip_deficit_observation(q)
    copywriting_requested = bool((payload or {}).get("copywriting_enabled") is True)
    copy_profile_id = str((payload or {}).get("copy_profile_id") or "").strip() or None
    copy_surface = str((payload or {}).get("copy_surface") or "storefront").strip() or "storefront"
    brand_name = str((payload or {}).get("brand_name") or "").strip() or None
    copy_profile_inline = (payload or {}).get("copy_profile")
    if not isinstance(copy_profile_inline, dict):
        copy_profile_inline = None

    # Reload confirmed slots at turn start to keep context continuity explicit.
    # Also capture the PRIOR turn's shortlist NOW (before this turn's recommend overwrites it) so the
    # multi-intent planner can bind "actually 15 instead" to the item the buyer was just shown when the
    # cart is empty (e.g. an add-to-cart 409'd on stock).
    _prior_turn_shortlist: List[str] = []
    try:
        if not persist_conversation:
            raise RuntimeError("temporary_chat")
        _prior_ss = Memory(
            redis,
            tenant_id=tenant_id,
            session_epoch=session_epoch,
        ).get_structured_state(uid) or {}
        _confirmed_in = _prior_ss.get("confirmed_slots") if isinstance(_prior_ss.get("confirmed_slots"), dict) else {}
        _confirmed_request = (
            payload.get("confirmed_slots")
            if isinstance(payload.get("confirmed_slots"), dict) else {}
        )
        if _confirmed_in or _confirmed_request:
            payload["confirmed_slots"] = {**_confirmed_in, **_confirmed_request}
        _ls = _prior_ss.get("last_shortlist_skus") or _prior_ss.get("last_valid_shortlist_skus")
        if isinstance(_ls, list):
            _prior_turn_shortlist = [str(s) for s in _ls if s][:5]
    except Exception:
        pass

    # Replay protection: reject immediate duplicates from retries/replays.
    try:
        # SKIP when invoked from the /chat/stream wrapper: chat_stream calls chat_query internally, so
        # marking here would make the frontend's stream→/chat/query FALLBACK look like a duplicate (the
        # 409 chat_replay_detected demo blocker). Only the terminal /chat/query enforces replay protection.
        _skip_replay = bool((payload or {}).get("_internal_skip_replay"))
        replay_nonce = str(
            (payload or {}).get("nonce")
            or (payload or {}).get("message_id")
            or request.headers.get("x-chat-nonce")
            or request.headers.get("idempotency-key")
            or ""
        ).strip()[:128]
        replay_shape = {
            "nqe_selection": (payload or {}).get("nqe_selection"),
            "image_hash": (payload or {}).get("image_hash"),
            "images": [
                str((x or {}).get("image_hash") or (x or {}).get("hash") or "")[:64]
                for x in ((payload or {}).get("images") or [])[:3]
                if isinstance(x, dict)
            ],
            "has_voice": bool((payload or {}).get("voice_transcript")),
        }
        replay_material = "|".join(
            [
                uid,
                str(session_id or ""),
                str(source_ip or ""),
                str(q or "").strip().lower()[:500],
                replay_nonce
                or hashlib.sha256(
                    json.dumps(replay_shape, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
            ]
        )
        replay_key = hashlib.sha256(replay_material.encode("utf-8")).hexdigest()
        params_case_patch_idempotency_key = replay_nonce or replay_key
        replay_ttl = int(os.getenv("CHAT_REPLAY_TTL_SECONDS", "20") or 20)
        require_nonce = str(os.getenv("CHAT_REPLAY_REQUIRE_NONCE", "0")).strip().lower() in ("1", "true", "yes", "on")
        if require_nonce and not replay_nonce and not _skip_replay:
            raise HTTPException(status_code=428, detail={"message": "nonce_required"})
        if replay_nonce:
            replay_ttl = max(replay_ttl, 120)
        if not _skip_replay and not _chat_replay_mark_once(redis, replay_key=replay_key, ttl_seconds=replay_ttl):
            raise HTTPException(
                status_code=409,
                detail={"message": "chat_replay_detected", "retry_after_seconds": replay_ttl},
            )
    except HTTPException:
        raise
    except Exception:
        params_case_patch_idempotency_key = hashlib.sha256(
            f"{tenant_id}|{session_epoch}|{q}".encode("utf-8")
        ).hexdigest()

    # -----------------------------------------------------------------------
    # Cross-modal security: scan merged text (user query + voice + OCR + labels + QR)
    # -----------------------------------------------------------------------
    try:
        merged_text_parts = [q]
        if isinstance(voice_transcript, str) and voice_transcript.strip():
            merged_text_parts.append(voice_transcript[:500])
        if isinstance(image_ocr_text_in, str):
            merged_text_parts.append(image_ocr_text_in[:500])
        if isinstance(image_labels_in, list):
            merged_text_parts.append(" ".join(str(x) for x in image_labels_in[:12]))
        elif isinstance(image_labels_in, str):
            merged_text_parts.append(image_labels_in[:200])
        # Extract QR-decoded text from image security results
        for img in (images_array or []):
            if isinstance(img, dict):
                sec = img.get("security") or {}
                if isinstance(sec, dict):
                    qr_texts = sec.get("qr_data") or sec.get("signals", {}).get("qr_data")
                    if isinstance(qr_texts, str) and qr_texts.strip():
                        merged_text_parts.append(qr_texts[:200])
                    elif isinstance(qr_texts, list):
                        merged_text_parts.extend(str(t)[:200] for t in qr_texts[:4])
        merged_text = " ".join(merged_text_parts)

        from src.app.security.observer import analyze_payload
        _sec_payload: Dict[str, Any] = {"query": merged_text, "source": "chat_multimodal"}
        if source_ip:
            _sec_payload["ip"] = source_ip
        if uid:
            _sec_payload["uid"] = uid
        if image_cv_signals_in:
            _sec_payload["cv_signals"] = image_cv_signals_in
        sec_result = analyze_payload(_sec_payload)
        if isinstance(sec_result, dict):
            sev = str(sec_result.get("severity") or "").lower()
            if sev in ("critical", "high"):
                log_trace_event(
                    trace_id=None, event_type="cross_modal_security_block",
                    source_type="agent", source_id="Security_Observer_Agent",
                    target_type="chat", target_id=None,
                    payload={"severity": sev, "signals": sec_result.get("signals")},
                )
                # Warn-and-continue: when an image is involved, run a full breach
                # assessment (IP/ASN/GeoIP + human escalation). Products still flow.
                if (image_cv_signals_in and breach_assessment is None
                        and bool(image_security_posture.get("security_risk"))):
                    try:
                        breach_assessment = _assess_image_compromise_breach(
                            merged_text=merged_text,
                            cv_signals=image_cv_signals_in,
                            source_ip=source_ip,
                            uid=uid,
                            image_hash=image_hash_in,
                            posture=image_security_posture,
                            request=request,
                        )
                    except Exception:
                        breach_assessment = None
    except Exception:
        pass

    # -----------------------------------------------------------------------
    # Image intent routing (when images present and intent not pre-resolved)
    # -----------------------------------------------------------------------
    intent_routing_result: Optional[Dict[str, Any]] = None
    if has_image and (not image_intent_in or image_intent_in == "auto"):
        try:
            recent_msgs = (payload or {}).get("recent_messages") or []
            labels_for_router: List[str] = []
            if isinstance(image_labels_in, list):
                labels_for_router = [str(x) for x in image_labels_in[:12]]
            elif isinstance(image_labels_in, str):
                labels_for_router = [s.strip() for s in image_labels_in.split(",")][:12]

            intent_routing_result = classify_image_intent(
                image_labels=labels_for_router,
                image_ocr_text=str(image_ocr_text_in or "")[:500],
                damage_score=damage_score_in,
                is_product_photo=is_product_photo_in,
                user_query=q,
                recent_messages=recent_msgs if isinstance(recent_msgs, list) else [],
            )
            image_intent_in = intent_routing_result.get("intent") or "disambiguate"
        except Exception:
            image_intent_in = "disambiguate"

    # If intent is disambiguate, return disambiguation response without calling recommend
    if image_intent_in == "disambiguate" and has_image:
        out = {
            "products": [],
            "view_mode": "cards",
            "confidence": None,
            "decision_trace_id": None,
            "assistant_message": (
                "I see the photo! What would you like to do?\n\n"
                "\u2022 Type **\"find similar\"** to search for products like this\n"
                "\u2022 Type **\"report issue\"** to start a return or complaint\n"
                "\u2022 Or describe what you need and I'll figure it out"
            ),
            "disambiguation": True,
            "needs_disambiguation": True,
            "intent_routing": intent_routing_result,
            "next_questions": [
                {"id": "visual_search", "text": "Find similar products", "goal": "visual_search"},
                {"id": "cv_triage", "text": "Report an issue / return", "goal": "cv_triage"},
                {"id": "describe", "text": "Let me describe what I need", "goal": "freeform"},
            ],
            "llm_model": None,
            "model_tier": None,
            "complexity": score_query_complexity(q, context={"has_image": True}),
        }
        try:
            if not persist_conversation:
                raise RuntimeError("temporary_chat")
            _store_chat_message(
                db,
                tenant_id=tenant_id,
                uid=uid,
                session_id=session_id,
                session_epoch=session_epoch,
                role="user",
                content=q,
                trace_id=None,
            )
            _store_chat_message(
                db,
                tenant_id=tenant_id,
                uid=uid,
                session_id=session_id,
                session_epoch=session_epoch,
                role="assistant",
                content=str(out.get("assistant_message") or ""),
                trace_id=None,
            )
            _persist_chat_structured_state(
                redis=redis,
                uid=uid,
                query=q,
                products=[],
                trace_id=None,
                assistant_message=str(out.get("assistant_message") or ""),
                recent_messages=(payload or {}).get("recent_messages") if isinstance((payload or {}).get("recent_messages"), list) else None,
                confirmed_slots=_extract_confirmed_slots(query=q, response=None),
                tenant_id=tenant_id,
                session_epoch=session_epoch,
            )
        except Exception:
            pass
        return out

    # -----------------------------------------------------------------------
    # Complexity scoring for trace enrichment
    # -----------------------------------------------------------------------
    complexity_result = score_query_complexity(q, context={
        "has_image": has_image,
        "conversation_turn": int((payload or {}).get("conversation_turn") or 0),
    })
    try:
        if not persist_conversation:
            raise RuntimeError("temporary_chat")
        uid_for_cache = _resolve_uid(payload, request)
        if uid_for_cache and isinstance(image_hash_in, str) and image_hash_in.strip() and image_blob_bytes:
            mem = Memory(
                redis,
                tenant_id=tenant_id,
                session_epoch=session_epoch,
            )
            _stash_image_blob_for_recommend(mem, uid_for_cache, image_hash_in.strip()[:128], image_blob_bytes)
    except Exception:
        pass

    from src.app.services.recommendation_ingress import authorize_recommendation_ingress
    _recommend_ingress = authorize_recommendation_ingress(
        request=request, redis=redis, query=q, uid=uid,
        tenant_id=_request_tenant_id(request),
        benign_shopping_query=False,
    )

    # -----------------------------------------------------------------------
    # Persist recent conversation messages so the recommend pipeline can
    # reference them for context continuity (avoids "context rot").
    # -----------------------------------------------------------------------
    try:
        if not persist_conversation:
            raise RuntimeError("temporary_chat")
        _uid_msg = uid
        _recent_msgs_raw = (payload or {}).get("recent_messages") or []
        if isinstance(_recent_msgs_raw, list) and _recent_msgs_raw:
            _mem_state = Memory(
                redis,
                tenant_id=tenant_id,
                session_epoch=session_epoch,
            )
            _ss = _mem_state.get_structured_state(_uid_msg) or {}
            _ss["recent_messages"] = _normalize_recent_messages(_recent_msgs_raw, limit=12)
            _mem_state.set_structured_state(_uid_msg, _ss)
    except Exception:
        pass

    # Log escalation trace event for steg/suspicious images that need human review
    # (the lockdown path below has its own trace; this covers the escalate route)
    if bool(image_security_posture.get("needs_human_review")) and not bool(image_security_posture.get("chat_lockdown")):
        try:
            _esc_signals = {str(k): bool(v) for k, v in (image_cv_signals_in or {}).items() if isinstance(v, bool)}
            _esc_steg_score = float((image_cv_signals_in or {}).get("steg_score") or 0.0)
            log_trace_event(
                trace_id=None,
                event_type="image_security_escalation",
                source_type="agent",
                source_id="Security_Observer_Agent",
                target_type="chat",
                target_id=uid,
                payload={
                    "route": str(image_security_posture.get("route") or "escalate"),
                    "severity": str(image_security_posture.get("severity") or "high"),
                    "signals": _esc_signals,
                    "steg_score": _esc_steg_score,
                    "image_hash": str(image_hash_in or "")[:64],
                    "query_preview": str(q or "")[:120],
                    "warning": str(image_security_posture.get("warning_message") or ""),
                },
            )
        except Exception:
            pass

    # Legacy hard-lock (deny products) is OFF by default. Policy is warn-and-continue:
    # a compromised image must NOT deny the shopping result — see the fall-through block
    # below. Set IMAGE_COMPROMISE_HARD_LOCK=1 only if you explicitly want the old deny.
    _image_hard_lock_enabled = str(os.getenv("IMAGE_COMPROMISE_HARD_LOCK", "0")).strip().lower() in ("1", "true", "yes", "on")
    if bool(image_security_posture.get("chat_lockdown")) and _image_hard_lock_enabled:
        decision_trace_id = str(uuid.uuid4())
        _sec_signals = {str(k): bool(v) for k, v in (image_cv_signals_in or {}).items() if isinstance(v, bool)}
        _qr = _derive_qr_details(image_cv_signals_in, image_security_posture)
        _trust = _image_trust_channels(image_security_posture)
        _fw = _frameworks_for_image_security(signals=_sec_signals, severity=str(image_security_posture.get("severity") or "high"))
        security_payload = {
            "severity": str(image_security_posture.get("severity") or "high"),
            "route": "lockdown",
            "policy_route": "lockdown",
            "signals": _sec_signals,
            "qr": _qr,
            "image_trust_channels": _trust,
            "qr_payload_types": image_cv_signals_in.get("qr_payload_types") if isinstance(image_cv_signals_in.get("qr_payload_types"), list) else [],
            "qr_payloads": (image_cv_signals_in.get("qr_payloads") or [])[:6] if isinstance(image_cv_signals_in.get("qr_payloads"), list) else [],
            "qr_redirect_probe": image_cv_signals_in.get("qr_redirect_probe") if isinstance(image_cv_signals_in.get("qr_redirect_probe"), dict) else {},
            "frameworks": _fw,
            "mitre_atlas": _fw.get("mitre_atlas") or [],
            "mitre_attack": _fw.get("mitre_attack") or [],
            "owasp_llm_top10": _fw.get("owasp_llm_top10") or [],
            "stride_categories": _fw.get("stride_categories") or [],
            "pasta": _fw.get("pasta") or {},
            "pasta_stage": _fw.get("pasta_stage"),
            "dread": _fw.get("dread") or {},
            "cvss": _fw.get("cvss") or {},
            "compliance": _fw.get("compliance") or {},
            "summary": "Chat lockdown due to malicious image security posture.",
        }
        try:
            log_trace_event(
                trace_id=decision_trace_id,
                event_type="security_scan",
                source_type="agent",
                source_id="Security_Observer_Agent",
                target_type="chat",
                target_id=None,
                payload=security_payload,
            )
        except Exception:
            pass
        out = {
            "products": [],
            "view_mode": "cards",
            "confidence": None,
            "decision_trace_id": decision_trace_id,
            "trace_id": decision_trace_id,
            "assistant_message": str(image_security_posture.get("warning_message") or "Chat locked for safety review."),
            "next_questions": [
                {"id": "continue_text_only", "text": "Continue without image (text-only recommendations)", "goal": "text_only_mode"},
                {"id": "reupload_clean", "text": "Reupload clean product-only image", "goal": "clean_reupload"},
                {"id": "human_escalation", "text": "Open human support now", "goal": "human_escalation"},
            ],
            "blocked": True,
            "image_untrusted": True,
            "image_degraded_mode": False,
            "chat_lockdown": True,
            "needs_human_review": True,
            "right_panel": {
                "mode": "shopping",
                "show_tiers": False,
                "image_untrusted": True,
                "image_degraded_mode": False,
                "security_route": "lockdown",
                "security_summary": str(image_security_posture.get("warning_message") or ""),
            },
        }
        try:
            if not persist_conversation:
                raise RuntimeError("temporary_chat")
            _store_chat_message(
                db,
                tenant_id=tenant_id,
                uid=uid,
                session_id=session_id,
                session_epoch=session_epoch,
                role="user",
                content=q,
                trace_id=decision_trace_id,
            )
            _store_chat_message(
                db,
                tenant_id=tenant_id,
                uid=uid,
                session_id=session_id,
                session_epoch=session_epoch,
                role="assistant",
                content=str(out.get("assistant_message") or ""),
                trace_id=decision_trace_id,
            )
        except Exception:
            pass
        return out

    # ── Severe image threat → warn-and-continue (default policy) ──────────────
    # A malicious-image posture must NOT deny the shopping result. We run a full
    # breach assessment (IP/ASN/GeoIP + human escalation), strengthen the
    # user-facing warning, and fall through to text-only recommendations. The
    # downstream recommend call runs in text_only_fallback because the image is
    # marked untrusted (image_security_posture.image_untrusted).
    if bool(image_security_posture.get("chat_lockdown")) and not _image_hard_lock_enabled:
        if breach_assessment is None:
            try:
                breach_assessment = _assess_image_compromise_breach(
                    merged_text=str(q or ""),
                    cv_signals=image_cv_signals_in,
                    source_ip=source_ip,
                    uid=uid,
                    image_hash=image_hash_in,
                    posture=image_security_posture,
                    request=request,
                )
            except Exception:
                breach_assessment = None
        # Short, accurate badge summary for the right-panel (the detailed,
        # mode-aware user message is built later in the response surface). Override
        # the stale "Chat is temporarily locked…" copy from the posture since we
        # are NOT locking — we continue with the safe channels.
        image_security_posture["route"] = "escalate_continue"
        image_security_posture["warning_message"] = (
            "Suspicious image element detected and neutralised — recommendations "
            "continue; flagged for security review."
        )
        image_security_posture["image_untrusted"] = True
        try:
            log_trace_event(
                trace_id=None,
                event_type="image_compromise_warn_and_continue",
                source_type="agent",
                source_id="Security_Observer_Agent",
                target_type="chat",
                target_id=uid,
                payload={
                    "severity": str(image_security_posture.get("severity") or "high"),
                    "route": "escalate_continue",
                    "human_notified": bool((breach_assessment or {}).get("human_notified")),
                },
            )
        except Exception:
            pass

    # Delegate through the in-process compatibility boundary. The mature suggest
    # contract remains authoritative until facade dispatch is fully hoisted.
    params = {"uid": uid, "query": _query_for_retrieval,
              "trace_id": _recommend_ingress.trace_id,
              "session_epoch": session_epoch,
              "memory_mode": memory_mode}
    params["case_patch_idempotency_key"] = params_case_patch_idempotency_key
    if _deficit_reorder:
        params["reorder_consent_intent"] = "true"  # emphasize the backorder-consent answer downstream
    if turn_intent and turn_intent != "SEARCH":
        params["turn_intent"] = turn_intent
    # Explicit chip and explicit free-text permission share one per-turn consent
    # contract. The model decides what evidence is needed; it cannot grant
    # permission on the buyer's behalf.
    from src.app.services.clarification_state import external_research_consent_granted

    turn_explicit_research_consent = bool(
        bool((payload or {}).get("external_research_consent"))
        or external_research_consent_granted(submitted_query)
    )
    from src.app.services.research_policy import (
        active_research_policy, tenant_policy_auto_research_authorized,
    )
    turn_research_policy = active_research_policy()
    turn_policy_research_authorized = tenant_policy_auto_research_authorized()
    turn_research_authorized = bool(
        turn_explicit_research_consent or turn_policy_research_authorized
    )
    turn_research_authorization_basis = (
        "buyer_action" if turn_explicit_research_consent else
        "tenant_policy" if turn_policy_research_authorized else "none"
    )
    if turn_research_authorized:
        params["external_research_consent"] = "true"
    nqe_selection = (payload or {}).get("nqe_selection") or {}
    active_shopping_case_id = str(
        (payload or {}).get("shopping_case_id") or ""
    ).strip()[:200]
    active_shopping_case_purpose = ""
    canonical_case_snapshot: Dict[str, Any] = {}
    if active_shopping_case_id:
        active_case = db.execute(sql_text(
            "SELECT uid, retained_purpose FROM shopping_cases "
            "WHERE tenant_id=:tenant_id AND case_id=:case_id LIMIT 1"
        ), {
            "tenant_id": tenant_id,
            "case_id": active_shopping_case_id,
        }).mappings().first()
        if active_case is None:
            raise HTTPException(status_code=409, detail="shopping_case_not_found")
        if str(active_case.get("uid") or "") != str(uid or ""):
            raise HTTPException(status_code=403, detail="shopping_case_not_owned")
        active_shopping_case_purpose = str(
            active_case.get("retained_purpose") or ""
        ).strip()[:500]
        try:
            from src.app.deps import hash_uid
            from src.app.services.conversation_case_state import ensure_case_state

            # A shopping case created by the provisional-exploration endpoint may
            # predate its first chat turn. Materialize its typed projection now so
            # even that first follow-up is routed with the canonical objective.
            ensure_case_state(
                db,
                tenant_id=tenant_id,
                case_id=active_shopping_case_id,
                session_epoch=session_epoch,
                subject_ref=hash_uid(uid),
                authoritative_anchor={"objective": active_shopping_case_purpose},
            )

            case_state_row = db.execute(sql_text(
                "SELECT state_json,version FROM conversation_case_state "
                "WHERE tenant_id=:tenant_id AND case_id=:case_id "
                "AND session_epoch=:session_epoch AND subject_ref=:subject_ref LIMIT 1"
            ), {
                "tenant_id": tenant_id,
                "case_id": active_shopping_case_id,
                "session_epoch": session_epoch,
                "subject_ref": hash_uid(uid),
            }).first()
            if case_state_row:
                raw_state = json.loads(case_state_row[0])
                typed_state = raw_state.get("procurement_case_state")
                if isinstance(typed_state, dict):
                    canonical_case_snapshot = {
                        **typed_state,
                        "case_id": active_shopping_case_id,
                        "revision": int(case_state_row[1]),
                    }
                    params["canonical_case"] = canonical_case_snapshot
        except Exception as exc:
            logger.error("pre-router procurement case hydration failed", exc_info=True)
            raise HTTPException(
                status_code=503,
                detail="procurement_case_state_unavailable",
            ) from exc
    pending_clarification: Dict[str, Any] = {}
    try:
        pending_clarification = Memory(
            redis,
            tenant_id=tenant_id,
            session_epoch=session_epoch,
        ).get_pending_clarification(uid)
    except Exception:
        pending_clarification = {}
    # Detect the high-confidence lexical switch before clarification expansion
    # and recommendation dispatch.  This keeps the old case snapshot, consent,
    # evidence and question text out of the new subject's model input.  The old
    # case is durably superseded later once the full routing result is present.
    from src.app.services.recommendation_core.literal_workload_identity import (
        deterministic_named_workload_switch,
    )
    deterministic_pre_route_subject_switch = bool(
        active_shopping_case_id
        and deterministic_named_workload_switch(submitted_query)
    )
    if deterministic_pre_route_subject_switch:
        from src.app.services.subject_switch_boundary import clear_subject_scoped_state
        clear_subject_scoped_state(
            params,
            retain_same_turn_consent=turn_research_authorized,
        )
        pending_clarification = {}

    # URL intake has a strict fast-fail boundary.  An invalid, ambiguous, or
    # unenrolled origin is fully decidable from the reviewed local registry; it
    # must not wait behind model interpretation or catalog ranking.  Materialize
    # the case and its receipt in the same database operation, then return the
    # zero-fetch decision immediately.  Resolved enrolled sources continue to
    # the normal governed research pipeline below.
    if submitted_source_url:
        from src.app.services.buyer_evidence_source_resolution import (
            resolve_buyer_evidence_source,
        )

        _early_source_resolution = resolve_buyer_evidence_source(
            source_url=submitted_source_url,
            retained_purpose=submitted_query,
        )
        if _early_source_resolution.status != "resolved":
            from datetime import datetime, timezone
            from src.app.models.orm import ShoppingCase
            from src.app.routers.shopping_cases import (
                ResolveBuyerEvidenceSourceRequest,
                _resolve_case_evidence_source_with_db,
            )
            from src.app.services.subject_switch_boundary import clear_subject_scoped_state

            _replaced_case_id = active_shopping_case_id or None
            if not active_shopping_case_id or deterministic_pre_route_subject_switch:
                _source_trace_id = uuid.uuid4().hex
                _source_case_id = f"sc-{_source_trace_id}"
                now = datetime.now(timezone.utc)
                if deterministic_pre_route_subject_switch and active_shopping_case_id:
                    db.execute(sql_text(
                        "UPDATE shopping_cases SET status='superseded',updated_at=:updated_at "
                        "WHERE tenant_id=:tenant_id AND case_id=:case_id"
                    ), {
                        "updated_at": now,
                        "tenant_id": tenant_id,
                        "case_id": active_shopping_case_id,
                    })
                db.add(ShoppingCase(
                    case_id=_source_case_id,
                    tenant_id=tenant_id,
                    uid=str(uid or "guest")[:200],
                    status="active",
                    retained_purpose=str(submitted_query or q or "")[:500],
                    created_at=now,
                    updated_at=now,
                ))
                db.commit()
            else:
                _source_case_id = active_shopping_case_id
                _source_trace_id = active_shopping_case_id.removeprefix("sc-")

            _source_result = await _resolve_case_evidence_source_with_db(
                _source_case_id,
                ResolveBuyerEvidenceSourceRequest(
                    uid=uid,
                    source_url=submitted_source_url,
                    research_authorized=False,
                    authorization_basis="none",
                ),
                x_tenant_id=tenant_id,
                db=db,
            )
            _shared_budget = _extract_budget_bounds(submitted_query)
            for _budget_key in ("budget_min", "budget_max"):
                if _shared_budget.get(_budget_key) is not None:
                    params[_budget_key] = _shared_budget[_budget_key]
            _switch_receipt = (
                clear_subject_scoped_state(
                    params,
                    retain_same_turn_consent=turn_research_authorized,
                )
                if deterministic_pre_route_subject_switch else None
            )
            if _switch_receipt is not None:
                _switch_receipt.update({
                    "previous_case_id": _replaced_case_id,
                    "replacement_case_id": _source_case_id,
                })
            _source_reason = str(
                (_source_result.get("resolution") or {}).get("reason")
                or "source_not_approved"
            )
            _link_assessment = (
                (_source_result.get("source_intake_certificate") or {})
                .get("security", {}).get("link_assessment") or {}
            )
            _link_relevance = str(
                _link_assessment.get("relevance") or "relevance_unresolved"
            ).replace("_", " ")
            _link_use = str(
                _link_assessment.get("recommended_use")
                or "provide an enrolled official requirements source"
            ).replace("_", " ")
            return {
                "products": [],
                "view_mode": "cards",
                "confidence": None,
                "decision_trace_id": _source_trace_id,
                "trace_id": _source_trace_id,
                "shopping_case_id": _source_case_id,
                "assistant_message": (
                    "I inspected the submitted link before using it. It is classified as "
                    f"{_link_relevance}, but it is not an enrolled canonical source "
                    f"({_source_reason}). I made zero network calls and did not retain its "
                    f"query parameters or use its claims. Next: {_link_use}. The full "
                    "source-safety receipt is available in Decision Trace."
                ),
                "next_questions": [],
                "blocked": True,
                "degraded": False,
                "buyer_evidence_source_resolution": _source_result,
                "subject_switch_boundary": _switch_receipt,
                "workload_authorization": {
                    "status": "blocked",
                    "reason": "submitted_source_not_enrolled",
                    "evidence": preflight_workload_evidence,
                    "state_prevented": [
                        "catalog_qualification", "buyer_commitment", "supplier_rfq",
                    ],
                },
                "execution_state_envelope": {
                    "schema_version": "unified-execution-state-v1",
                    "execution_status": "completed",
                    "research_authority": "not_granted",
                    "evidence_status": "source_rejected",
                    "decision_status": "blocked",
                    "commerce_authority": "none",
                },
            }
    # Research consent belongs to the active semantic case, not merely the click
    # that granted it.  Reuse it only inside the same tenant/session-scoped,
    # unexpired pending contract; a new or superseding objective must ask again.
    if bool(pending_clarification.get("external_research_consent")):
        params["external_research_consent"] = "true"
    clarification_reduction = None
    try:
        from src.app.services.clarification_state import reduce_clarification_turn

        clarification_reduction = reduce_clarification_turn(
            query=str(q or ""),
            nqe_selection=nqe_selection if isinstance(nqe_selection, dict) else {},
            pending=pending_clarification,
            intent_hint=turn_intent,
        )
        q = clarification_reduction.effective_query
    except Exception:
        logger.warning("typed clarification reduction failed; preserving buyer turn", exc_info=True)
        clarification_reduction = None
    pending_clarification_consumed = bool(
        clarification_reduction
        and clarification_reduction.consume_pending
        and pending_clarification
    )
    pending_clarification_suspended = bool(
        clarification_reduction
        and clarification_reduction.suspend_pending
        and pending_clarification
    )
    from src.app.services.clarification_state import commercial_obligations

    case_commercial_obligations = list(
        clarification_reduction.interrupting_obligations
        if clarification_reduction and clarification_reduction.interrupting_obligations
        else commercial_obligations(str(submitted_query or ""))
        if active_shopping_case_id else ()
    )
    if active_shopping_case_id and case_commercial_obligations:
        log_trace_event(
            trace_id=active_shopping_case_id.removeprefix("sc-"),
            event_type="shopping_case_obligations_retained",
            source_type="stage",
            source_id="Clarification_State",
            target_type="shopping_case",
            target_id=active_shopping_case_id,
            tenant_id=tenant_id,
            payload={
                "case_id": active_shopping_case_id,
                "status": "retained",
                "pending_question_status": (
                    "suspended" if pending_clarification_suspended else "not_present"
                ),
                "obligations": [
                    {
                        "kind": obligation,
                        "resolution_owner": (
                            "supplier" if obligation == "supplier_enquiry" else "buyer"
                        ),
                        "buyer_text": str(submitted_query or "")[:500],
                    }
                    for obligation in case_commercial_obligations
                ],
            },
        )
    if (
        clarification_reduction
        and clarification_reduction.answer
        and clarification_reduction.question_id
    ):
        params["clarification_answer"] = {
            "question_id": str(clarification_reduction.question_id)[:80],
            "value": str(clarification_reduction.answer)[:500],
            "relation": str(clarification_reduction.relation)[:40],
            "authority": "buyer_authored_candidate",
        }
    params["query"] = q
    confirmed_slots = (payload or {}).get("confirmed_slots") if isinstance((payload or {}).get("confirmed_slots"), dict) else {}
    if not confirmed_slots:
        try:
            recent_for_slots = (payload or {}).get("recent_messages") if isinstance((payload or {}).get("recent_messages"), list) else []
            for msg in reversed(recent_for_slots or []):
                if not isinstance(msg, dict) or str(msg.get("role") or "").lower() != "user":
                    continue
                slots = _extract_confirmed_slots(query=str(msg.get("content") or ""), response=None)
                if slots:
                    confirmed_slots = slots
                    break
        except Exception:
            confirmed_slots = {}
    if confirmed_slots:
        params["confirmed_slots"] = dict(confirmed_slots)
    if isinstance(nqe_selection, dict):
        try:
            oval = str(nqe_selection.get("option_value") or "").strip().lower()
            if oval.startswith("expand_budget:+"):
                delta = int(oval.split(":+", 1)[1])
                # The current query is usually the button label ("Widen more (+$400)").
                # Do not re-parse that label as a real budget cap; widen from confirmed
                # prior slots only, otherwise "$400" collapses a prior 1100-1400 range.
                base_budget = _budget_range_from_slots(confirmed_slots, "")
                widened = _compute_widened_budget(base_budget, delta)
                q = (
                    f"{q}. budget between ${int(widened['budget_min'])} and ${int(widened['budget_max'])} "
                    "(widened deterministically from prior budget)"
                )
                params["query"] = q
                params["budget_min"] = int(widened["budget_min"])
                params["budget_max"] = int(widened["budget_max"])
                params["budget_widen_mode"] = "deterministic_ladder"
                params["budget_widen_delta"] = int(delta)
        except Exception:
            pass
    if isinstance(nqe_selection, dict):
        qid = str(nqe_selection.get("question_id") or "").strip()
        oid = str(nqe_selection.get("option_id") or "").strip()
        olbl = str(nqe_selection.get("option_label") or "").strip()
        oval = str(nqe_selection.get("option_value") or "").strip()
        if qid and oid:
            params["nqe_question_id"] = qid
            params["nqe_option_id"] = oid
            if olbl:
                params["nqe_option_label"] = olbl[:120]
            if oval:
                params["nqe_option_value"] = oval[:120]
    try:
        security_risky_image = bool(image_security_posture.get("image_untrusted"))
        # Channel-separated trust (A-10 resilience): the attack vector is usually
        # in ONE channel (QR / OCR text / steg payload), independent of the visual
        # product recognition. We quarantine the malicious channel but keep the
        # safe visual signal so recommendations stay anchored to the real product.
        # The visual channel itself is only suspect when the *pixels* are attacked
        # (adversarial perturbation or manipulation/forgery).
        _sig = image_cv_signals_in or {}
        _qr_or_text_threat = bool(
            _sig.get("qr_code_detected")
            or _sig.get("qr_external_url_detected")
            or _sig.get("qr_prompt_injection")
            or _sig.get("ocr_prompt_injection")
            or _sig.get("steg_suspicious")
        )
        _adversarial = float(_sig.get("adversarial_score") or 0.0)
        _manip = bool(_sig.get("manipulation_detected"))
        # The visual product recognition is only untrustworthy when the *pixels*
        # are directly attacked: a strong adversarial perturbation (targets the
        # classifier), or manipulation with NO QR/OCR/steg overlay to explain it
        # (i.e. a likely forged photo). A QR pasted onto a real product photo does
        # NOT invalidate "this is a gaming laptop" — we keep that and quarantine
        # only the QR/OCR/steg channel.
        _visual_attacked = bool(_adversarial >= 0.7 or (_manip and not _qr_or_text_threat))
        _visual_trusted = not _visual_attacked

        labels_list: List[str] = []
        if isinstance(image_labels_in, list):
            labels_list = [str(x).strip() for x in image_labels_in if str(x).strip()]
        elif isinstance(image_labels_in, str):
            labels_list = [s.strip() for s in image_labels_in.split(",") if s.strip()]
        recognized_image_label = _summarize_recognized_product(labels_list)

        if not security_risky_image:
            # Full trust — pass every channel (unchanged behavior).
            if labels_list:
                params["image_labels"] = ",".join(labels_list[:12])
            if isinstance(image_ocr_text_in, str) and image_ocr_text_in.strip():
                params["image_ocr_text"] = image_ocr_text_in.strip()[:500]
            if isinstance(image_hash_in, str) and image_hash_in.strip():
                params["image_hash"] = image_hash_in.strip()[:128]
            if isinstance(image_intent_in, str) and image_intent_in.strip():
                params["image_intent"] = image_intent_in.strip()[:32]
        elif _visual_trusted and labels_list:
            # Untrusted upload BUT visual recognition is intact → keep the safe
            # product labels (recommend's image_feature_gate will apply the
            # "sanitized" verdict: anchor on category, strip brand/OCR). We
            # deliberately DO NOT forward OCR text (injection vector) or intent.
            params["image_labels"] = ",".join(labels_list[:12])
            if isinstance(image_hash_in, str) and image_hash_in.strip():
                params["image_hash"] = image_hash_in.strip()[:128]
            params["image_security_mode"] = "sanitized_visual"
            image_handling_mode = "sanitized_visual"
        else:
            # Pixels themselves are suspect (adversarial/manipulated) or nothing
            # was recognizable → text only, and we'll ask the user to clarify the
            # product so we don't lose the shopping context.
            params["image_security_mode"] = "text_only_fallback"
            image_handling_mode = "text_only_fallback"
        # Product identity is forwarded for both trusted and sanitized paths; the
        # recommend-side gate strips brand/identity under the "sanitized" verdict.
        if isinstance(image_product_identity_in, dict) and image_product_identity_in and image_handling_mode != "text_only_fallback":
            params["image_product_identity"] = json.dumps(image_product_identity_in, separators=(",", ":"))[:1000]
        if image_cv_signals_in:
            params["image_cv_signals"] = json.dumps(image_cv_signals_in, separators=(",", ":"))[:1000]
    except Exception:
        pass
    try:
        headers = {}
        try:
            # Forward caller auth to internal request; fallback to local key for dev
            fwd_key = (request.headers.get("x-api-key") if request and hasattr(request, "headers") else None) or "local-merchant-key"
            headers["x-api-key"] = fwd_key
        except Exception:
            headers["x-api-key"] = "local-merchant-key"
        # Bound the storefront upstream wait. The V2 dispatch is now in-process, so configuring a timeout
        # without applying it here does nothing and can strand an HTTP worker indefinitely. wait_for gives
        # the buyer a real response deadline; downstream sync dependencies must still carry their own
        # statement/model timeouts because cancelling this await cannot forcibly stop a running OS thread.
        try:
            _upstream_timeout = float(os.getenv("CHAT_UPSTREAM_TIMEOUT_SEC", "25") or 25)
        except (TypeError, ValueError):
            _upstream_timeout = 25.0
        _upstream_timeout = max(0.05, min(_upstream_timeout, 120.0))
        from src.app.services.recommendation_core.cancellation import RecommendationCancellation
        _recommend_cancellation = RecommendationCancellation.with_timeout(_upstream_timeout)
        dispatch_kwargs = {"redis": redis, "db": db, "role": role}
        # Preserve the long-standing injectable dispatch seam used by local
        # degradation tests and deployments while the production function
        # receives cooperative cancellation.
        import inspect
        if "cancellation" in inspect.signature(_call_recommend_in_process).parameters:
            dispatch_kwargs["cancellation"] = _recommend_cancellation
        status_code, data = await asyncio.wait_for(
            _call_recommend_in_process(request, params, **dispatch_kwargs),
            timeout=_upstream_timeout,
        )
        if status_code is not None:
            # CART-MUTATION short-circuit (V2 cart lane): see _cart_mutation_short_circuit.
            if status_code == 200:
                _cart_out = _cart_mutation_short_circuit(
                    data,
                    q=q,
                    uid=_resolve_uid(payload, request),
                    db=db,
                    redis=redis,
                    tenant_id=tenant_id,
                    session_id=session_id,
                    session_epoch=session_epoch,
                    persist_conversation=persist_conversation,
                )
                if _cart_out is not None:
                    return _cart_out
            if status_code == 403 and isinstance(data, dict):
                # Safety/policy blocks are a normal outcome; surface them as a friendly chat response.
                blocked = data.get("detail") if isinstance(data.get("detail"), dict) else data
                decision_trace_id = (
                    blocked.get("trace_id")
                    or blocked.get("decision_trace_id")
                    or blocked.get("decision_id")
                    or blocked.get("approval_id")
                )
                if _is_budget_query_text(q):
                    budget_hint = _budget_range_from_slots(confirmed_slots, q)
                    budget_phrase = None
                    if budget_hint.get("budget_min") is not None and budget_hint.get("budget_max") is not None:
                        budget_phrase = f"${int(budget_hint['budget_min']):,}-${int(budget_hint['budget_max']):,}"
                    elif budget_hint.get("budget_max") is not None:
                        budget_phrase = f"under ${int(budget_hint['budget_max']):,}"
                    elif budget_hint.get("budget_min") is not None:
                        budget_phrase = f"from ${int(budget_hint['budget_min']):,}"
                    msg = (
                        f"I treated this as a shopping budget request{f' for {budget_phrase}' if budget_phrase else ''}, "
                        "not sensitive data. I couldn't complete the recommendation on that pass, so try the same question once more or add the main use-case in one line."
                    )
                    followups = [
                        {"id": "retry_budget_search", "text": "Retry this as a budget shopping search", "goal": "retry_search"},
                        {"id": "clarify_use_case", "text": "Add the main use-case, for example 'for school' or 'for gaming'.", "goal": "clarify_details"},
                    ]
                    out = {
                        "products": [],
                        "view_mode": "cards",
                        "confidence": None,
                        "decision_trace_id": decision_trace_id,
                        "trace_id": decision_trace_id,
                        "assistant_message": msg,
                        "next_questions": followups,
                        "llm_model": blocked.get("llm_model"),
                        "model_tier": blocked.get("model_tier") or blocked.get("tier"),
                        "blocked": False,
                        "blocked_detail": blocked,
                        "image_untrusted": bool(image_security_posture.get("image_untrusted")),
                        "image_degraded_mode": bool(image_security_posture.get("image_degraded_mode")),
                        "chat_lockdown": bool(image_security_posture.get("chat_lockdown")),
                        "needs_human_review": False,
                        "security_route": str(image_security_posture.get("route") or "allow"),
                    }
                    try:
                        if not persist_conversation:
                            raise RuntimeError("temporary_chat")
                        uid = _resolve_uid(payload, request)
                        _store_chat_message(
                            db,
                            tenant_id=tenant_id,
                            uid=uid,
                            session_id=session_id,
                            session_epoch=session_epoch,
                            role="user",
                            content=q,
                            trace_id=decision_trace_id,
                        )
                        _store_chat_message(
                            db,
                            tenant_id=tenant_id,
                            uid=uid,
                            session_id=session_id,
                            session_epoch=session_epoch,
                            role="assistant",
                            content=str(out.get("assistant_message") or ""),
                            trace_id=decision_trace_id,
                        )
                    except Exception:
                        pass
                    return out
                msg = blocked.get("message") or "This request was blocked due to safety checks. A human will review it."
                followups = [
                    {"id": "remove_sensitive", "text": "Can you rephrase without any personal info, order numbers, or long digit strings?", "goal": "safety_rephrase"},
                    {"id": "use_budget_words", "text": "If you meant a price range, try: 'budget between $900 and $1300'.", "goal": "clarify_details"},
                ]
                out = {
                    "products": [],
                    "view_mode": "cards",
                    "confidence": None,
                    "decision_trace_id": decision_trace_id,
                    "trace_id": decision_trace_id,
                    "assistant_message": msg,
                    "next_questions": followups,
                    "llm_model": blocked.get("llm_model"),
                    "model_tier": blocked.get("model_tier") or blocked.get("tier"),
                    "blocked": True,
                    "blocked_detail": blocked,
                    "image_untrusted": bool(image_security_posture.get("image_untrusted")),
                    "image_degraded_mode": bool(image_security_posture.get("image_degraded_mode")),
                    "chat_lockdown": bool(image_security_posture.get("chat_lockdown")),
                    "needs_human_review": bool(image_security_posture.get("needs_human_review")),
                    "security_route": str(image_security_posture.get("route") or "review"),
                }
                try:
                    if not persist_conversation:
                        raise RuntimeError("temporary_chat")
                    uid = _resolve_uid(payload, request)
                    _store_chat_message(
                        db,
                        tenant_id=tenant_id,
                        uid=uid,
                        session_id=session_id,
                        session_epoch=session_epoch,
                        role="user",
                        content=q,
                        trace_id=decision_trace_id,
                    )
                    _store_chat_message(
                        db,
                        tenant_id=tenant_id,
                        uid=uid,
                        session_id=session_id,
                        session_epoch=session_epoch,
                        role="assistant",
                        content=str(out.get("assistant_message") or ""),
                        trace_id=decision_trace_id,
                    )
                    _persist_chat_structured_state(
                        redis=redis,
                        uid=uid,
                        query=q,
                        products=[],
                        trace_id=decision_trace_id,
                        tenant_id=tenant_id,
                        session_epoch=session_epoch,
                    )
                except Exception:
                    pass
                return out
            if status_code == 429:
                detail = data.get("detail") if isinstance(data.get("detail"), dict) else data
                reason = str((detail or {}).get("reason") or "quota_exceeded")
                decision_trace_id = (detail or {}).get("trace_id")
                return {
                    "products": [], "view_mode": "cards", "confidence": None,
                    "decision_trace_id": decision_trace_id, "trace_id": decision_trace_id,
                    "assistant_message": (
                        "This account has reached its configured AI-assistance allowance for today. "
                        "Your cart and prior work are unchanged; an operator can raise the allowance "
                        "or you can continue after it resets."
                    ),
                    "next_questions": [], "blocked": True, "blocked_detail": detail,
                    "degraded": False, "security_route": "allow", "quota_reason": reason,
                }
            if status_code >= 400:
                raise HTTPException(status_code=status_code, detail=data)
    except Exception as e:
        import traceback as _tb
        _timed_out = isinstance(e, (asyncio.TimeoutError, TimeoutError))
        _failure_reason = "recommend_timeout" if _timed_out else "recommend_error"
        _detail = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
        logger.warning("chat.recommend_call_failed detail=%s tb=%s", _detail, _tb.format_exc()[-500:])
        if _timed_out:
            try:
                from src.app.observability.metrics import record_recommendation_dispatch
                record_recommendation_dispatch(
                    outcome="timeout",
                    lane=str(params.get("turn_intent") or "UNKNOWN"),
                    reason="recommend_timeout",
                )
            except Exception as _metric_exc:
                logger.debug("chat timeout metric skipped: %s", repr(_metric_exc)[:120])
        # N7 (2026-07-07): a hiccup on the internal recommend hop used to surface to the BUYER as a
        # raw HTTP 502 — a broken chat experience. Degrade GRACEFULLY instead: a friendly retry
        # message + a traceable id, HTTP 200. The operator still sees the warning log above and the
        # error trace below; the shopper sees a recoverable prompt, never a stack-status code.
        _degraded_trace = f"chat-degraded-{uuid.uuid4().hex[:12]}"
        try:
            log_trace_event(
                trace_id=_degraded_trace,
                event_type=("system_timeout" if _timed_out else "system_error"),
                source_type="agent",
                source_id="Chat_Delegation", target_type="system", target_id=None,
                payload={
                    "stage": "recommend_hop",
                    "error": _detail[:300],
                    "reason": _failure_reason,
                    "route": "graceful_degrade",
                },
            )
        except Exception:
            pass
        # Preserve an open-world research path when catalog ranking reaches its
        # deadline. This projection is local-only: it calls no discovery
        # provider and grants no fit, supplier, or cart authority.
        if _timed_out:
            _fallback_db_gen = None
            try:
                from datetime import datetime, timezone
                from src.app.models.db import get_db_for_request
                from src.app.models.orm import ShoppingCase
                from src.app.services.accepted_catalog_projection import project_accepted_catalog
                from src.app.services.case_catalog_candidates import build_case_catalog_candidate_set
                from src.app.services.case_research_plan import build_case_research_plan

                _purpose = " ".join(str(q or "").split())[:500]
                _plan = build_case_research_plan(_purpose, allow_open_world=True)
                if _plan is not None:
                    # ``wait_for`` can cancel the await, but it cannot stop the sync
                    # recommendation worker that is still using the request session.
                    # Never let timeout recovery query/commit with that same Session:
                    # doing so races its rollback and can raise IllegalStateChangeError.
                    _fallback_db_gen = get_db_for_request(request)
                    _fallback_db = next(_fallback_db_gen)
                    _case_tenant = _request_tenant_id(request)
                    _candidate_set = build_case_catalog_candidate_set(
                        _fallback_db,
                        retained_purpose=_purpose,
                        tenant_id=_case_tenant,
                        storefront_taxonomy_handle=None,
                    )
                    _projection = project_accepted_catalog(
                        _fallback_db, accepted_claims=[], desired_outcome=_purpose,
                        tenant_id=_case_tenant,
                        hypothesis_labels={
                            item.hypothesis_id: item.label for item in _plan.hypotheses
                        },
                        candidate_configuration_ids=_candidate_set.configuration_ids,
                    )
                    # Keep case and trace identity reversible. The research
                    # endpoint derives the trace by removing only ``sc-``.
                    _case_id = f"sc-{_degraded_trace}"
                    _case_uid = _resolve_uid(payload, request)
                    existing = _fallback_db.execute(sql_text(
                        "SELECT 1 FROM shopping_cases "
                        "WHERE tenant_id=:tenant_id AND case_id=:case_id LIMIT 1"
                    ), {"tenant_id": _case_tenant, "case_id": _case_id}).first()
                    if existing is None:
                        now = datetime.now(timezone.utc)
                        _fallback_db.add(ShoppingCase(
                            case_id=_case_id, tenant_id=_case_tenant,
                            uid=str(_case_uid or "guest")[:200], status="active",
                            retained_purpose=_purpose, created_at=now, updated_at=now,
                        ))
                        _fallback_db.commit()
                    _ambiguity = {
                        "schema_version": "ambiguity-exploration-v1",
                        "case_id": _case_id, "trace_id": _degraded_trace,
                        "retained_purpose": _purpose, "status": "provisional",
                        "interpretations": [
                            item.model_dump(mode="json") for item in _plan.hypotheses
                        ],
                        "next_question": {"id": "research_scope", "text": _plan.next_question},
                        "research_choices": [
                            "research_approved_sources", "upload_requirements",
                            "enter_specifications", "continue_provisionally",
                        ],
                        "execution": "local_exploration_completed_after_recommend_timeout",
                        "evidence": "material_gaps", "decision": "exploration_allowed",
                        "cart_authority": "none",
                        "provider_accounting": {"external_calls": 0, "paid_calls": 0},
                        "research_plan_id": _plan.plan_id,
                        "ambiguity_objects": [
                            item.model_dump(mode="json") for item in _plan.ambiguities
                        ],
                        "research_obligations": [
                            item.model_dump(mode="json") for item in _plan.obligations
                        ],
                        "source_candidate_ids": list(_plan.source_candidate_ids),
                        "catalog_candidate_set": _candidate_set.model_dump(mode="json"),
                    }
                    from src.app.services.open_world_query_proposal import (
                        schedule_open_world_query_proposal,
                    )

                    schedule_open_world_query_proposal(_plan)
                    log_trace_event(
                        trace_id=_degraded_trace,
                        event_type="ambiguity_exploration_projected",
                        source_type="stage", source_id="Timeout_Degradation",
                        target_type="ui", target_id="research_fit_panel",
                        payload={
                            **_ambiguity,
                            "shelf_ids": [shelf.shelf_id for shelf in _projection.shelves],
                            "qualification_authority": "none", "commercial_authority": "none",
                        },
                    )
                    _fallback_source_intake = None
                    if submitted_source_url:
                        try:
                            from src.app.routers.shopping_cases import (
                                ResolveBuyerEvidenceSourceRequest,
                                _resolve_case_evidence_source_with_db,
                            )
                            _fallback_source_intake = await _resolve_case_evidence_source_with_db(
                                _case_id,
                                ResolveBuyerEvidenceSourceRequest(
                                    uid=_case_uid,
                                    source_url=submitted_source_url,
                                    research_authorized=turn_research_authorized,
                                    authorization_basis=turn_research_authorization_basis,
                                ),
                                x_tenant_id=_case_tenant,
                                db=_fallback_db,
                            )
                        except Exception as _source_exc:
                            logger.warning(
                                "timeout source intake failed closed: %s",
                                repr(_source_exc)[:160],
                            )
                            _fallback_source_intake = {
                                "schema_version": "buyer-evidence-source-resolution-v1",
                                "case_id": _case_id,
                                "resolution": {
                                    "status": "invalid",
                                    "reason": "source_intake_failed_closed",
                                },
                                "provider_accounting": {
                                    "external_calls": 0, "paid_calls": 0,
                                },
                                "source_intake_certificate": {
                                    "schema_version": "source-intake-certificate-v1",
                                    "case_id": _case_id,
                                    "resolution_status": "invalid",
                                    "security": {
                                        "url_syntax": "isolated_before_routing",
                                        "publisher_authority": "unresolved",
                                        "arbitrary_submitted_path_fetch_allowed": False,
                                    },
                                    "execution": {"network_execution": False},
                                },
                            }
                    _preflight_authorization = (
                        {
                            "status": "evidence_resolved_catalog_pending",
                            "reason": "catalog_ranking_timeout",
                            "evidence": preflight_workload_evidence,
                            "state_prevented": [
                                "catalog_qualification", "buyer_commitment", "supplier_rfq",
                            ],
                        }
                        if preflight_workload_evidence else None
                    )
                    _fallback_assistant_message = (
                        "The catalog-ranking step reached its deadline. I preserved a provisional "
                        "shortlist and research plan; no external source was called. You can "
                        "authorize discovery, upload requirements, or continue provisionally."
                    )
                    _fallback_source_status = str(
                        ((_fallback_source_intake or {}).get("resolution") or {}).get("status")
                        or ""
                    ).lower()
                    if _fallback_source_status == "not_enrolled":
                        _fallback_assistant_message = (
                            "I isolated and security-checked the submitted link, but its publisher "
                            "is not an enrolled canonical source for this case. I made zero network "
                            "calls, did not retain its query parameters, and did not use its claims. "
                            "You can upload requirements or choose an enrolled source."
                        )
                    elif _fallback_source_status == "invalid":
                        _fallback_assistant_message = (
                            "I isolated the submitted link, but URL intake failed closed. I made "
                            "zero network calls and did not use its claims. You can upload the "
                            "requirements or provide another approved source."
                        )
                    return {
                        "products": [], "view_mode": "cards", "confidence": None,
                        "decision_trace_id": _degraded_trace, "trace_id": _degraded_trace,
                        "assistant_message": _fallback_assistant_message,
                        "next_questions": [], "blocked": False, "degraded": True,
                        "degraded_reason": _failure_reason, "needs_human_review": False,
                        "security_route": "allow", "ambiguity_exploration": _ambiguity,
                        "product_shelves": _projection.model_dump(mode="json"),
                        "workload_authorization": _preflight_authorization,
                        "execution_state_envelope": {
                            "schema_version": "unified-execution-state-v1",
                            "execution_status": "degraded",
                            "research_authority": (
                                "granted" if external_research_consent_granted(str(q or ""))
                                else "required"
                            ),
                            "evidence_status": (
                                "identity_resolved" if preflight_workload_evidence else "material_gaps"
                            ),
                            "decision_status": "provisional",
                            "commerce_authority": "none",
                        },
                        "buyer_evidence_source_resolution": _fallback_source_intake,
                    }
            except Exception:
                logger.warning("timeout ambiguity projection failed", exc_info=True)
            finally:
                if _fallback_db_gen is not None:
                    _fallback_db_gen.close()
        return {
            "products": [],
            "view_mode": "cards",
            "confidence": None,
            "decision_trace_id": _degraded_trace,
            "trace_id": _degraded_trace,
            "assistant_message": (
                "I hit a brief hiccup pulling that together — nothing's lost. Please send that once "
                "more, or add the main use-case in one line (e.g. 'for gaming' or 'for my team')."
            ),
            "next_questions": [
                {"id": "retry_last", "text": "Try that again", "goal": "retry_search"},
                {"id": "add_use_case", "text": "Add the main use-case in one line", "goal": "clarify_details"},
            ],
            "blocked": False,
            "degraded": True,
            "degraded_reason": _failure_reason,
            "needs_human_review": False,
            "security_route": "allow",
        }

    # The pre-dispatch classifier is only an ingress hint. Once the typed facade returns a
    # bounded lane, project that authoritative decision through chat and Decision Trace instead
    # of retaining a contradictory heuristic label (for example POLICY_QUESTION -> SEARCH).
    backend_turn_intent = _authoritative_backend_lane(data)
    backend_lane_authoritative = backend_turn_intent is not None
    if backend_lane_authoritative:
        turn_intent = backend_turn_intent

    # Map results into canonical product shape
    results = data.get("results") or []
    products: List[Dict] = []
    for item in results:
        price = item.get("price")
        price_cents = item.get("price_cents")
        if price is None:
            try:
                if price_cents is not None:
                    price = cents_to_dollars(price_cents)
            except Exception:
                price = None
        if price_cents is None and price is not None:
            try:
                price_cents = dollars_to_cents(price)
            except Exception:
                price_cents = None
        specs = item.get("specs") or {}
        features: List[str] = []
        try:
            if isinstance(specs, dict):
                cpu = specs.get("cpu")
                if cpu:
                    features.append(str(cpu))
                ram = specs.get("ram_gb")
                if ram:
                    features.append(f"{ram}GB RAM")
                storage = specs.get("storage")
                if storage:
                    features.append(str(storage))
                display = specs.get("display")
                if display:
                    features.append(str(display))
                wifi = specs.get("wifi")
                if wifi:
                    features.append(str(wifi))
        except Exception:
            features = []
        # Deterministic "why" badges for UI: prefer positive factors from recommend.
        why: List[str] = []
        try:
            fac = item.get("factors") or {}
            if isinstance(fac, dict):
                pos = fac.get("positive") or []
                if isinstance(pos, list):
                    why = [str(x) for x in pos if isinstance(x, (str, int, float))][:4]
        except Exception:
            why = []
        product_out = {
            "sku": item.get("sku"),
            "name": item.get("name"),
            "price": price,
            "price_cents": price_cents,
            "currency": item.get("currency") or "USD",
            "specs": specs,
            "features": features or (item.get("features") or []),
            "image_url": item.get("image_url"),
            "why": why,
            "score_norm": item.get("score_norm"),
            "score": item.get("score"),
            "factors": item.get("factors") or {},
            "why_not": item.get("why_not") or [],
            "stock": item.get("stock"),
            "stock_level": item.get("stock_level"),
            "stock_status": item.get("stock_status"),
            "stock_urgency": item.get("stock_urgency"),
            "cart_eligible": item.get("cart_eligible"),
            "confidence": item.get("confidence"),
        }
        for optional_key in ("id", "brand", "category", "reason_codes", "contrastive_why", "rank_delta", "rerank_delta"):
            if optional_key in item:
                product_out[optional_key] = item.get(optional_key)
        products.append(product_out)

    # Auto view mode heuristic (simple client-like logic)
    ql = q.lower()
    compare_keywords = ("compare", "vs", "difference", "better", "which")
    if any(k in ql for k in compare_keywords):
        view_mode = "compare" if len(products) <= 5 else "grid"
    elif len(products) > 5:
        view_mode = "grid"
    else:
        view_mode = "cards"

    decision_trace_id = data.get("decision_trace_id") or data.get("decision_id") or data.get("trace_id")
    if decision_trace_id and backend_lane_authoritative:
        try:
            log_trace_event(
                trace_id=decision_trace_id,
                event_type="intent_classify",
                source_type="stage",
                source_id="V2_Recommendation_Facade",
                target_type="chat",
                target_id=None,
                payload={
                    "intent_analysis": {
                        "lane": turn_intent,
                        "intent": turn_intent,
                        "source": "typed_facade_result",
                    },
                    "intent_authority": "finalized_route",
                },
            )
        except Exception:
            pass
    assistant_message = data.get("assistant_message") or data.get("message")
    if bool(image_security_posture.get("image_untrusted")):
        warning = str(
            image_security_posture.get("warning_message")
            or "Image security warning detected. Continuing with text-only recommendations."
        )
        assistant_message = f"{warning}\n\n{assistant_message}" if assistant_message else warning

    # Emit new trace events for the Multimodal / Complexity / Memory tabs
    try:
        if complexity_result:
            log_trace_event(
                trace_id=decision_trace_id, event_type="tier_complexity_score",
                source_type="agent", source_id="Complexity_Scorer",
                target_type="chat", target_id=None,
                payload={
                    "score": complexity_result.get("score"),
                    "tier": complexity_result.get("tier"),
                    "model": complexity_result.get("model"),
                    "signals": complexity_result.get("signals", {}),
                    "explanations": complexity_result.get("explanations", []),
                },
            )
        if intent_routing_result:
            log_trace_event(
                trace_id=decision_trace_id, event_type="image_intent_routing",
                source_type="agent", source_id="ImageIntentRouter",
                target_type="chat", target_id=None,
                payload={
                    "intent": intent_routing_result.get("intent"),
                    "confidence": intent_routing_result.get("confidence"),
                    "reason": intent_routing_result.get("reason"),
                    "signals": intent_routing_result.get("signals", {}),
                    "scores": intent_routing_result.get("scores", {}),
                },
            )
        if has_image or voice_transcript:
            log_trace_event(
                trace_id=decision_trace_id, event_type="multimodal_fusion",
                source_type="stage", source_id="Multimodal_Fusion",
                target_type="chat", target_id=None,
                payload={
                    "image_count": len(images_array) if images_array else (1 if has_image else 0),
                    "voice_used": bool(voice_transcript),
                    "labels": (image_labels_in[:12] if isinstance(image_labels_in, list) else []),
                    "ocr_text": str(image_ocr_text_in or "")[:200],
                },
            )
        if has_image:
            log_trace_event(
                trace_id=decision_trace_id, event_type="image_security_scan",
                source_type="gate", source_id="Image_Security_Sidecar",
                target_type="chat", target_id=None,
                payload={
                    "qr_detected": bool(image_cv_signals_in.get("qr_code_detected")),
                    "qr_prompt_injection": bool(image_cv_signals_in.get("qr_prompt_injection")),
                    "qr_external_url_detected": bool(image_cv_signals_in.get("qr_external_url_detected")),
                    "adversarial_score": float(image_cv_signals_in.get("adversarial_score") or 0.0),
                    "reupload_needed": bool(
                        image_cv_signals_in.get("qr_code_detected")
                        or image_cv_signals_in.get("qr_prompt_injection")
                        or image_cv_signals_in.get("qr_external_url_detected")
                        or image_cv_signals_in.get("manipulation_detected")
                        or image_cv_signals_in.get("ocr_low_confidence_uncertain")
                    ),
                },
            )
            sec_signals = {
                "qr_code_detected": bool(image_cv_signals_in.get("qr_code_detected")),
                "qr_prompt_injection": bool(image_cv_signals_in.get("qr_prompt_injection")),
                "qr_external_url_detected": bool(image_cv_signals_in.get("qr_external_url_detected")),
                "ocr_prompt_injection": bool(image_cv_signals_in.get("ocr_prompt_injection")),
                "ocr_low_confidence_uncertain": bool(image_cv_signals_in.get("ocr_low_confidence_uncertain")),
                "manipulation_detected": bool(image_cv_signals_in.get("manipulation_detected")),
                "damage_detected": bool(image_cv_signals_in.get("damage_detected")),
                "steg_suspicious": bool(image_cv_signals_in.get("steg_suspicious")),
            }
            sec_sev = str(image_security_posture.get("severity") or "info")
            qr_details = _derive_qr_details(image_cv_signals_in, image_security_posture)
            trust_channels = _image_trust_channels(image_security_posture)
            frameworks = _frameworks_for_image_security(signals=sec_signals, severity=sec_sev)
            log_trace_event(
                trace_id=decision_trace_id,
                event_type="security_scan",
                source_type="agent",
                source_id="Security_Observer_Agent",
                target_type="chat",
                target_id=None,
                payload={
                    "severity": sec_sev,
                    "route": str(image_security_posture.get("route") or ("review" if sec_sev in ("high", "warn") else "allow")),
                    "policy_route": str(image_security_posture.get("route") or ("review" if sec_sev in ("high", "warn") else "allow")),
                    "qr": qr_details,
                    "image_trust_channels": trust_channels,
                    "frameworks": frameworks,
                    "mitre_atlas": frameworks.get("mitre_atlas") or [],
                    "mitre_attack": frameworks.get("mitre_attack") or [],
                    "owasp_llm_top10": frameworks.get("owasp_llm_top10") or [],
                    "stride_categories": frameworks.get("stride_categories") or [],
                    "pasta": frameworks.get("pasta") or {},
                    "pasta_stage": frameworks.get("pasta_stage"),
                    "dread": frameworks.get("dread") or {},
                    "cvss": frameworks.get("cvss") or {},
                    "compliance": frameworks.get("compliance") or {},
                    "details": {
                        "signals": sec_signals,
                        "qr_payload_types": image_cv_signals_in.get("qr_payload_types") if isinstance(image_cv_signals_in.get("qr_payload_types"), list) else [],
                        "qr_payloads": (image_cv_signals_in.get("qr_payloads") or [])[:6] if isinstance(image_cv_signals_in.get("qr_payloads"), list) else [],
                        "qr_redirect_probe": image_cv_signals_in.get("qr_redirect_probe") if isinstance(image_cv_signals_in.get("qr_redirect_probe"), dict) else {},
                        "qr": qr_details,
                        "image_trust_channels": trust_channels,
                    },
                    "signals": sec_signals,
                    "summary": "Image-sidecar security signal normalization with QR payload evidence",
                },
            )
    except Exception:
        pass
    next_questions = data.get("next_questions") or []
    # A completed policy answer is informational, not a failed product search. Legacy chat
    # post-processing used to append budget/performance refinements solely because the slate
    # was empty, contradicting the authoritative facade lane.
    if turn_intent == "POLICY_QUESTION":
        next_questions = []
    # Grounding ladder: guarantee the SPECIFIC identity clarification ("Is this a
    # Razer?") leads when the ladder couldn't confirm the product — robust against
    # the NQE cap/transform ordering that can drop it on some paths.
    try:
        _gl_rq = (data.get("constraints_used") or {}).get("_identity_residual_question") if isinstance(data.get("constraints_used"), dict) else None
        if isinstance(_gl_rq, dict) and str(_gl_rq.get("text") or "").strip():
            _grid = str(_gl_rq.get("id") or "clarify_product_identity")
            next_questions = [_gl_rq] + [
                q for q in next_questions
                if isinstance(q, dict) and str(q.get("id") or "") not in ("ask_image_model", _grid)
            ]
    except Exception:
        pass
    if turn_intent in ("EXPLAIN", "SUPPORT_CLAIM"):
        next_questions = [x for x in next_questions if isinstance(x, dict) and not _is_budget_question(x)]
    if not next_questions and not products and turn_intent not in (
        "EXPLAIN", "SUPPORT_CLAIM", "POLICY_QUESTION",
    ):
        # Fallback follow-ups when no candidates are found but backend did not emit NQE prompts.
        next_questions = [
            {
                "id": "widen_budget",
                "text": "Can we widen your budget upward from your current range?",
                "goal": "increase_match_space",
                "options": [
                    {"id": "widen_small", "label": "Widen a little (+$200)", "value": "expand_budget:+200"},
                    {"id": "widen_medium", "label": "Widen more (+$400)", "value": "expand_budget:+400"},
                ],
            },
        ]
        # Ask to relax only a positive hard brand filter. An explicit exclusion is already a
        # resolved buyer constraint; asking them to consider the excluded brand contradicts the
        # same response. Brand names and vertical policy stay in the bounded core payload.
        _confirmed = data.get("confirmed_slots") if isinstance(data.get("confirmed_slots"), dict) else {}
        _decision = data.get("decision") if isinstance(data.get("decision"), dict) else {}
        _hard_brand = _decision.get("brand_filter") or _confirmed.get("brand_filter")
        _excluded = _decision.get("exclude_brand") or _confirmed.get("brand_excludes")
        if _hard_brand and not _excluded:
            next_questions.append({
                "id": "relax_brand",
                "text": "Should I relax the current brand constraint?",
                "goal": "increase_match_space",
            })
        next_questions.append({
            "id": "priority_tradeoff",
            "text": "Prioritize interactive performance or rendering/export speed first?",
            "goal": "resolve_tradeoff",
        })
    # Budget stated but NO in-budget match (nearest-above fallback shows OVER-budget products): still expose
    # the WIDEN option. The old trigger only fired when products was empty, so a budget query that fell back
    # to over-budget picks hid the widen chip (the brittle path GPT-5.5 flagged). Deterministic: budget set +
    # every shown product over it → prepend widen (unless already present). Never clobbers other questions.
    try:
        if turn_intent not in ("EXPLAIN", "SUPPORT_CLAIM") and products:
            # budget from the QUERY (constraints_used is often empty in the chat response) → compare to the
            # shown product prices. If a ceiling was stated and EVERY shown product exceeds it, the buyer got
            # only over-budget picks → offer widen.
            from src.app.services.query_decomposer import decompose as _decompose_budget
            _bmax = _decompose_budget(str(q or "")).budget_max

            def _pp(pr: Dict[str, Any]) -> float:
                try:
                    return float(pr.get("price") or 0) or (float(pr.get("price_cents") or 0) / 100.0)
                except (TypeError, ValueError):
                    return 0.0
            _priced = [pr for pr in products if isinstance(pr, dict) and _pp(pr) > 0]
            _all_over = bool(_bmax and _priced and all(_pp(pr) > float(_bmax) for pr in _priced))
            _has_widen = any(isinstance(x, dict) and x.get("id") == "widen_budget" for x in next_questions)
            if _all_over and not _has_widen:
                next_questions = [{
                    "id": "widen_budget",
                    "text": "Nothing landed exactly in budget — widen it a little to see closer fits?",
                    "goal": "increase_match_space",
                    "options": [
                        {"id": "widen_small", "label": "Widen a little (+$200)", "value": "expand_budget:+200"},
                        {"id": "widen_medium", "label": "Widen more (+$400)", "value": "expand_budget:+400"},
                    ],
                }] + list(next_questions)
    except Exception:
        pass
    if not assistant_message and not products and next_questions:
        prompts = [f"- {q.get('text')}" for q in next_questions if isinstance(q, dict) and q.get("text")]
        assistant_message = "I could not find a confident in-catalog match yet. Try one of these refinements:\n" + "\n".join(prompts)

    clarification_only = bool(data.get("needs_disambiguation") and not products and next_questions)
    if clarification_only:
        aq_out = {"assistant_message": assistant_message}
    else:
        aq_out = apply_answer_quality(
            query=q,
            assistant_message=assistant_message,
            turn_intent=turn_intent,
            products=products,
            image_cv_signals=image_cv_signals_in if isinstance(image_cv_signals_in, dict) else {},
            has_image=has_image,
            buyer_persona=data.get("buyer_persona"),
            brand_name=None,
            bulk_budget=data.get("bulk_budget") if isinstance(data.get("bulk_budget"), dict) else None,
        )
    assistant_message = aq_out.get("assistant_message")
    # N6 prose citations, re-applied on the /chat path: recommend.suggest appends a "_Sources:_" line,
    # but chat re-derives the message through apply_answer_quality (which drops it). Re-append here on
    # the FINAL message so provenance reads in the chat text, matching the chips/Evidence tab.
    try:
        _ev = data.get("evidence") if isinstance(data, dict) else None
        _cites = [str(c.get("source") or "").replace("_", " ")
                  for c in ((_ev or {}).get("citations") or []) if c.get("source")]
        if _cites and assistant_message and "_Sources:" not in assistant_message:
            assistant_message = assistant_message.rstrip() + "\n\n_Sources: " + " / ".join(_cites[:4]) + "_"
    except Exception:
        pass
    aq_intent = aq_out.get("intent_decomposed") if isinstance(aq_out.get("intent_decomposed"), dict) else {}
    aq_template = aq_out.get("template_selected") if isinstance(aq_out.get("template_selected"), dict) else {}
    aq_coverage = aq_out.get("answer_coverage_scored") if isinstance(aq_out.get("answer_coverage_scored"), dict) else {}
    try:
        if decision_trace_id:
            log_trace_event(
                trace_id=decision_trace_id,
                event_type="intent_decomposed",
                source_type="agent",
                source_id="Copywriting_Agent",
                target_type="chat",
                target_id=None,
                payload=aq_intent,
            )
            log_trace_event(
                trace_id=decision_trace_id,
                event_type="template_selected",
                source_type="agent",
                source_id="Copywriting_Agent",
                target_type="chat",
                target_id=None,
                payload=aq_template,
            )
            log_trace_event(
                trace_id=decision_trace_id,
                event_type="answer_coverage_scored",
                source_type="agent",
                source_id="Copywriting_Agent",
                target_type="chat",
                target_id=None,
                payload=aq_coverage,
            )
    except Exception:
        pass

    copy_out = maybe_apply_copywriting(
        assistant_message=assistant_message,
        turn_intent=turn_intent,
        surface=copy_surface,
        requested_enabled=copywriting_requested,
        profile_id=copy_profile_id,
        inline_profile=copy_profile_inline,
        brand_name=brand_name,
    )
    assistant_message = copy_out.get("assistant_message")
    # HONEST REFUSAL survives every compose path: suggest() may refuse an out-of-range quantity
    # (99999/0/negative) — the note must reach the buyer even when chat rebuilds the message
    # (answer-quality templates, copywriting, no-match compose all run after suggest's own narration).
    _refusal = str(data.get("refusal_note") or "").strip()
    if _refusal and _refusal not in str(assistant_message or ""):
        assistant_message = f"{_refusal}\n\n{assistant_message}" if assistant_message else _refusal
    # PRE-SALES policy answer (StoreProfile policy_faq slot — store-written content, never invented):
    # a mixed ask ("gaming laptop… what warranty?") gets products PLUS the policy paragraph; a pure
    # policy question replaces the useless "no match" with the actual answer.
    try:
        from src.app.services.answer_quality import policy_faq_answer
        _pol = policy_faq_answer(q)
        if _pol:
            if products:
                assistant_message = f"{assistant_message}\n\n📋 {_pol}" if assistant_message else f"📋 {_pol}"
            else:
                assistant_message = f"📋 {_pol}"
    except Exception as _pol_exc:
        logger.debug("policy_faq compose failed: %s", _pol_exc)
    copy_meta = copy_out.get("meta") if isinstance(copy_out.get("meta"), dict) else {}
    try:
        if decision_trace_id and (bool(copy_meta.get("applied")) or bool(copywriting_requested)):
            log_trace_event(
                trace_id=decision_trace_id,
                event_type="copywriting",
                source_type="agent",
                source_id="Copywriting_Agent",
                target_type="chat",
                target_id=None,
                payload={
                    "applied": bool(copy_meta.get("applied")),
                    "mode": copy_meta.get("mode"),
                    "profile_id": copy_meta.get("profile_id"),
                    "tone": copy_meta.get("tone"),
                    "surface": copy_meta.get("surface"),
                    "cpu_cost": copy_meta.get("cpu_cost"),
                    "latency_ms": copy_meta.get("latency_ms"),
                    "reason": copy_meta.get("reason"),
                },
            )
        if decision_trace_id and bool(copy_meta.get("policy_gate_triggered")):
            log_trace_event(
                trace_id=decision_trace_id,
                event_type="copy_policy_gate",
                source_type="agent",
                source_id="Copywriting_Agent",
                target_type="chat",
                target_id=None,
                payload={
                    "action": "sanitize_claims",
                    "triggered": True,
                    "profile_id": copy_meta.get("profile_id"),
                },
            )
    except Exception:
        pass

    confidence = None
    try:
        # Use top normalized score as confidence proxy if present
        if results and isinstance(results[0].get("score_norm"), (int, float)):
            confidence = float(results[0]["score_norm"]) / 100.0
    except Exception:
        confidence = None

    # Persist search event for chat route (UI-friendly shape)
    try:
        semantic = (
            data.get("semantic_resolution")
            if isinstance(data.get("semantic_resolution"), dict) else {}
        )
        alignment = (
            data.get("catalog_alignment")
            if isinstance(data.get("catalog_alignment"), dict) else {}
        )
        concepts = [item for item in semantic.get("concepts") or [] if isinstance(item, dict)]
        unresolved = next(
            (str(item.get("text") or "") for item in concepts
             if str(item.get("status") or "unresolved") != "resolved"),
            None,
        )
        alignment_status = str(alignment.get("status") or "")
        qualification_map = {
            "exact_catalog_match": "exact",
            "qualified_catalog_match": "qualified",
            "no_exact_catalog_match": (
                "alternative" if alignment.get("alternatives") else "no_match"
            ),
            "unsupported": "no_match",
            "blocked": "blocked",
        }
        qualification_outcome = qualification_map.get(
            alignment_status,
            "blocked" if semantic.get("catalog_authority") == "blocked" else "unresolved",
        )
        lifecycle_stage = (
            "clarification_requested"
            if semantic.get("outcome") in {"clarify", "research", "rejected"}
            else "qualified_interest"
            if alignment_status in {"exact_catalog_match", "qualified_catalog_match", "no_exact_catalog_match"}
            else "search_interest"
        )
        semantic_evidence_rows = [
            item for item in semantic.get("evidence") or [] if isinstance(item, dict)
        ]
        evidence_refs = [
            str(item.get("citation_id")) for item in semantic_evidence_rows
            if item.get("citation_id")
        ]
        source_policy_status = (
            "approved"
            if semantic_evidence_rows and all(
                item.get("source_policy_status") == "approved"
                for item in semantic_evidence_rows
            )
            else "candidate_only" if semantic_evidence_rows else "not_evaluated"
        )
        active_case = (
            data.get("fulfillment_case")
            if isinstance(data.get("fulfillment_case"), dict) else {}
        )
        search_constraints = (
            data.get("constraints_used")
            if isinstance(data.get("constraints_used"), dict) else {}
        )
        requested_quantity = (
            search_constraints.get("quantity") or search_constraints.get("order_quantity")
        )
        inventory_snapshot = (
            data.get("inventory_snapshot")
            if isinstance(data.get("inventory_snapshot"), dict)
            else (data.get("procurement_context") or {}).get("inventory_snapshot")
            if isinstance(data.get("procurement_context"), dict)
            else None
        )
        resolved_sku = (
            alignment.get("resolved_sku")
            or alignment.get("sku")
            or semantic.get("resolved_sku")
        )
        log_search_event(
            uid=_resolve_uid(payload, request),
            query=q,
            filters=None,
            result_skus=[p.get("sku") for p in products],
            view_mode=view_mode,
            trace_id=decision_trace_id,
            session_id=str(payload.get("session_id") or "") or None,
            session_epoch=session_epoch,
            tenant_id=_request_tenant_id(request),
            case_id=str(active_case.get("case_id") or "") or None,
            requirement={
                "desired_outcome": semantic.get("desired_outcome"),
                "concepts": concepts,
                "constraints": search_constraints,
            },
            requested_quantity=requested_quantity,
            qualification_outcome=qualification_outcome,
            lifecycle_stage=lifecycle_stage,
            unresolved_concept=unresolved,
            resolved_sku=str(resolved_sku or "") or None,
            evidence_refs=evidence_refs,
            source_policy_status=source_policy_status,
            actor_dedup_class=str(data.get("actor_dedup_class") or "distinct_actor"),
            abuse_status=str(data.get("search_abuse_status") or "not_evaluated"),
            inventory_snapshot=inventory_snapshot,
            simulation_only=bool(data.get("simulation_only", False)),
        )
    except Exception as exc:
        logger.warning("search authority observation preparation failed: %s", exc)

    budget_viability = data.get("budget_viability") if isinstance(data.get("budget_viability"), dict) else {"status": "unknown"}
    use_case_analysis = data.get("use_case_analysis") if isinstance(data.get("use_case_analysis"), dict) else None
    constraints_used = data.get("constraints_used") if isinstance(data.get("constraints_used"), dict) else {}
    use_case_key = (
        (use_case_analysis.get("use_case_key") if isinstance(use_case_analysis, dict) else None)
        or constraints_used.get("use_case")
    )
    effective_budget = _budget_range_from_slots(
        _extract_confirmed_slots(query=q, response=data if isinstance(data, dict) else {}),
        q,
    )
    anchor_sections = _build_anchor_sections(
        images=images_array if isinstance(images_array, list) else [],
        products=products,
        query=q,
        budget=effective_budget,
        use_case_key=str(use_case_key) if use_case_key else None,
        buyer_persona=str(data.get("buyer_persona") or "") or None,
    )
    panel_intent = "SUPPORT_CLAIM" if bool(image_cv_signals_in.get("damage_detected")) else turn_intent
    _backend_right_panel = data.get("right_panel") if isinstance(data.get("right_panel"), dict) else None
    if isinstance(_backend_right_panel, dict) and anchor_sections:
        _backend_right_panel = dict(_backend_right_panel)
        _backend_right_panel["anchor_sections"] = anchor_sections
    _right_panel_contract = _backend_right_panel or _build_right_panel_contract(
        products=products,
        turn_intent=panel_intent,
        budget_viability=budget_viability,
        use_case_analysis=use_case_analysis,
        anchor_sections=anchor_sections,
    )
    try:
        if isinstance(_right_panel_contract, dict):
            _right_panel_contract["image_untrusted"] = bool(image_security_posture.get("image_untrusted"))
            _right_panel_contract["image_degraded_mode"] = bool(image_security_posture.get("image_degraded_mode"))
            _right_panel_contract["security_route"] = str(image_security_posture.get("route") or "allow")
            if image_security_posture.get("warning_message"):
                _right_panel_contract["security_summary"] = str(image_security_posture.get("warning_message"))
    except Exception:
        pass
    try:
        if decision_trace_id:
            log_trace_event(
                trace_id=decision_trace_id,
                event_type="right_panel_anchor_sections",
                source_type="agent",
                source_id="Candidate_Retrieval_Agent",
                target_type="ui",
                target_id="right_panel",
                payload={
                    "count": len(anchor_sections),
                    "anchors": [
                        {
                            "anchor_id": str(s.get("anchor_id")),
                            "brand": ((s.get("anchor_hint") or {}).get("brand") if isinstance(s.get("anchor_hint"), dict) else None),
                            "top_skus": [str((p or {}).get("sku") or "") for p in (s.get("top_products") or [])[:3]],
                        }
                        for s in anchor_sections[:6]
                    ],
                    "products_summary": [
                        {
                            "sku": p.get("sku"),
                            "name": p.get("name"),
                            "score_norm": p.get("score_norm"),
                            "reasons": (p.get("why") or [])[:3],
                            "reason_codes": (p.get("reason_codes") or [])[:3],
                            "price": p.get("price"),
                        }
                        for p in (products or [])[:8]
                        if isinstance(p, dict)
                    ],
                    "explanation": (
                        data.get("explanation")
                        if isinstance(data.get("explanation"), dict) else None
                    ),
                    "delivery_feasibility": (
                        data.get("delivery_feasibility")
                        if isinstance(data.get("delivery_feasibility"), dict) else None
                    ),
                    "human_escalation": (
                        data.get("human_escalation")
                        if isinstance(data.get("human_escalation"), dict) else None
                    ),
                    "right_panel_contract": _right_panel_contract,
                },
            )
    except Exception:
        pass

    # ── P0 multi-intent planner (flag-gated default-OFF) ─────────────────────────────────────────────
    # A mixed buyer turn — "actually make it 15, and what headsets + hard drives for $1200 for those" —
    # must (a) KEEP the chosen laptop, (b) change ITS quantity, and (c) source the new categories under the
    # SCOPED budget only. plan_live decomposes the turn against the live cart, fans out per new category, and
    # RE-CHECKS the assembled plan adversarially before we surface it. Additive: it attaches `multi_intent`
    # (with needs_confirmation so money/qty is confirmed, never guessed); it never mutates products here.
    multi_intent: Optional[Dict[str, Any]] = None
    try:
        _mi_on = str(os.getenv("MULTI_INTENT_PLANNER_ENABLED", "")).strip().lower() in ("1", "true", "yes", "on")
        if not _mi_on:
            try:
                from src.app.feature_flags import get_flags as _get_flags
                _mi_on = bool(_get_flags().get("MULTI_INTENT_PLANNER_ENABLED", False))
            except Exception:
                _mi_on = False
        if _mi_on and turn_intent not in ("EXPLAIN", "SUPPORT_CLAIM"):
            from src.app.services.multi_intent_live import plan_live
            multi_intent = plan_live(str(q or ""), str(uid), fallback_prior_skus=_prior_turn_shortlist or None)
    except Exception as _mi_exc:
        # Non-silent: attach the failure to the response instead of crashing the turn or hiding it.
        multi_intent = {"warnings": [f"multi_intent planner error: {str(_mi_exc)[:120]}"],
                        "needs_confirmation": True}

    # W3: off-catalog gate answers pass through UNTOUCHED — chat's budget-band prepends and
    # message recomposition would bury the category honesty under laptop framing.
    if isinstance(data, dict) and data.get("off_catalog"):
        assistant_message = data.get("assistant_message") or assistant_message
        products = []

    response_confirmed_slots = dict(confirmed_slots or {})
    response_confirmed_slots.update(
        _extract_confirmed_slots(
            query=q,
            response=data if isinstance(data, dict) else {},
        )
    )
    routed_decision = (
        data.get("decision") if isinstance(data.get("decision"), dict) else {}
    )
    routed_clarification_relation = str(
        routed_decision.get("clarification_relation") or "none"
    ).strip().lower()
    if pending_clarification and routed_clarification_relation in {"answer", "supersede"}:
        pending_clarification_consumed = True
    elif pending_clarification and routed_clarification_relation == "interrupt":
        pending_clarification_suspended = True

    semantic_resolution = (
        data.get("semantic_resolution")
        if isinstance(data.get("semantic_resolution"), dict)
        else {}
    )
    provisional_catalog_authority = (
        data.get("provisional_catalog_authority")
        if isinstance(data.get("provisional_catalog_authority"), dict)
        else {}
    )
    semantic_catalog_blocked = (
        str(semantic_resolution.get("catalog_authority") or "").strip().lower()
        == "blocked"
        and str(provisional_catalog_authority.get("status") or "").strip().lower()
        != "allowed"
    )
    routed_subject_action = str(
        routed_decision.get("subject_action") or "uncertain"
    ).strip().lower()
    literal_buyer_turn = str(submitted_query or "").strip()
    explicit_replacement_turn = bool(re.search(
        r"\b(?:actually|instead|rather\s+than|change(?:d)?\s+(?:my|the)\s+(?:mind|request)|"
        r"new\s+(?:request|search)|what\s+i\s+(?:really\s+)?need)\b",
        literal_buyer_turn,
        re.IGNORECASE,
    ))
    named_workload_replacement = bool(
        explicit_replacement_turn
        and re.search(
            r"\b(?:simulate|simulation|software|platform|application|program|workload|run)\b",
            literal_buyer_turn,
            re.IGNORECASE,
        )
        and re.search(
            r"\b[A-Z][a-z][A-Za-z0-9.+-]*(?:\s+[A-Z0-9][A-Za-z0-9.+-]*)+\b",
            literal_buyer_turn,
        )
    )
    deterministic_workload_replacement = deterministic_named_workload_switch(
        literal_buyer_turn,
    )
    subject_switch_receipt: Dict[str, Any] | None = None
    active_case_subject_replaced = bool(
        active_shopping_case_id
        and (
            named_workload_replacement
            or deterministic_workload_replacement
            or (
                not case_commercial_obligations
                and (
                    routed_subject_action == "switch"
                    or routed_clarification_relation == "supersede"
                    or (
                        semantic_catalog_blocked
                        and explicit_replacement_turn
                    )
                )
            )
        )
    )
    if active_case_subject_replaced:
        # The literal turn, rather than clarification-expanded prose, is the root
        # of the replacement case. It must not inherit the old product node,
        # purpose, research consent, or visible decision trace.
        prior_case_id = active_shopping_case_id
        prior_case_purpose = active_shopping_case_purpose
        active_shopping_case_id = None
        active_shopping_case_purpose = None
        # Consent and observations are scoped to the superseded subject.  Only
        # an authorization made explicitly on this same replacement turn may
        # cross the boundary; budget and other freshly parsed shared buyer
        # constraints remain in response_confirmed_slots.
        from src.app.services.subject_switch_boundary import clear_subject_scoped_state
        subject_switch_receipt = clear_subject_scoped_state(
            params,
            retain_same_turn_consent=turn_research_authorized,
        )
        pending_clarification_consumed = bool(pending_clarification)
        pending_clarification_suspended = False
        routed_clarification_relation = "supersede"
        routed_decision = dict(routed_decision)
        routed_decision.update({
            "subject_action": "switch",
            "clarification_relation": "supersede",
            "node_handle": None,
            "node_path": None,
            "use_cases": [],
            "prior_shortlist": [],
            "subject_from_session": False,
        })
        try:
            db.execute(sql_text(
                "UPDATE shopping_cases SET status='superseded',updated_at=CURRENT_TIMESTAMP "
                "WHERE tenant_id=:tenant_id AND case_id=:case_id AND status='active'"
            ), {"tenant_id": tenant_id, "case_id": prior_case_id})
            db.commit()
            log_trace_event(
                trace_id=str(prior_case_id).removeprefix("sc-"),
                event_type="shopping_case_subject_superseded",
                source_type="stage",
                source_id="Conversation_Subject_Boundary",
                target_type="shopping_case",
                target_id=str(prior_case_id),
                tenant_id=tenant_id,
                payload={
                    "prior_purpose": prior_case_purpose,
                    "replacement_turn": literal_buyer_turn[:500],
                    "state_boundary": subject_switch_receipt,
                    "commercial_authority": "none",
                },
            )
        except Exception:
            db.rollback()
            logger.warning("shopping-case subject supersession audit failed", exc_info=True)
    response_slots_for_output = dict(response_confirmed_slots)
    same_case_commercial_interruption = bool(
        active_shopping_case_id and case_commercial_obligations
    )
    if (
        semantic_catalog_blocked
        and data.get("requested_quantity") is None
        and not same_case_commercial_interruption
    ):
        # Accepted commercial state belongs to the suspended prior subject. Do not project
        # its quantity/budget into a new unresolved subject: the storefront uses these fields
        # to pin procurement panels and trace identity to the current turn.
        for key in (
            "order_quantity", "budget_scope", "total_budget_cents",
            "budget_min", "budget_max",
        ):
            response_slots_for_output.pop(key, None)

    # Buyer-provided OCR/text can propose requirement claims, but it is never
    # qualification authority. Keep the proposal at the chat edge so the UI can
    # ask the buyer to review it before any requirement compiler or cart path
    # consumes it. Suspicious OCR remains quarantined by the image security gate.
    buyer_requirement_claims: List[Dict[str, Any]] = []
    buyer_requirement_review_required = False
    buyer_requirement_proposal: Dict[str, Any] | None = None
    if (
        not bool(image_security_posture.get("image_untrusted"))
        and isinstance(image_ocr_text_in, str)
        and image_ocr_text_in.strip()
    ):
        try:
            from src.app.services.buyer_requirement_evidence import (
                extract_buyer_requirement_claims,
            )

            source_reference = str(image_hash_in or decision_trace_id or "buyer-upload")[:160]
            extracted_claims = extract_buyer_requirement_claims(
                image_ocr_text_in[:20000],
                source_reference=source_reference,
            )
            buyer_requirement_claims = [claim.model_dump() for claim in extracted_claims]
            buyer_requirement_review_required = bool(buyer_requirement_claims)
            if buyer_requirement_claims:
                # Persist the review boundary now so browser acceptance can be
                # case-scoped and version checked. This records no qualification
                # or cart authority.
                from datetime import datetime, timezone
                import uuid as _uuid
                from sqlalchemy import select as _select
                from src.app.models.orm import RequirementProposal, ShoppingCase

                _tenant_id = _request_tenant_id(request)
                _uid = str((payload or {}).get("uid") or "guest")[:200]
                _requested_case_id = str((payload or {}).get("shopping_case_id") or "").strip()[:200]
                _case_id = _requested_case_id or str(
                    decision_trace_id or f"case-{_uuid.uuid4().hex}"
                )[:200]
                _now = datetime.now(timezone.utc)
                _case = db.execute(_select(ShoppingCase).where(
                    ShoppingCase.tenant_id == _tenant_id,
                    ShoppingCase.case_id == _case_id,
                )).scalar_one_or_none()
                if _requested_case_id and _case is None:
                    raise HTTPException(status_code=409, detail="shopping_case_not_found")
                if _case is not None and _case.uid != _uid:
                    raise HTTPException(status_code=403, detail="shopping_case_not_owned")
                if _case is None:
                    _case = ShoppingCase(
                        case_id=_case_id, tenant_id=_tenant_id, uid=_uid,
                        status="active", retained_purpose=str(q or "")[:500],
                        created_at=_now, updated_at=_now,
                    )
                    db.add(_case)
                _proposal_id = "rp-" + _uuid.uuid4().hex
                db.add(RequirementProposal(
                    proposal_id=_proposal_id, case_id=_case_id,
                    tenant_id=_tenant_id, uid=_uid, version=1,
                    status="pending_review", source_reference=source_reference,
                    claims_json=buyer_requirement_claims,
                    created_at=_now, updated_at=_now,
                ))
                db.commit()
                buyer_requirement_proposal = {
                    "case_id": _case_id, "proposal_id": _proposal_id,
                    "proposal_version": 1, "status": "pending_review",
                    "cart_mutation": "not_authorized",
                }
            _requirement_trace_id = (
                str(buyer_requirement_proposal.get("case_id") or "").removeprefix("sc-")
                if buyer_requirement_proposal else str(decision_trace_id or "")
            )
            if _requirement_trace_id and buyer_requirement_claims:
                log_trace_event(
                    trace_id=_requirement_trace_id,
                    event_type="buyer_requirement_claims_extracted",
                    source_type="stage",
                    source_id="Buyer_Requirement_Evidence",
                    target_type="ui",
                    target_id="requirement_review",
                    payload={
                        "status": "provisional",
                        "authority_status": "unverified",
                        "qualification_authority": "none",
                        "claim_count": len(buyer_requirement_claims),
                        "attributes": sorted({
                            str(claim.get("attribute") or "")
                            for claim in buyer_requirement_claims
                            if claim.get("attribute")
                        }),
                    },
                )
        except Exception as exc:
            logger.debug("buyer requirement extraction skipped: %s", exc)

    if buyer_requirement_claims:
        # The dominant obligation on an upload turn is claim review, not the
        # pre-existing semantic refusal. Product fit remains conditional until
        # the buyer accepts a subset and corroboration runs where needed.
        assistant_message = (
            f"I extracted {len(buyer_requirement_claims)} provisional requirement claims "
            "from your upload. Review or correct them below. I have not qualified a product, "
            "authorized external research, or changed your cart."
        )
        next_questions = []

    # Unresolved workload semantics block qualification, not provisional catalog
    # exploration. This path calls no external provider and grants no cart authority.
    ambiguity_exploration: Dict[str, Any] | None = None
    ambiguous_product_shelves: Dict[str, Any] | None = None
    if preflight_workload_evidence:
        # Canonical local identity data is deterministic and must not disappear
        # when the live router varies its output. Merge metadata into the
        # recommendation-owned authorization envelope without changing that
        # envelope's product or commerce decision.
        projected_authorization = dict(
            data.get("workload_authorization")
            if isinstance(data.get("workload_authorization"), dict) else {}
        )
        projected_items = [
            dict(item) for item in list(projected_authorization.get("evidence") or [])
            if isinstance(item, dict)
        ]
        for canonical_item in preflight_workload_evidence:
            canonical_key = str(
                canonical_item.get("app_id")
                or canonical_item.get("canonical_title")
                or canonical_item.get("resolved_name")
                or ""
            ).strip().lower()
            match_index = next((
                index for index, item in enumerate(projected_items)
                if canonical_key and canonical_key in {
                    str(item.get("app_id") or "").strip().lower(),
                    str(item.get("canonical_title") or "").strip().lower(),
                    str(item.get("resolved_name") or "").strip().lower(),
                }
            ), None)
            if match_index is None:
                projected_items.append(dict(canonical_item))
            else:
                projected_items[match_index] = {
                    **projected_items[match_index],
                    **{
                        key: value for key, value in canonical_item.items()
                        if value not in (None, "", [], {})
                    },
                }
        projected_authorization["evidence"] = projected_items
        projected_authorization.setdefault("status", "evidence_resolved_catalog_pending")
        projected_authorization.setdefault("reason", "canonical_identity_preflight")
        data["workload_authorization"] = projected_authorization
    _workload_authorization = (
        data.get("workload_authorization")
        if isinstance(data.get("workload_authorization"), dict) else {}
    )
    _workload_material_blocked = (
        str(_workload_authorization.get("status") or "").strip().lower() == "blocked"
    )
    _case_research_plan = None
    try:
        from src.app.services.case_research_plan import build_case_research_plan

        _case_research_plan = build_case_research_plan(
            active_shopping_case_purpose or str(submitted_query or q or "")[:500]
        )
    except Exception as exc:
        logger.debug("case research-plan projection skipped: %s", exc)
    provisional_exploration_needed = bool(
        semantic_catalog_blocked
        or _workload_material_blocked
        or (
            turn_intent == "SEARCH"
            and not products
            and not bool(data.get("off_catalog"))
        )
        or (
            _case_research_plan is not None
            and turn_intent not in {
                "EXPLAIN", "SUPPORT_CLAIM", "POLICY_QUESTION", "CART_MUTATION",
            }
        )
    )
    if provisional_exploration_needed and _case_research_plan is None:
        try:
            _case_research_plan = build_case_research_plan(
                active_shopping_case_purpose or str(submitted_query or q or "")[:500],
                allow_open_world=True,
            )
        except Exception as exc:
            logger.debug("open-world research-plan projection skipped: %s", exc)
    if provisional_exploration_needed and not buyer_requirement_claims:
        try:
            from src.app.services.accepted_catalog_projection import project_accepted_catalog

            _identity_candidates = []
            for item in list(_workload_authorization.get("evidence") or [])[:3]:
                if not isinstance(item, dict) or not str(
                    item.get("status") or ""
                ).startswith("identity_resolved"):
                    continue
                identity = (
                    item.get("identity_resolution")
                    if isinstance(item.get("identity_resolution"), dict) else {}
                )
                _identity_candidates.append({
                    "requested_name": item.get("requested_name"),
                    "resolved_name": item.get("resolved_name") or identity.get("resolved_name"),
                    "source": item.get("source") or identity.get("source"),
                    "source_url": item.get("source_url") or identity.get("source_url"),
                    "confidence": item.get("confidence") or identity.get("confidence"),
                    "status": item.get("status"),
                    "requirements_status": "incomplete",
                    "canonical_title": item.get("canonical_title") or item.get("resolved_name"),
                    "publisher": item.get("publisher"),
                    "app_id": item.get("app_id") or item.get("source_record_id"),
                    "release_state": item.get("release_state"),
                    "release_date": item.get("release_date"),
                    "requirements_completeness": item.get("requirements_completeness"),
                })

            _semantic_hypotheses = list(semantic_resolution.get("workload_hypotheses") or [])[:3]
            if not _semantic_hypotheses and _case_research_plan is not None:
                _semantic_hypotheses = [
                    {
                        "hypothesis_id": item.hypothesis_id,
                        "label": item.label,
                        "authority": item.authority,
                    }
                    for item in _case_research_plan.hypotheses
                ]
            _retained_case_purpose = active_shopping_case_purpose or str(submitted_query or q or "")[:500]
            _projection = project_accepted_catalog(
                db, accepted_claims=[], desired_outcome=_retained_case_purpose,
                tenant_id=_request_tenant_id(request),
                requested_quantity=(
                    int(data["requested_quantity"])
                    if isinstance(data.get("requested_quantity"), int)
                    and not isinstance(data.get("requested_quantity"), bool)
                    and int(data["requested_quantity"]) > 0
                    else None
                ),
                hypothesis_labels={
                    str(item.get("hypothesis_id") or f"hypothesis_{index + 1}"): str(
                        item.get("label") or item.get("hypothesis_id") or f"Interpretation {index + 1}"
                    )
                    for index, item in enumerate(_semantic_hypotheses)
                    if isinstance(item, dict)
                },
            )
            ambiguous_product_shelves = _projection.model_dump(mode="json")
            if (
                semantic_catalog_blocked
                or active_case_subject_replaced
                or (
                    _case_research_plan is not None
                    and _case_research_plan.publisher_status == "unresolved"
                )
            ):
                # Discovery has not established even the governing publisher yet.
                # Showing architecture-wide products here looks like a recommendation
                # and creates the unrelated 12-card wall reported in the live UI.
                ambiguous_product_shelves = None
            _questions = [
                item for item in list(next_questions or [])
                if isinstance(item, dict)
                and str(item.get("text") or item.get("question") or "").strip()
            ]
            ambiguity_exploration = {
                "schema_version": "ambiguity-exploration-v1",
                "case_id": (
                    active_shopping_case_id
                    or (f"sc-{decision_trace_id}" if decision_trace_id else None)
                ),
                "trace_id": decision_trace_id,
                "retained_purpose": _retained_case_purpose,
                "status": "context_only" if _identity_candidates else "provisional",
                "interpretations": _semantic_hypotheses,
                "next_question": (
                    # A generic catalog budget question must not displace the
                    # evidence question that resolves an open-world suitability
                    # gap.  The durable plan owns that material question.
                    ({"id": "research_scope", "text": _case_research_plan.next_question}
                     if _case_research_plan is not None
                     and _case_research_plan.publisher_status == "unresolved"
                     and not _identity_candidates
                     else _questions[0]) if _questions
                    else ({"id": "research_scope", "text": _case_research_plan.next_question}
                          if _case_research_plan is not None else None)
                ),
                "research_choices": (["research_approved_sources"] if _case_research_plan else []) + [
                    "upload_requirements", "enter_specifications", "continue_provisionally",
                ],
                "execution": (
                    "provider_lookup_completed" if _identity_candidates
                    else "local_exploration_completed"
                ),
                "evidence": "identity_only" if _identity_candidates else "material_gaps",
                "decision": "clarification_required" if _workload_material_blocked else "exploration_allowed",
                "cart_authority": "none",
                "provider_accounting": {
                    "external_calls": sum(
                        1 for item in list(_workload_authorization.get("evidence") or [])
                        if isinstance(item, dict)
                        for attempt in list(item.get("provider_attempts") or [])
                        if isinstance(attempt, dict) and bool(attempt.get("allow_live"))
                    ),
                    "paid_calls": 0,
                },
                "research_plan_id": (
                    _case_research_plan.plan_id if _case_research_plan is not None else None
                ),
                "ambiguity_objects": (
                    [item.model_dump(mode="json") for item in _case_research_plan.ambiguities]
                    if _case_research_plan is not None else []
                ),
                "research_obligations": (
                    [item.model_dump(mode="json") for item in _case_research_plan.obligations]
                    if _case_research_plan is not None else []
                ),
                "source_candidate_ids": (
                    list(_case_research_plan.source_candidate_ids)
                    if _case_research_plan is not None else []
                ),
                "identity_candidates": _identity_candidates,
            }
            if active_case_subject_replaced and _case_research_plan is not None:
                products = []
                material_question_text = str(
                    (ambiguity_exploration.get("next_question") or {}).get("text") or ""
                ).strip()
                named_workload = re.search(
                    r"\b([A-Z][a-z][A-Za-z0-9.+-]*(?:\s+[A-Z0-9][A-Za-z0-9.+-]*){1,4})\b",
                    literal_buyer_turn,
                )
                workload_label = (
                    named_workload.group(1) if named_workload else "this newly named workload"
                )
                assistant_message = (
                    "I treated this as a new workload and cleared the earlier gaming assumptions. "
                    "Before I recommend hardware, I need current authoritative requirements for "
                    f"{workload_label}."
                    + (f" {material_question_text}" if material_question_text else "")
                )
            if not active_shopping_case_id and ambiguity_exploration.get("case_id"):
                # The legacy chat path can discover ambiguity after the fast
                # interpretation endpoint returned 204. Materialize the same
                # durable case boundary before the next buyer turn so follow-up
                # quantity/deadline/supplier acts cannot float free of purpose.
                from datetime import datetime, timezone
                from src.app.models.orm import ShoppingCase

                generated_case_id = str(ambiguity_exploration["case_id"])[:200]
                existing_case = db.execute(sql_text(
                    "SELECT 1 FROM shopping_cases "
                    "WHERE tenant_id=:tenant_id AND case_id=:case_id LIMIT 1"
                ), {
                    "tenant_id": tenant_id,
                    "case_id": generated_case_id,
                }).first()
                if existing_case is None:
                    now = datetime.now(timezone.utc)
                    db.add(ShoppingCase(
                        case_id=generated_case_id,
                        tenant_id=tenant_id,
                        uid=str(uid or "guest")[:200],
                        status="active",
                        retained_purpose=_retained_case_purpose,
                        created_at=now,
                        updated_at=now,
                    ))
                    db.commit()
                active_shopping_case_id = generated_case_id
                active_shopping_case_purpose = _retained_case_purpose
            if decision_trace_id:
                log_trace_event(
                    trace_id=decision_trace_id,
                    event_type="ambiguity_exploration_projected",
                    source_type="stage",
                    source_id="Ambiguous_Catalog_Exploration",
                    target_type="ui",
                    target_id="research_fit_panel",
                    payload={
                        **ambiguity_exploration,
                        "shelf_ids": [shelf.shelf_id for shelf in _projection.shelves],
                        "qualification_authority": "none",
                        "commercial_authority": "none",
                    },
                )
        except Exception as exc:
            logger.debug("provisional ambiguity projection skipped: %s", exc)

    # Covered local catalogue exploration still needs a durable case boundary:
    # subsequent quantity, deadline, selection, swap, or supplier turns amend
    # this purpose instead of floating as unrelated chat prose. Ambiguity and
    # research projections remain separate and retain their stricter contract.
    if not active_shopping_case_id and products:
        try:
            from datetime import datetime, timezone
            import uuid as _uuid
            from src.app.models.orm import ShoppingCase

            created_case_id = "sc-" + str(
                decision_trace_id or _uuid.uuid4().hex
            ).removeprefix("sc-")[:196]
            existing_case = db.execute(sql_text(
                "SELECT 1 FROM shopping_cases "
                "WHERE tenant_id=:tenant_id AND case_id=:case_id LIMIT 1"
            ), {
                "tenant_id": tenant_id,
                "case_id": created_case_id,
            }).first()
            if existing_case is None:
                now = datetime.now(timezone.utc)
                db.add(ShoppingCase(
                    case_id=created_case_id,
                    tenant_id=tenant_id,
                    uid=str(uid or "guest")[:200],
                    status="active",
                    retained_purpose=str(submitted_query or q or "")[:500],
                    created_at=now,
                    updated_at=now,
                ))
                db.commit()
            active_shopping_case_id = created_case_id
            active_shopping_case_purpose = str(submitted_query or q or "")[:500]
        except Exception:
            logger.warning(
                "covered catalog shopping-case creation failed; preserving response",
                exc_info=True,
            )

    durable_interpretation_job: Dict[str, Any] | None = None
    if (
        active_shopping_case_id
        and _case_research_plan is not None
        and _case_research_plan.publisher_status == "unresolved"
    ):
        try:
            from sqlalchemy import select as _select
            from src.app.models.orm import ShoppingCase
            from src.app.services.shopping_case_interpretation_jobs import (
                schedule_case_interpretation,
            )

            durable_case = db.execute(_select(ShoppingCase).where(
                ShoppingCase.tenant_id == tenant_id,
                ShoppingCase.case_id == active_shopping_case_id,
            )).scalar_one()
            durable_interpretation_job = schedule_case_interpretation(
                db, case=durable_case, plan=_case_research_plan,
            )
            if ambiguity_exploration is not None:
                ambiguity_exploration["interpretation_job"] = durable_interpretation_job
        except Exception as exc:
            logger.warning(
                "durable open-world interpretation scheduling failed; "
                "preserving deterministic exploration: %s",
                repr(exc)[:160],
            )

    # URL intake owns a durable case even when the workload itself resolved and
    # catalogue ranking returned no products. Without this final case boundary,
    # a first-turn rejected URL could be silently omitted from the response.
    if submitted_source_url and not active_shopping_case_id:
        try:
            from datetime import datetime, timezone
            import uuid as _uuid
            from src.app.models.orm import ShoppingCase

            source_case_id = "sc-" + str(
                decision_trace_id or _uuid.uuid4().hex
            ).removeprefix("sc-")[:196]
            existing_case = db.execute(sql_text(
                "SELECT 1 FROM shopping_cases "
                "WHERE tenant_id=:tenant_id AND case_id=:case_id LIMIT 1"
            ), {"tenant_id": tenant_id, "case_id": source_case_id}).first()
            if existing_case is None:
                now = datetime.now(timezone.utc)
                db.add(ShoppingCase(
                    case_id=source_case_id,
                    tenant_id=tenant_id,
                    uid=str(uid or "guest")[:200],
                    status="active",
                    retained_purpose=str(submitted_query or q or "")[:500],
                    created_at=now,
                    updated_at=now,
                ))
                db.commit()
            active_shopping_case_id = source_case_id
            active_shopping_case_purpose = str(submitted_query or q or "")[:500]
        except Exception:
            db.rollback()
            logger.warning("URL-owned shopping-case creation failed", exc_info=True)

    # A pasted URL is resolved inside the same chat operation that owns the new
    # or superseding case. This guarantees every accepted or rejected URL emits
    # a case-bound intake/security receipt; the browser never has to race a
    # second request against case creation.
    source_intake_result: Dict[str, Any] | None = None
    if submitted_source_url and active_shopping_case_id:
        try:
            from src.app.routers.shopping_cases import (
                ResolveBuyerEvidenceSourceRequest,
                _resolve_case_evidence_source_with_db,
            )

            source_intake_result = await _resolve_case_evidence_source_with_db(
                active_shopping_case_id,
                ResolveBuyerEvidenceSourceRequest(
                    uid=uid,
                    source_url=submitted_source_url,
                    research_authorized=bool(params.get("external_research_consent")),
                    authorization_basis=turn_research_authorization_basis,
                ),
                x_tenant_id=tenant_id,
                db=db,
            )
            source_status = str(
                (source_intake_result.get("resolution") or {}).get("status") or ""
            ).lower()
            research_status = str(source_intake_result.get("research_status") or "").lower()
            if source_status != "resolved":
                reason = str(
                    (source_intake_result.get("resolution") or {}).get("reason")
                    or "source_not_approved"
                )
                assistant_message = (
                    "I inspected the submitted link before using it, but it is not an "
                    f"enrolled canonical source ({reason}). I did not fetch its arbitrary "
                    "path or use its claims. The source-safety receipt is available in Decision Trace."
                )
                products = []
                ambiguous_product_shelves = None
            elif research_status == "not_authorized":
                assistant_message = (
                    "I safely matched the submitted link to a reviewed canonical publisher "
                    "source. I did not fetch it or use its claims because external research "
                    "is not authorized for this turn."
                )
                products = []
                ambiguous_product_shelves = None
            else:
                source_claims = list(source_intake_result.get("claims") or [])
                buyer_requirement_claims = source_claims
                buyer_requirement_review_required = bool(source_claims)
                buyer_requirement_proposal = source_intake_result.get(
                    "buyer_requirement_proposal"
                )
                if isinstance(source_intake_result.get("product_shelves"), dict):
                    ambiguous_product_shelves = source_intake_result["product_shelves"]
                evidence_outcome = str(
                    source_intake_result.get("evidence_outcome") or "unresolved"
                )
                if ambiguity_exploration is not None:
                    ambiguity_exploration["status"] = (
                        "researched" if evidence_outcome == "product_requirements"
                        else "context_only" if evidence_outcome == "context_only"
                        else "unresolved"
                    )
                    ambiguity_exploration["canonical_truth"] = source_intake_result.get(
                        "canonical_truth"
                    )
                    ambiguity_exploration["source_intake_certificate"] = (
                        source_intake_result.get("source_intake_certificate")
                    )
                assistant_message = (
                    f"I safely fetched the reviewed canonical publisher source and extracted "
                    f"{len(source_claims)} cited requirement claims. "
                    + (
                        "Review them below; they remain provisional until policy approval."
                        if source_claims else
                        "It did not establish product requirements, so product fit remains blocked."
                    )
                    + " No cart or supplier action was authorized."
                )
                products = []
        except Exception as exc:
            logger.warning("atomic buyer source intake failed closed", exc_info=True)
            source_intake_result = {
                "schema_version": "buyer-evidence-source-resolution-v1",
                "case_id": active_shopping_case_id,
                "resolution": {
                    "status": "invalid",
                    "reason": "governed_source_intake_failed_closed",
                },
                "research_status": "failed_closed",
                "provider_accounting": {"external_calls": 0, "paid_calls": 0},
                "source_intake_certificate": {
                    "schema_version": "buyer-source-intake-certificate-v1",
                    "case_id": active_shopping_case_id,
                    "resolution": {
                        "status": "invalid",
                        "reason": "governed_source_intake_failed_closed",
                    },
                    "security": {
                        "status": "blocked",
                        "url_syntax": "unresolved",
                        "publisher_authority": "unresolved",
                        "content_trust": "not_observed",
                        "canonical_fetch_eligible": False,
                        "arbitrary_submitted_path_fetch_allowed": False,
                    },
                    "execution": {"network_execution": False, "external_calls": 0, "paid_calls": 0},
                    "claim_compilation": {"status": "not_executed", "accepted": 0, "rejected": 0, "unresolved": 1},
                    "decision_effect": {"product_fit": "blocked", "cart_authority": "none", "supplier_authority": "none"},
                },
            }
            if ambiguity_exploration is not None:
                ambiguity_exploration["source_intake_certificate"] = (
                    source_intake_result["source_intake_certificate"]
                )
            assistant_message = (
                "I isolated the submitted link, but its governed source-intake operation "
                "failed closed. I did not fetch the submitted path, use its claims, or "
                "qualify a product."
            )
            products = []
            ambiguous_product_shelves = None

    out = {
        "products": products,
        "view_mode": view_mode,
        "confidence": confidence,
        "decision_trace_id": decision_trace_id,
        "trace_id": decision_trace_id,
        "assistant_message": assistant_message,
        "next_questions": next_questions,
        # P0 multi-intent plan (present only on a genuine mixed turn; None otherwise). Carries the scoped
        # new-line picks + adversarial verdict + needs_confirmation so the UI confirms qty/budget, not guesses.
        "multi_intent": multi_intent,
        "shopping_case_obligations": case_commercial_obligations,
        "shopping_case_id": active_shopping_case_id or None,
        "shopping_case_retained_purpose": active_shopping_case_purpose or None,
        "shopping_case_revision": (
            durable_interpretation_job.get("case_revision")
            if durable_interpretation_job else None
        ),
        "interpretation_job": durable_interpretation_job,
        "needs_disambiguation": False if turn_intent == "POLICY_QUESTION" else bool(
            data.get("needs_disambiguation") or (not products and next_questions)
        ),
        "nqe_selection_applied": data.get("nqe_selection_applied") or {},
        "confirmed_slots": response_slots_for_output,
        "llm_model": data.get("llm_model"),
        "model_tier": data.get("model_tier"),
        "response_provenance": (
            data.get("response_provenance")
            if isinstance(data.get("response_provenance"), dict) else None
        ),
        "complexity": complexity_result,
        "intent_routing": intent_routing_result,
        "turn_intent": turn_intent,
        "decision": routed_decision,
        "clarification_relation": routed_clarification_relation,
        # Preserve typed facade ownership at the HTTP/SSE edge. Without these fields the
        # browser and trace cannot prove whether V2 served, legacy delegated, or the request
        # failed boundedly in a V2-only pilot.
        "execution_mode": data.get("execution_mode"),
        "execution_lane": data.get("execution_lane") or turn_intent,
        "delegation_reason": data.get("delegation_reason"),
        "action_executed": bool(data.get("action_executed")),
        # Read-only case status/summary responses intentionally keep the buyer's
        # current product/cart/procurement panel in place. This typed contract
        # prevents an empty status response from looking like a fresh search.
        "preserve_current_view": bool(data.get("preserve_current_view")),
        "case_operation": data.get("case_operation"),
        "case_anchor": data.get("case_anchor") if isinstance(data.get("case_anchor"), dict) else None,
        "state_changed": data.get("state_changed"),
        # Server-hydrated case context is returned even when a response branch
        # (for example a policy answer) does not project core extras itself.
        "procurement_case_state": (
            data.get("procurement_case_state")
            if isinstance(data.get("procurement_case_state"), dict)
            else canonical_case_snapshot or None
        ),
        "case_patch_application": (
            data.get("case_patch_application")
            if isinstance(data.get("case_patch_application"), dict) else None
        ),
        "constraints_used": (
            data.get("constraints_used")
            if isinstance(data.get("constraints_used"), dict) else {}
        ),
        # N1/N6 forward-through: the evidence orchestrator's block (legs/citations) is produced in
        # recommend.suggest but was DROPPED here — so the frontend (which hits /chat/query, not
        # /suggest) never saw it and the Evidence tab + Source chips stayed empty. Forward it.
        "evidence": data.get("evidence"),
        # Canonical V2 execution ontology.  Persisting this on the chat response lets the same
        # immutable trace prove model proposal, deterministic authorization, and stage execution.
        "execution_steps": data.get("execution_steps") or [],
        # Preserve phase-level latency through the chat edge. The storefront and replay harness
        # use this single payload to distinguish queue/load/prefill/decode from retrieval,
        # evidence, fulfillment preview, and final response shaping.
        "timing_breakdown": (
            data.get("timing_breakdown")
            if isinstance(data.get("timing_breakdown"), dict)
            else {}
        ),
        # Async narration handoff: when recommend ran in async/skip mode it returns the deterministic
        # grounded answer now + a job id for the richer LLM prose. Forward both so the storefront can
        # poll /api/v1/recommend/narration/{job_id} and replace the message in place (no blocking wait).
        "llm_summary_job_id": data.get("llm_summary_job_id"),
        "summary_pending": bool(data.get("summary_pending") or data.get("llm_summary_job_id")),
        # W3/W4 forward-through (2026-07-08): the off-catalog verdict and workload fit verdicts
        # are computed in recommend.suggest — without forwarding, the frontend (which hits
        # /chat/query, not /suggest) loses the comparison AGAIN.
        "off_catalog": data.get("off_catalog"),
        "workload_fit": data.get("workload_fit"),
        "semantic_resolution": (
            data.get("semantic_resolution")
            if isinstance(data.get("semantic_resolution"), dict) else None
        ),
        # Canonical V2 presentation contract. These fields must survive the chat edge or the
        # browser falls back to an unlabeled legacy-looking slate even when the core correctly
        # separated best-fit, stretch, and noncompliant alternatives.
        "shelf": data.get("shelf") if isinstance(data.get("shelf"), dict) else None,
        "capability": (
            data.get("capability") if isinstance(data.get("capability"), dict) else None
        ),
        "price_intent": (
            data.get("price_intent") if isinstance(data.get("price_intent"), dict) else None
        ),
        "slate_disposition": str(data.get("slate_disposition") or "replace"),
        "secondary_lanes": (
            data.get("secondary_lanes") if isinstance(data.get("secondary_lanes"), list) else []
        ),
        "explanation": (
            data.get("explanation") if isinstance(data.get("explanation"), dict) else None
        ),
        "delivery_feasibility": (
            data.get("delivery_feasibility")
            if isinstance(data.get("delivery_feasibility"), dict) else None
        ),
        "human_escalation": (
            data.get("human_escalation")
            if isinstance(data.get("human_escalation"), dict) else None
        ),
        "voice_used": bool(voice_transcript),
        "budget_viability": budget_viability,
        "use_case_analysis": use_case_analysis,
        "buyer_persona": data.get("buyer_persona"),
        # Phase-3 adaptive-storefront observability: forward the market-driven ranking adaptations (the
        # demand-aware sales-response nudge + experiment ranking nudge + storefront emphasis) so the frontend
        # and the Decision Trace can SHOW the governed adaptation ("why these moved", gate allow/deny). Each
        # is present only when its flag-gated lever ran; the products themselves are already re-ranked.
        # bulk-order intent: the parsed unit count so Add buttons land the conversation's qty, not 1.
        "requested_quantity": (
            data.get("requested_quantity")
            if data.get("requested_quantity") is not None
            else (
                None
                if semantic_catalog_blocked and not same_case_commercial_interruption
                else response_slots_for_output.get("order_quantity")
            )
        ),
        # Whole-order sizing is consequential UI state too.  The storefront must be able to
        # reject a stale/stretch product whose requested quantity would exceed the accepted
        # total instead of blindly carrying requested_quantity into the cart.
        "bulk_budget": data.get("bulk_budget") if isinstance(data.get("bulk_budget"), dict) else None,
        # Buyer-safe procurement projection from /recommend/suggest. The recommend
        # layer owns case creation/redaction; chat must preserve it so the storefront
        # can render the commitment gate instead of hiding a real shortfall.
        "availability": data.get("availability") if isinstance(data.get("availability"), dict) else None,
        "fulfillment_case": (
            data.get("fulfillment_case")
            if isinstance(data.get("fulfillment_case"), dict) and data.get("fulfillment_case", {}).get("case_id")
            else None
        ),
        # Buyer-facing bulk alternatives (partial/transfer/substitute/source/reduce) for an unmet bulk
        # request — pre-commitment, no order placed. Preserve so the right panel can offer real choices.
        "fulfillment_options": (
            data.get("fulfillment_options") if isinstance(data.get("fulfillment_options"), list) else None
        ),
        # multi-line mixed order → grouped sourcing cases (buyer-safe summary; supplier identity stays server-side)
        "order_group": (
            data.get("order_group") if isinstance(data.get("order_group"), dict) else None
        ),
        # FLUID-procurement preview (FULFILLMENT_DEFER_TO_CART): the sourcing split is PREVIEWED here
        # (no durable case); the durable case materializes at cart-confirmation. Buyer-safe (no supplier).
        "sourcing_intent": (
            data.get("sourcing_intent") if isinstance(data.get("sourcing_intent"), dict) else None
        ),
        "right_panel": _right_panel_contract,
        "copywriting": copy_meta,
        "security_risk": bool(image_security_posture.get("security_risk")),
        "analysis_degraded": bool(image_security_posture.get("analysis_degraded")),
        "analysis_pending": bool(image_security_posture.get("analysis_pending")),
        "image_untrusted": bool(image_security_posture.get("image_untrusted")),
        "image_degraded_mode": bool(image_security_posture.get("image_degraded_mode")),
        "chat_lockdown": bool(image_security_posture.get("chat_lockdown")),
        "needs_human_review": bool(image_security_posture.get("needs_human_review")),
        "security_route": str(image_security_posture.get("route") or "allow"),
        "buyer_requirement_claims": buyer_requirement_claims,
        "buyer_requirement_review_required": buyer_requirement_review_required,
        "buyer_requirement_proposal": buyer_requirement_proposal,
        "ambiguity_exploration": ambiguity_exploration,
        "product_shelves": ambiguous_product_shelves,
        "workload_authorization": (
            data.get("workload_authorization")
            if isinstance(data.get("workload_authorization"), dict) else None
        ),
        "execution_state_envelope": data.get("execution_state_envelope"),
        "control_faults": data.get("control_faults") if isinstance(data.get("control_faults"), list) else [],
        "subject_switch_boundary": subject_switch_receipt,
        "buyer_evidence_source_resolution": source_intake_result,
        "research_policy": turn_research_policy,
    }
    # Adaptive fields are evidence that a governed lever actually ran. Omitting them when
    # disabled is part of the API contract; emitting null makes clients and audits infer an
    # experiment surface exists even though no assignment or adaptation occurred.
    _include_adaptive_metadata(out, data)
    if isinstance(out.get("assistant_message"), str):
        out["assistant_message"] = ResponseNormalizer.polish_llm_text(
            str(out.get("assistant_message") or ""),
            query=q,
        )
    # ── Image-compromise warn-and-continue surface ───────────────────────────
    # Products still flow; we prepend a clear warning and attach the breach
    # assessment (IP/ASN/GeoIP + intent + repercussions + human-notified) so the
    # user knows the upload is under review and the SOC has the evidence.
    if bool(image_security_posture.get("security_risk")) or bool(image_security_posture.get("chat_lockdown")):
        _ba = breach_assessment if isinstance(breach_assessment, dict) else None
        # Only claim a product "in your photo" when one was actually recognised in-domain. An
        # off-domain / unrecognised upload must be narrated as text + sanitized image context — never
        # "based on the product in your photo" (the apple-image-on-gaming-query case exposed that as
        # factually wrong).
        if image_handling_mode == "sanitized_visual":
            # We kept the legitimate product recognition; only the QR/OCR/steg
            # channel was quarantined. Stay anchored on the recognised product.
            if recognized_image_label:
                _anchor = (
                    f"I still recognised {recognized_image_label} in the photo, so these "
                    f"recommendations are anchored to that. Let me know if I read the product wrong."
                )
            else:
                _anchor = (
                    "I couldn't confidently identify a product in the image, so these recommendations "
                    "are based on your text plus the image's sanitized context."
                )
            _warn_msg = (
                f"⚠️ Heads up: a suspicious element (e.g. QR code / hidden payload) in your image "
                f"was detected and neutralised — I did not open or follow it, and it's been logged for "
                f"security review. {_anchor}"
            )
        elif image_handling_mode == "text_only_fallback":
            # Pixels themselves looked altered → ask the user to recover context.
            _warn_msg = (
                "⚠️ Your image looked altered or unreadable, so I couldn't safely identify the product "
                "from it (this has been logged for security review). I've used your text for now — to get "
                "you the right match, can you tell me the model or type you're after?"
            )
            _clarify_q = {
                "id": "clarify_product_identity",
                "text": "Which product is it? (model name or type, e.g. '17\" gaming laptop, RTX 4070')",
                "goal": "clarify_product_identity",
            }
            _nq = out.get("next_questions")
            if isinstance(_nq, list):
                if not any(isinstance(x, dict) and x.get("id") == "clarify_product_identity" for x in _nq):
                    out["next_questions"] = [_clarify_q] + _nq
            else:
                out["next_questions"] = [_clarify_q]
            out["needs_disambiguation"] = True
        else:
            if recognized_image_label:
                _basis = f"I've based these recommendations on {recognized_image_label} and your text."
            else:
                _basis = "I've based these recommendations on your text and the image's sanitized context."
            # Only ALARM the buyer when there is a genuine threat indicator — a benign upload that merely
            # tripped a soft posture check should not see "flagged by our security system" (the SOC breach
            # assessment + WORM audit still fire regardless; this only tunes the buyer-facing tone).
            _real_threat = (
                bool(image_security_posture.get("needs_human_review"))
                or bool(image_security_posture.get("chat_lockdown"))
                or str(image_security_posture.get("route") or "allow").lower() not in ("allow", "")
            )
            _warn_msg = (
                f"⚠️ Your uploaded image was flagged by our security system and logged for review. {_basis}"
                if _real_threat else _basis
            )
        if _ba and (_ba.get("ip_assessment") or {}).get("known_bad_actor"):
            _warn_msg = _warn_msg + " Note: this request originated from a network flagged as high-risk."
        _am = str(out.get("assistant_message") or "")
        if _warn_msg and "neutralised" not in _am.lower() and "flagged" not in _am.lower() and "[security]" not in _am.lower():
            out["assistant_message"] = f"{_warn_msg}\n\n{_am}".strip()
        out["platform_compromise"] = True
        out["needs_human_review"] = True
        out["security_warning"] = _warn_msg
        out["image_handling_mode"] = image_handling_mode
        out["recognized_product"] = recognized_image_label
        if _ba is not None:
            out["breach_assessment"] = _ba
    if isinstance(data.get("agent_steps"), list):
        out["agent_steps_readable"] = ResponseNormalizer.agent_steps_to_english(
            data.get("agent_steps") or []
        )
    try:
        if not persist_conversation:
            raise RuntimeError("temporary_chat")
        clarification_memory = Memory(
            redis,
            tenant_id=tenant_id,
            session_epoch=session_epoch,
        )
        semantic = (
            out.get("semantic_resolution")
            if isinstance(out.get("semantic_resolution"), dict) else {}
        )
        material_question = next((
            item for item in (out.get("next_questions") or [])
            if isinstance(item, dict) and (
                item.get("id") == "budget_scope"
                or bool(item.get("missing_slots"))
                or str(item.get("reason") or "").startswith(("missing_", "unresolved_", "contradictory_"))
                or semantic.get("catalog_authority") == "blocked"
            )
        ), None)
        pending_record = None
        if material_question:
            from src.app.services.clarification_state import build_pending_clarification, replacement_root_query

            pending_record = build_pending_clarification(
                material_question,
                original_query=replacement_root_query(
                    pending=pending_clarification,
                    submitted_query=submitted_query,
                    clarification_relation=routed_clarification_relation,
                ),
                trace_id=decision_trace_id,
                semantic_resolution=semantic,
                case_anchor=(
                    out.get("case_anchor")
                    if isinstance(out.get("case_anchor"), dict) else {}
                ),
                external_research_consent=(
                    str(params.get("external_research_consent") or "").lower() == "true"
                ),
                commercial_state={
                    "quantity": out.get("requested_quantity"),
                    "total_budget_cents": (
                        response_confirmed_slots.get("total_budget_cents")
                        or (out.get("constraints_used") or {}).get("total_budget_cents")
                    ),
                    "currency": out.get("currency") or "AUD",
                    "selected_sku": (
                        (out.get("case_anchor") or {}).get("selected_sku")
                        if isinstance(out.get("case_anchor"), dict) else None
                    ),
                },
                original_intent=turn_intent,
                ttl_seconds=int(os.getenv("CHAT_CLARIFICATION_TTL_SECONDS", "900") or 900),
            )
        from src.app.services.clarification_state import persist_clarification_transition

        persist_clarification_transition(
            clarification_memory,
            uid=uid,
            prior=pending_clarification,
            consume_prior=pending_clarification_consumed,
            suspend_prior=pending_clarification_suspended,
            replacement=pending_record,
            ttl_seconds=int(os.getenv("CHAT_CLARIFICATION_TTL_SECONDS", "900") or 900),
        )
    except Exception:
        if persist_conversation:
            logger.warning("pending chat clarification persistence failed", exc_info=True)
    try:
        if not persist_conversation:
            raise RuntimeError("temporary_chat")
        user_message_id = _store_chat_message(
            db,
            uid=uid,
            role="user",
            content=q,
            trace_id=decision_trace_id,
            session_id=session_id,
            tenant_id=tenant_id,
            session_epoch=session_epoch,
        )
        if user_message_id:
            from src.app.deps import hash_uid
            from src.app.services.conversation_fact_observations import (
                record_conversation_fact_observations,
            )

            try:
                record_conversation_fact_observations(
                    tenant_id=tenant_id,
                    subject_ref=hash_uid(uid),
                    session_id=session_id,
                    source_message_id=user_message_id,
                    trace_id=decision_trace_id,
                    message=q,
                )
            except Exception as observation_exc:
                logger.warning(
                    "conversation fact observation unavailable tenant=%s trace=%s: %s",
                    tenant_id,
                    decision_trace_id,
                    observation_exc,
                )
            # A transcript observation is not enough to preserve an active procurement
            # case. Project the same turn through the canonical case reducer when the
            # response carries a durable case identity. This is isolated from the request
            # transaction and is advisory only: consequential amendments remain pending
            # until the appropriate confirmation/execution boundary applies them.
            fulfillment_case = (
                out.get("fulfillment_case")
                if isinstance(out.get("fulfillment_case"), dict)
                else {}
            )
            case_anchor = (
                out.get("case_anchor") if isinstance(out.get("case_anchor"), dict) else {}
            )
            active_case_id = str(
                fulfillment_case.get("case_id") or case_anchor.get("case_id") or ""
            ).strip()
            if active_case_id:
                try:
                    from src.app.services.conversation_case_state import (
                        ensure_case_state,
                        record_case_turn,
                        record_typed_case_patch_set,
                    )

                    bind = db.get_bind() if hasattr(db, "get_bind") else getattr(db, "bind", None)
                    if bind is None:
                        raise RuntimeError("conversation_case_store_requires_database_bind")
                    first_product = products[0] if products and isinstance(products[0], dict) else {}
                    sku = str(
                        fulfillment_case.get("item_ref")
                        or case_anchor.get("sku")
                        or first_product.get("sku")
                        or first_product.get("id")
                        or ""
                    ).strip() or None
                    anchor = {
                        "sku": sku,
                        "quantity": out.get("requested_quantity") or case_anchor.get("quantity"),
                        "budget": {
                            "currency": str(out.get("currency") or "AUD"),
                            "scope": response_confirmed_slots.get("budget_scope"),
                            "total_cents": response_confirmed_slots.get("total_budget_cents"),
                        },
                        "destination": (
                            response_confirmed_slots.get("destination")
                            or response_confirmed_slots.get("ship_to")
                            or case_anchor.get("destination_token")
                        ),
                        "deadline": (
                            response_confirmed_slots.get("deadline")
                            or case_anchor.get("deadline")
                        ),
                        "case_status": fulfillment_case.get("status"),
                        "semantic_resolution": (
                            out.get("semantic_resolution")
                            if isinstance(out.get("semantic_resolution"), dict)
                            else None
                        ),
                        "catalog_authority": case_anchor.get("catalog_authority"),
                        "objective": (
                            out.get("retained_purpose")
                            or (
                                out.get("shopping_case", {}).get("retained_purpose")
                                if isinstance(out.get("shopping_case"), dict) else None
                            )
                            or q
                        ),
                        "destination_allocations": (
                            out.get("destination_allocations")
                            if isinstance(out.get("destination_allocations"), list) else None
                        ),
                    }
                    with Session(bind=bind, future=True) as case_db:
                        ensured = ensure_case_state(
                            case_db,
                            tenant_id=tenant_id,
                            case_id=active_case_id,
                            session_epoch=session_epoch,
                            subject_ref=hash_uid(uid),
                            authoritative_anchor=anchor,
                        )
                        decision_payload = (
                            out.get("decision") if isinstance(out.get("decision"), dict) else {}
                        )
                        case_patches = decision_payload.get("case_patches")
                        preflight_application = (
                            out.get("case_patch_application")
                            if isinstance(out.get("case_patch_application"), dict) else None
                        )
                        if preflight_application is not None:
                            out["case_memory"] = dict(preflight_application)
                        elif isinstance(case_patches, list) and case_patches:
                            out["case_memory"] = record_typed_case_patch_set(
                                case_db,
                                tenant_id=tenant_id,
                                case_id=active_case_id,
                                session_epoch=session_epoch,
                                subject_ref=hash_uid(uid),
                                source_message_id=user_message_id,
                                idempotency_key=params_case_patch_idempotency_key,
                                expected_version=int(ensured["version"]),
                                patches=case_patches,
                                trace_id=decision_trace_id,
                            )
                        else:
                            out["case_memory"] = record_case_turn(
                                case_db,
                                tenant_id=tenant_id,
                                case_id=active_case_id,
                                session_epoch=session_epoch,
                                subject_ref=hash_uid(uid),
                                source_message_id=user_message_id,
                                trace_id=decision_trace_id,
                                message=q,
                            )
                except Exception as case_state_exc:
                    logger.warning(
                        "conversation case projection unavailable tenant=%s case=%s trace=%s: %s",
                        tenant_id,
                        active_case_id,
                        decision_trace_id,
                        case_state_exc,
                    )
    except Exception:
        if persist_conversation:
            logger.warning("chat message persistence failed", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
    if persist_conversation:
        from src.app.services.chat_persistence import persist_chat_result

        persistence_receipt = persist_chat_result(
            db,
            redis=redis,
            uid=uid,
            query=q,
            products=products,
            trace_id=decision_trace_id,
            assistant_message=str(out.get("assistant_message") or ""),
            budget=_extract_budget_bounds(q),
            brands=_extract_brand_mentions(q),
            session_id=session_id,
            tenant_id=tenant_id,
            session_epoch=session_epoch,
            recent_messages=(payload or {}).get("recent_messages") if isinstance((payload or {}).get("recent_messages"), list) else None,
            confirmed_slots=response_confirmed_slots,
            semantic_resolution=(
                out.get("semantic_resolution")
                if isinstance(out.get("semantic_resolution"), dict) else None
            ),
            case_anchor=(
                out.get("case_anchor")
                if isinstance(out.get("case_anchor"), dict) else None
            ),
        )
        if persistence_receipt.errors:
            logger.warning(
                "chat result persistence degraded tenant=%s trace=%s errors=%s",
                tenant_id,
                decision_trace_id,
                ",".join(persistence_receipt.errors),
            )
    return out


@router.get("/history")
def chat_history(
    request: Request,
    uid: str,
    limit: int = Query(50, ge=1, le=500),
    before: Optional[str] = None,
    session_epoch: Optional[str] = Query(None, max_length=128),
    db=Depends(get_db),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    tenant_id = _request_tenant_id(request)
    epoch = str(session_epoch or uid)[:128]
    params: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "uid": uid,
        "session_epoch": epoch,
        "lim": int(limit),
    }
    where = (
        "WHERE tenant_id = :tenant_id AND uid = :uid "
        "AND session_epoch = :session_epoch"
    )
    if before:
        where += " AND created_at < :before"
        params["before"] = str(before)
    rows = db.execute(
        sql_text(
            f"""
            SELECT id, tenant_id, uid, session_id, session_epoch,
                   role, content, trace_id, created_at
            FROM chat_messages
            {where}
            ORDER BY created_at DESC
            LIMIT :lim
            """
        ),
        params,
    ).mappings().all()
    items = [dict(r) for r in rows]
    items.reverse()
    return {
        "tenant_id": tenant_id,
        "uid": uid,
        "session_epoch": epoch,
        "count": len(items),
        "items": items,
    }


@router.post("/ollama_test")
async def ollama_test(
    payload: Dict,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    """Route queries to small vs big Ollama models based on complexity and return a short summary.

    Input: { query: string }
    Output: { model: string, complex: bool, total_duration_ms: number, response: string }
    """
    q = (payload or {}).get("query") or ""
    if not q.strip():
        raise HTTPException(status_code=400, detail="query_required")
    model = select_ollama_model(q)
    try:
        result = await ollama_generate(model, f"Summarize the user's intent in one sentence and list top 2 attributes to consider.\nUser Query: {q}")
        return {
            "model": model,
            "complex": is_complex_query(q),
            "total_duration_ms": result.get("total_duration_ms"),
            "response": result.get("response"),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ollama_unavailable: {e}")
