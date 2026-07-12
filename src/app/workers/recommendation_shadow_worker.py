"""V2 shadow worker (M1.2) — drains shadow:core:queue, runs V2 OFFLINE, diffs against the V1
response legacy already served, records metrics. This is what makes RECOMMEND_CORE_MODE=shadow
mean something: the facade enqueues every shadow turn (legacy serves it live), and this worker
measures what V2 WOULD have done — with zero added latency on the hot path and zero double-serve.

The V1 baseline is loaded from the DECISION TRACE legacy persisted for the turn (by trace_id),
so the diff is faithful without re-running V1 or capturing it inline. When the trace isn't
found (async lag / disabled persistence), the turn is scored INTRINSIC-ONLY (V2 behaviour:
lane, grounding, products, latency) — still useful, never dropped.

Run: python -m src.app.workers.recommendation_shadow_worker [--once] [--max N]
A poisoned job that fails _MAX_RETRIES times is dead-lettered to shadow:core:deadletter.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("shopsquire.recommendation_shadow_worker")

QUEUE_KEY = "shadow:core:queue"                    # legacy list (fallback + migration drain)
STREAM_KEY = "shadow:core:stream"                  # R10.4b durable path
GROUP = "shadow-workers"
DEADLETTER_KEY = "shadow:core:deadletter"          # legacy list DLQ (fallback)
DEADLETTER_STREAM = "shadow:core:deadletter:stream"
_MAX_RETRIES = 3
_BRPOP_TIMEOUT_S = 5
_CLAIM_IDLE_MS = 60_000    # a pending entry idle >60s = its consumer died → reclaim it
_MAX_DELIVERIES = 4        # redeliveries beyond this = poison (crashes the worker each time)


def _v1_products_from_trace(db, trace_id: str) -> Optional[List[Dict[str, Any]]]:
    """Reconstruct legacy's served product set from the recommendation_result trace event —
    the faithful V1 baseline. None when the trace isn't present (scored intrinsic-only)."""
    if not trace_id:
        return None
    try:
        from sqlalchemy import text
        row = db.execute(text(
            "SELECT payload FROM decision_trace_events WHERE trace_id = :t "
            "AND event_type = 'recommendation_result' ORDER BY created_at DESC LIMIT 1"),
            {"t": trace_id}).fetchone()
        if not row or not row[0]:
            return None
        payload = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        summary = (payload or {}).get("products_summary") or []
        return [{"sku": p.get("sku"), "name": p.get("name")} for p in summary if isinstance(p, dict)]
    except Exception as exc:
        logger.debug("v1 trace load failed (%s): %s", trace_id, repr(exc)[:100])
        return None


def _job_envelope(job: Dict[str, Any]):
    """THE job→envelope decision (R10.1/P1.1). New jobs carry the FULL envelope.to_dict()
    (budget/session/image/cart — the turn production actually saw); old queued jobs fall back
    to the top-level keys and measure budget-less/session-less, exactly as before."""
    from src.app.services.recommendation_core.envelope import TurnEnvelope
    if isinstance(job.get("envelope"), dict):
        return TurnEnvelope.from_dict(job["envelope"])
    return TurnEnvelope.from_suggest_params(
        query=job.get("query", ""), uid=job.get("uid", ""),
        tenant_id=job.get("tenant_id", "default"), budget_min=job.get("budget_min"),
        budget_max=job.get("budget_max"), trace_id=job.get("trace_id"),
        cart=job.get("cart") or [])


