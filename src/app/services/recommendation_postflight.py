"""Shared postflight (V2 — GPT-5.6 review-3 roadmap item 1).

The core path returned through `_with_trace` (sanitize + trace persistence) but SKIPPED the
turn's other side effects — most importantly MEMORY WRITEBACK, so multi-turn broke: nothing
populated the session slice the facade reads next turn. This is the shared side-effect stage:

  session writeback  — the immutable slice the facade consumes: prior node, shortlist SKUs,
                       accepted constraints, use-cases. TENANT-SCOPED (session:{tenant}:{uid})
                       to match the facade reader. This is what makes prior-subject resolution
                       and 'those' / 'the first one' possible.
  telemetry          — one metered record per core turn (lane, use-cases, count, latency,
                       degraded) so the canary has operational visibility.
  narration hook     — optional async prose enqueue (parity with v1's async narration); the
                       core's finalize() message is already honest, so this is an enhancement,
                       wired as an extension point, off by default.

Best-effort by construction: a side-effect failure must NEVER change the response the buyer
already has. Every leg is independently guarded + logged.

Convergence note: legacy suggest() has its own richer writeback (rolling summary, pinned
context); this module is the CORE's writeback today and the shared target both paths adopt as
the legacy path is retired — not a same-day big-bang extraction of suggest()'s internals.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

from src.app.services.recommendation_core.envelope import CoreResponse, TurnEnvelope

logger = logging.getLogger("shopsquire.recommendation_postflight")

_SESSION_TTL_S = 60 * 60 * 6   # 6h — a shopping session, not forever


def _session_key(tenant_id: str, uid: str) -> str:
    return f"session:{tenant_id}:{uid}:kv_state"


def write_session(
    redis,
    envelope: TurnEnvelope,
    core: CoreResponse,
    *,
    session_epoch: str | None = None,
) -> bool:
    """Persist the immutable session slice the facade reads next turn. Returns True on write."""
    if redis is None or not envelope.uid:
        return False
    try:
        decision = core.extras.get("decision") or {}
        intent = core.extras.get("intent") or {}
        # constraints persisted = what the turn USED (R9.1): constraints_used carries session-
        # inherited budget/requirements, so a budget-less follow-up REFRESHES the remembered
        # budget instead of wiping it (screenshot 30's loss point was exactly this overwrite).
        used = core.extras.get("constraints_used") or {}
        prior = (envelope.session or {}).get("accepted_constraints") or {}
        decision_quantity = decision.get("quantity")
        decision_total = decision.get("total_budget_cents")
        clear_brands = decision.get("brand_action") == "clear"
        prior_workflow = ((envelope.session or {}).get("active_workflow_lane")
                          or ((envelope.session or {}).get("prior_lane")
                              if (envelope.session or {}).get("prior_lane") == "PROCUREMENT"
                              else None))
        if core.lane == "PROCUREMENT":
            active_workflow = "PROCUREMENT"
        elif decision.get("subject_action") == "switch":
            active_workflow = None
        else:
            active_workflow = prior_workflow
        slice_ = {
            "last_node_handle": (decision.get("node_handle") or used.get("node_handle")
                                 or (envelope.session or {}).get("prior_node")),
            "last_shortlist_skus": ([c.sku for c in core.products][:12]
                                    or list((envelope.session or {}).get("shortlist_skus") or [])[:12]),
            "constraints": {
                "budget_min_cents": used.get("budget_min_cents", envelope.budget_min_cents),
                "budget_max_cents": used.get("budget_max_cents", envelope.budget_max_cents),
                "requirements": (used.get("requirements") or decision.get("requirements") or {}),
                "use_cases": intent.get("use_cases") or [],
                "workload_entities": (used.get("workload_entities")
                                      or decision.get("workload_entities")
                                      or prior.get("workload_entities")
                                      or []),
                # bulk state (Phase 1f) — so a follow-up 'how many can I get?' inherits the order
                # size + total budget the shopper set earlier (the facade maps this into
                # accepted_constraints verbatim).
                "quantity": (decision_quantity if decision_quantity is not None
                             else prior.get("quantity")),
                "total_budget_cents": (decision_total if decision_total is not None
                                        else prior.get("total_budget_cents")),
                "budget_scope": (decision.get("budget_scope")
                                 if decision.get("budget_scope") in ("total", "per_unit")
                                 else prior.get("budget_scope")),
                # brand constraints (review-10 P0.6) — so 'now show me cheaper ones' keeps the
                # 'only Asus' / 'not Apple' the shopper set on a prior turn.
                "brand_filter": (None if clear_brands else decision.get("brand_filter")
                                 if decision.get("brand_filter") is not None
                                 else prior.get("brand_filter")),
                "exclude_brand": (None if clear_brands else decision.get("exclude_brand")
                                  if decision.get("exclude_brand") is not None
                                  else prior.get("exclude_brand")),
                "preferred_brand": (None if clear_brands else decision.get("preferred_brand")
                                    if decision.get("preferred_brand") is not None
                                    else prior.get("preferred_brand")),
            },
            "last_lane": core.lane,
            "active_workflow_lane": active_workflow,
            "ts": int(time.time()),
        }
        if session_epoch:
            from src.app.services.memory import Memory

            Memory(
                redis,
                tenant_id=envelope.tenant_id,
                session_epoch=session_epoch,
            ).set_structured_state(envelope.uid, slice_, ttl_seconds=_SESSION_TTL_S)
            return True
        payload = json.dumps(slice_)
        key = _session_key(envelope.tenant_id, envelope.uid)
        try:
            redis.setex(key, _SESSION_TTL_S, payload)
        except Exception:
            redis.set(key, payload)   # DummyRedis / clients without setex
        return True
    except Exception as exc:
        logger.warning("session writeback failed (uid=%s): %s", envelope.uid, repr(exc)[:120])
        return False


def emit_telemetry(envelope: TurnEnvelope, core: CoreResponse, *, latency_ms: int) -> None:
    """One metered record per core-served turn. Best-effort; log if the metrics sink is absent."""
    rec = {
        "engine": "recommendation_core", "tenant_id": envelope.tenant_id, "lane": core.lane,
        "use_cases": (core.extras.get("intent") or {}).get("use_cases") or [],
        "product_count": len(core.products), "degraded": bool(core.degraded),
        "grounding": core.grounding, "off_catalog": bool(core.off_catalog),
        "latency_ms": latency_ms,
    }
    try:
        from src.app.observability.metrics import record_event as _record  # type: ignore
        _record("recommend_core_turn", rec)
    except Exception:
        logger.info("core_turn %s", json.dumps(rec))


def run_postflight(
    redis,
    envelope: TurnEnvelope,
    core: CoreResponse,
    *,
    latency_ms: int = 0,
    narrate: bool = False,
    executor: Any = None,
    session_epoch: str | None = None,
    memory_enabled: bool = True,
) -> Dict[str, Any]:
    """The shared side-effect stage. Returns an outcome dict for the trace; never raises."""
    out: Dict[str, Any] = {"session_written": False, "narration_job_id": None}
    if memory_enabled:
        out["session_written"] = write_session(
            redis,
            envelope,
            core,
            session_epoch=session_epoch,
        )
    try:
        emit_telemetry(envelope, core, latency_ms=latency_ms)
    except Exception as exc:   # observable, not silent (no-silent-except ratchet)
        logger.warning("telemetry emit failed (non-fatal): %s", repr(exc)[:120])
    if narrate and executor is not None and core.products:
        out["narration_job_id"] = _enqueue_narration(redis, envelope, core, executor)
    return out


def _enqueue_narration(redis, envelope: TurnEnvelope, core: CoreResponse, executor) -> Optional[str]:
    """Optional async prose (parity with v1). Extension point — the deterministic message is
    already honest, so this only enriches; guarded so it can never break the turn."""
    try:
        from src.app.services.recommend_narration_jobs import submit_narration
        # a real narration fn (grounded, guard-checked) is wired when narration parity is
        # prioritized; today we reserve the job id so the contract/handshake exists.
        def _noop(*_a, **_k) -> str:
            return core.message
        return submit_narration(executor, redis, _noop)
    except Exception as exc:
        logger.debug("narration enqueue skipped: %s", repr(exc)[:100])
        return None
