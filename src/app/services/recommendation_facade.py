"""Recommendation dispatch facade (V2 — GPT-5.6 review-2 finding #1, #4, #6, #10).

THE LIVE DISPATCH BOUNDARY. The first core wiring returned from inside suggest() BEFORE the
shared commerce guard, image security, and normal persistence — a proof-of-life, not a
production boundary. This module is that boundary, built right:

  preflight (SHARED, not duplicated)
    → inspect_commerce_request  — the REAL guard (prompt-injection/XSS/SQLi/uid/sku); a
      'block' verdict emits the security event and returns the same block payload legacy
      does, so the core can never bypass it. Its verdict is passed into the envelope so the
      core reads the real guard, not a second regex (finding #10).
    → session slice             — best-effort read of the durable session (prior node,
      constraints, shortlist, referents); populated now, consumed by prior-subject
      resolution in a later step.
  dispatch (mode ladder, finding #4)
    → off      : return None → legacy serves (default; zero live change).
    → shadow   : legacy serves; a durable job is enqueued for OFFLINE diffing (no inline
                 second brain — that doubles latency, the critique that killed wiring #1).
    → canary:N : stable per-user bucketing → N% to core, rest to legacy.
    → primary  : core serves every CANARY-eligible lane.
  lane gate (finding #6)
    → only SEARCH/FILTER/COMPARE/EXPLAIN/OFF_CATALOG are core-served; cart, claims, policy,
      inventory, procurement, and image turns fall through to legacy, which handles them
      properly. (Cost: a non-core lane under canary/primary runs the router then falls
      through — double work on a small traffic slice; safety over latency, documented.)
  postflight
    → the caller's with_trace() runs sanitization + REAL trace persistence (the persisted
      flag is now honest — finding #2).

Returns a finalized payload dict when the core owns the turn, or None to fall through to
legacy. Never raises into the router: any failure records + returns None (legacy is always
a safe fallback).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional

from src.app.security.commerce_request_guard import inspect_commerce_request
from src.app.services.recommendation_core.envelope import TurnEnvelope

logger = logging.getLogger("shopsquire.recommendation_facade")

# the lanes the core is trusted to serve live; everything else → legacy (finding #6)
CANARY_LANES = frozenset({"SEARCH", "FILTER", "COMPARE", "EXPLAIN", "OFF_CATALOG"})
_SHADOW_QUEUE_KEY = "shadow:core:queue"
_SHADOW_QUEUE_MAX = 5000


def _resolve_mode() -> tuple[str, int]:
    """(mode, canary_pct). RECOMMEND_CORE_MODE = off | shadow | canary:<pct> | primary."""
    raw = str(os.getenv("RECOMMEND_CORE_MODE", "") or "").strip().lower()
    if raw.startswith("canary"):
        pct = 0
        if ":" in raw:
            try:
                pct = max(0, min(100, int(raw.split(":", 1)[1])))
            except ValueError:
                pct = 0
        return "canary", pct
    if raw in ("shadow", "primary", "off"):
        return raw, 0
    return "off", 0


def _in_canary_bucket(key: str, pct: int) -> bool:
    """Stable per-user/tenant bucketing: the same key always lands the same side of the split
    (deterministic across turns — a user doesn't flip between engines mid-session)."""
    if pct <= 0:
        return False
    if pct >= 100:
        return True
    h = int(hashlib.sha256(str(key or "anon").encode("utf-8")).hexdigest(), 16)
    return (h % 100) < pct


def _enqueue_shadow(redis, *, query: str, uid: str, tenant_id: str, trace_id: str) -> None:
    """Durable shadow job (finding #4): legacy serves live; the offline worker/replay drains
    this queue and diffs core vs the recorded/served response. Best-effort; capped so a
    stalled drainer can't grow it unbounded."""
    if redis is None:
        return
    try:
        job = json.dumps({"query": query, "uid": uid, "tenant_id": tenant_id,
                          "trace_id": trace_id})
        redis.lpush(_SHADOW_QUEUE_KEY, job)
        redis.ltrim(_SHADOW_QUEUE_KEY, 0, _SHADOW_QUEUE_MAX - 1)
    except Exception as exc:
        logger.debug("shadow enqueue skipped: %s", repr(exc)[:100])


def _read_session_slice(redis, uid: str, tenant_id: str) -> Dict[str, Any]:
    """Best-effort immutable session slice, TENANT-SCOPED (GPT-5.6 #5c22575.3): the core's
    session namespace is session:{tenant}:{uid}:kv_state — never uid-alone (that would cross
    tenants). Consumed by prior-subject resolution later; populated now so the wiring is
    proven end-to-end."""
    if redis is None or not uid:
        return {}
    try:
        raw = redis.get(f"session:{tenant_id}:{uid}:kv_state")
        data = json.loads(raw) if raw else {}
        if not isinstance(data, dict) or not data:
            return {}
        return {"prior_node": data.get("last_node_handle"),
                "shortlist_skus": data.get("last_shortlist_skus") or [],
                "accepted_constraints": data.get("constraints") or {}}
    except Exception:
        return {}


def _run_guard(*, query: str, uid: str, image_labels: Optional[str],
               image_ocr: Optional[str]) -> Dict[str, Any]:
    try:
        return inspect_commerce_request(
            surface="recommend.core", texts=[query, image_labels, image_ocr], uid=uid,
            sku_values=[], quantity_values=[])
    except Exception as exc:
        logger.warning("commerce guard failed in facade — failing closed to review: %s",
                       repr(exc)[:120])
        return {"verdict": "review", "severity": "medium", "reasons": ["guard_error"]}


def dispatch_recommendation_core(
    db, redis, *, query: str, uid: str, tenant_id: Optional[str],
    budget_min: Optional[float], budget_max: Optional[float], trace_id: str,
    image_labels: Optional[str] = None, image_hash: Optional[str] = None,
    image_ocr: Optional[str] = None, source_ip: Optional[str] = None, request: Any = None,
    with_trace: Callable[[Dict[str, Any], str], Dict[str, Any]],
    record_failure: Callable[..., Any],
) -> Optional[Dict[str, Any]]:
    """See module docstring. Returns finalized payload if the core owns the turn, else None."""
    mode, pct = _resolve_mode()
    if mode == "off":
        return None
    tenant = tenant_id or "default"

    # SHADOW enqueues EVERY turn (review #8): the shadow corpus must include image turns —
    # excluding them here would overstate coverage when the image lane is later core-enabled.
    # Enqueue is offline-diff only; it never serves.
    if mode == "shadow":
        _enqueue_shadow(redis, query=query, uid=uid, tenant_id=tenant, trace_id=trace_id)
        return None

    # IMAGE turns → legacy (review-3 #5c22575.2): the image lane (quarantine, CV, vision
    # identity) is not core-SERVED yet; a text lane carrying an image must not be either.
    # Excluded from SERVING (below), not from shadow (above).
    if image_labels or image_hash:
        return None
    # canary bucket on tenant:uid (GPT-5.6 #5c22575.4) — same user in different tenants can
    # legitimately land different sides; anon users bucket by tenant.
    if mode == "canary" and not _in_canary_bucket(f"{tenant}:{uid or 'anon'}", pct):
        return None

    try:
        # ── PREFLIGHT: the real shared guard (finding #1/#10) ──────────────────
        # Require verdict==allow (GPT-5.6 #5c22575.1): 'review' and guard-failure ('review'
        # fail-closed) fall through to legacy too — review semantics aren't implemented in the
        # core, so a flagged query must never be core-served with products. Blocked/reviewed
        # input reaches legacy's full guard path (security event, block payload).
        guard = _run_guard(query=query, uid=uid, image_labels=image_labels, image_ocr=image_ocr)
        if str(guard.get("verdict")) != "allow":
            return None

        session = _read_session_slice(redis, uid, tenant)
        envelope = TurnEnvelope.from_suggest_params(
            query=query, uid=uid or "", tenant_id=tenant, budget_min=budget_min,
            budget_max=budget_max, trace_id=trace_id,
            has_image=bool(image_labels or image_hash), source_ip=source_ip,
            session=session, pre_gate=guard)

        # ── DISPATCH ───────────────────────────────────────────────────────────
        from src.app.services.recommendation_core.core import recommend_turn
        from src.app.services.recommendation_core.legacy_adapter import to_legacy
        _t0 = time.perf_counter()
        core = recommend_turn(db, envelope)
        _latency_ms = int((time.perf_counter() - _t0) * 1000)

        # ── LANE GATE (finding #6): non-core lanes fall through to legacy ───────
        if core.lane not in CANARY_LANES:
            logger.debug("core lane %s not canary-eligible — falling through to legacy", core.lane)
            return None

        # DEGRADED → legacy (review #5): a core turn that couldn't verify the catalog
        # (grounding error / retrieval failure) must NOT serve a 'try again' apology to a
        # canary buyer while a healthy legacy sits one return away. Honest degradation only
        # falls back when it produced nothing — an off-catalog refusal is a real answer, keep it.
        if core.grounding in ("error", "empty") or (core.degraded and not core.products and not core.off_catalog):
            logger.info("core degraded (grounding=%s reason=%s) — falling through to legacy",
                        core.grounding, (core.extras or {}).get("degraded_reason"))
            return None

        # ── FINALIZE FIRST, THEN POSTFLIGHT (review #3): with_trace (sanitize + trace
        # persistence) must SUCCEED before any session mutation. If it raises, the outer except
        # returns None → legacy serves, and session state was NOT yet written by V2 — no
        # split-brain where V2 mutated session but legacy answered.
        payload = with_trace(to_legacy(core), trace_id)
        try:
            from src.app.services.recommendation_postflight import run_postflight
            run_postflight(redis, envelope, core, latency_ms=_latency_ms)
        except Exception as _e_pf:
            logger.warning("postflight failed (non-fatal): %s", repr(_e_pf)[:120])
        return payload
    except Exception as exc:
        record_failure("recommend_core_dispatch", exc, trace_id=trace_id)
        return None   # legacy is always a safe fallback