def _resolve_cart_plan(job: Dict[str, Any], llm_fn=None) -> Optional[Dict[str, Any]]:
    """C0 resolve-only shadow: resolve the job's cart edit into a CartMutationPlan OFFLINE —
    measured, logged, NEVER executed. Returns the plan row (or None when the job carries no
    cart). The plan is written to the decision trace (event cart_shadow_plan) so the phrasing
    corpus is reviewable in the Decision Trace UI before any serving decision."""
    cart = job.get("cart")
    if not cart:
        return None
    from src.app.services.recommendation_core.cart_resolver import resolve_cart_mutation
    env = _job_envelope(job)
    t0 = time.perf_counter()
    plan = resolve_cart_mutation(env, llm_fn=llm_fn)
    row = {"trace_id": job.get("trace_id"), "kind": "cart_shadow_plan",
           "outcome": ("ambiguous" if plan.needs_clarification
                       else ("ops" if plan.ops else "empty")),
           "plan": plan.as_dict(), "latency_ms": int((time.perf_counter() - t0) * 1000)}
    try:
        from src.app.observability.metrics import record_cart_shadow
        record_cart_shadow(row["outcome"])
    except Exception as exc:
        logger.debug("cart shadow metric skipped: %s", repr(exc)[:80])
    try:
        from src.app.services.decision_log import log_trace_event
        log_trace_event(trace_id=job.get("trace_id"), event_type="cart_shadow_plan",
                        source_type="worker", source_id="recommendation_shadow_worker",
                        target_type="cart", target_id=None,
                        payload={"query": str(job.get("query", ""))[:300], **row["plan"],
                                 "outcome": row["outcome"], "executed": False})
    except Exception as exc:
        logger.debug("cart shadow trace event skipped: %s", repr(exc)[:80])
    logger.info("cart shadow %s", json.dumps(row))
    return row


def process_job(db, job: Dict[str, Any], *, cart_llm_fn=None) -> Dict[str, Any]:
    """Run V2 for one shadow job, diff against V1-from-trace, return the scorecard row.
    Pure except for the read-only DB + metrics; never raises (caller handles retry).
    Jobs carrying a cart slice also get a resolve-only cart plan (C0); cart_only jobs
    (enqueued solely for cart measurement) skip the search diff entirely."""
    cart_row = _resolve_cart_plan(job, llm_fn=cart_llm_fn)
    if job.get("cart_only"):
        return cart_row or {"trace_id": job.get("trace_id"), "kind": "cart_shadow_plan",
                            "outcome": "empty", "diffed": False}

    from src.app.services.recommend_parity_full import diff_responses, evaluate_case, message_class
    from src.app.services.recommendation_core.core import recommend_turn
    from src.app.services.recommendation_core.legacy_adapter import to_legacy

    env = _job_envelope(job)
    t0 = time.perf_counter()
    core = recommend_turn(db, env)
    v2 = to_legacy(core)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    v1_products = _v1_products_from_trace(db, job.get("trace_id"))
    row: Dict[str, Any] = {
        "trace_id": job.get("trace_id"), "lane": core.lane, "grounding": core.grounding,
        "v2_products": len(core.products), "v2_class": message_class(v2),
        "degraded": bool(core.degraded), "latency_ms": latency_ms, "diffed": False,
    }
    if v1_products is not None:
        v1 = {"products": v1_products, "results": v1_products, "assistant_message": "v1"}
        d = diff_responses(v1, v2)
        row.update({"diffed": True, "severity": d["severity"],
                    "v1_products": len(v1_products),
                    "jaccard": d["dimensions"]["product_set"]["jaccard"],
                    "v1_class": message_class(v1)})
    _record_metrics(row)
    return row


def _record_metrics(row: Dict[str, Any]) -> None:
    try:
        from src.app.observability.metrics import record_event
        record_event("recommend_core_turn", {
            "lane": row.get("lane"), "grounding": row.get("grounding"),
            "degraded": row.get("degraded"), "latency_ms": row.get("latency_ms"),
            "product_count": row.get("v2_products")})
    except Exception as exc:   # observable, not silent (review-6 #22) — a dead metrics sink
        logger.debug("shadow metrics sink failed: %s", repr(exc)[:100])
    logger.info("shadow %s", json.dumps(row))


def _ensure_group(redis) -> bool:
    """Create the consumer group once (idempotent). False = no stream support on this client
    (DummyRedis / old server) → the worker drains only the legacy list, exactly as before."""
    try:
        redis.xgroup_create(STREAM_KEY, GROUP, id="0", mkstream=True)
        return True
    except AttributeError:
        return False
    except Exception as exc:
        if "BUSYGROUP" in repr(exc):
            return True                    # group already exists — the normal steady state
        logger.debug("xgroup_create failed (%s) — list-only mode", repr(exc)[:80])
        return False


def _stream_payload(fields) -> Optional[str]:
    """The job JSON out of a stream entry's field dict (bytes or str keys — client-dependent)."""
    if not isinstance(fields, dict):
        return None
    for k, v in fields.items():
        key = k.decode() if isinstance(k, bytes) else k
        if key == "payload":
            return v.decode() if isinstance(v, bytes) else v
    return None


def _read_stream_batch(redis, consumer: str, *, block_ms: int) -> List[tuple]:
    """[(msg_id, payload_json)] — stale pending entries FIRST (a dead consumer's unacked work,
    reclaimed via XAUTOCLAIM after _CLAIM_IDLE_MS; poison beyond _MAX_DELIVERIES is dead-lettered
    + acked here), then new entries (XREADGROUP '>'). At-least-once: nothing is removed from the
    stream until the processor ACKs it — a crash mid-job leaves the entry pending for reclaim,
    which is the loss mode the BRPOP list could not survive."""
    out: List[tuple] = []
    try:
        # 1. reclaim stale pending (dead-consumer recovery)
        try:
            res = redis.xautoclaim(STREAM_KEY, GROUP, consumer,
                                   min_idle_time=_CLAIM_IDLE_MS, start_id="0-0", count=10)
            claimed = res[1] if isinstance(res, (list, tuple)) and len(res) >= 2 else []
        except AttributeError:
            claimed = []                   # pre-6.2 server/client: skip recovery, never crash
        except Exception as exc:
            logger.debug("xautoclaim skipped: %s", repr(exc)[:80])
            claimed = []
        for msg_id, fields in claimed or []:
            payload = _stream_payload(fields)
            deliveries = _delivery_count(redis, msg_id)
            if deliveries is not None and deliveries > _MAX_DELIVERIES:
                _dead_letter(redis, payload or "", f"poison_redelivered_{deliveries}x")
                redis.xack(STREAM_KEY, GROUP, msg_id)
                continue
            if payload is not None:
                out.append((msg_id, payload))
        if out:
            return out
        # 2. new entries
        res = redis.xreadgroup(GROUP, consumer, {STREAM_KEY: ">"}, count=1, block=block_ms)
        for _stream, entries in res or []:
            for msg_id, fields in entries:
                payload = _stream_payload(fields)
                if payload is not None:
                    out.append((msg_id, payload))
    except Exception as exc:
        logger.debug("stream read failed: %s", repr(exc)[:80])
    return out


def _delivery_count(redis, msg_id) -> Optional[int]:
    """Delivery count for one pending entry (poison detection). None = can't tell (fail open —
    a reclaim loop without counts still converges via the DLQ on repeated failure)."""
    try:
        pend = redis.xpending_range(STREAM_KEY, GROUP, min=msg_id, max=msg_id, count=1)
        if pend:
            p = pend[0]
            return int(p.get("times_delivered") if isinstance(p, dict) else p[3])
    except Exception as exc:
        logger.debug("xpending delivery count unavailable: %s", repr(exc)[:80])
    return None


def run(redis, db_factory, *, once: bool = False, max_jobs: Optional[int] = None,
        consumer: str = "worker-1") -> Dict[str, int]:
    """Drain loop. db_factory() → a fresh read Session per job (short-lived, no cross-job state).
    once=True processes whatever is queued then stops (for tests/CI).

    R10.4b: the STREAM is the primary source (consumer group, ack-after-process, XAUTOCLAIM
    recovery of a dead consumer's pending work — zero loss on worker crash). The legacy LIST is
    still drained every cycle: clients without stream support enqueue there, and jobs queued
    before the upgrade must not strand."""
    import time as _time
    stats = {"processed": 0, "diffed": 0, "dead_lettered": 0, "errors": 0}
    streams = _ensure_group(redis)
    while True:
        worked = False
        # ── stream leg (durable) ─────────────────────────────────────────────
        if streams:
            for msg_id, item in _read_stream_batch(
                    redis, consumer, block_ms=0 if once else _BRPOP_TIMEOUT_S * 1000):
                worked = True
                _handle_raw(redis, db_factory, item, stats)
                try:
                    redis.xack(STREAM_KEY, GROUP, msg_id)   # ACK only after process/dead-letter
                except Exception as exc:
                    logger.warning("xack failed (job may redeliver — at-least-once): %s",
                                   repr(exc)[:80])
                if max_jobs and stats["processed"] >= max_jobs:
                    return stats
        # ── legacy list leg (fallback + migration) ───────────────────────────
        # non-blocking rpop sweep first — NEVER brpop(timeout=0), which in redis-py blocks
        # FOREVER (the hang class); block 5s only when this whole cycle found no work.
        item = None
        brpop_errored = False
        try:
            try:
                item = redis.rpop(QUEUE_KEY)
            except AttributeError:
                item = None                    # fake/old client without rpop → blocking leg below
            if item is None and not (worked or once):
                popped = redis.brpop(QUEUE_KEY, timeout=_BRPOP_TIMEOUT_S)
                item = popped[1] if popped else None
        except Exception as exc:
            logger.warning("list pop failed: %s", repr(exc)[:100])
            brpop_errored = True
        if item is not None:
            worked = True
            item = item.decode() if isinstance(item, bytes) else item
            _handle_raw(redis, db_factory, item, stats)
        if max_jobs and stats["processed"] >= max_jobs:
            break
        if not worked:
            if once:
                break
            # BACKOFF (defect-hunt #4): a RAISING brpop (Redis down) gives no 5s block, so a bare
            # `continue` busy-spins the CPU + floods the log until Redis returns.
            if brpop_errored:
                _time.sleep(_BRPOP_TIMEOUT_S)
    return stats


def _handle_raw(redis, db_factory, item: str, stats: Dict[str, int]) -> None:
    """One raw job payload → parse, process-with-retry, count. Shared by both legs."""
    try:
        job = json.loads(item)
    except Exception:
        _dead_letter(redis, item, "unparseable")
        stats["dead_lettered"] += 1
        return
    row = _process_with_retry(redis, db_factory, job, item, stats)
    if row and row.get("diffed"):
        stats["diffed"] += 1
    stats["processed"] += 1


def _process_with_retry(redis, db_factory, job, raw, stats) -> Optional[Dict[str, Any]]:
    last_exc = None
    for attempt in range(_MAX_RETRIES):
        db = None
        try:
            db = db_factory()
            return process_job(db, job)
        except Exception as exc:
            last_exc = exc
            logger.warning("shadow job attempt %d failed: %s", attempt + 1, repr(exc)[:120])
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception as _ce:
                    logger.debug("shadow db.close failed: %s", repr(_ce)[:80])
    stats["errors"] += 1
    _dead_letter(redis, raw, repr(last_exc)[:200] if last_exc else "unknown")
    stats["dead_lettered"] += 1
    return None


def _dead_letter(redis, raw, reason: str) -> None:
    entry = json.dumps({"raw": raw if isinstance(raw, str) else str(raw), "reason": reason})
    try:
        # R10.4b: DLQ is a stream (durable, XRANGE-replayable); list fallback for clients
        # without stream support — same degradation ladder as the producer.
        try:
            redis.xadd(DEADLETTER_STREAM, {"entry": entry}, maxlen=2000, approximate=True)
            return
        except (AttributeError, TypeError) as exc:
            logger.debug("no stream DLQ support (%s) → list", type(exc).__name__)
        redis.lpush(DEADLETTER_KEY, entry)
    except Exception as exc:
        logger.error("dead-letter push failed: %s", repr(exc)[:100])


def _default_db_factory():
    from sqlalchemy.orm import sessionmaker
    from src.app.models.db import get_engine
    return sessionmaker(bind=get_engine())()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--max", type=int, default=None)
    args = ap.parse_args()
    from src.app.deps import _create_redis_client
    redis = _create_redis_client()
    if redis is None:
        raise SystemExit("no redis available — shadow worker needs redis")
    stats = run(redis, _default_db_factory, once=args.once, max_jobs=args.max)
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
