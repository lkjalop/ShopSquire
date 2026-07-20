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
_ATTEMPT_PREFIX = "shadow:core:attempt:"           # review-9-followup #4: attempt counter,
_DONE_PREFIX = "shadow:core:done:"                 # #5: idempotency marker — both independent
_KEY_TTL_S = 6 * 3600                               # of XPENDING (which can be unreadable)
_MAX_RETRIES = 3
_BRPOP_TIMEOUT_S = 5
_CLAIM_IDLE_MS = 60_000    # a pending entry idle >60s = its consumer died → reclaim it
_MAX_DELIVERIES = 4        # deliveries beyond this = poison (crashes the worker each time)
_MAX_CLAIM_PER_CYCLE = 8   # bound the reclaim batch so a stale backlog can't starve new work
_MAX_NEW_PER_CYCLE = 8

# typed per-job outcomes (review-9-followup #2): only PROCESSED/DEAD_LETTERED/DUPLICATE may be
# ACKed; RETRY leaves the entry pending for redelivery (durable output was NOT guaranteed).
_PROCESSED, _DEAD_LETTERED, _DUPLICATE, _RETRY = "PROCESSED", "DEAD_LETTERED", "DUPLICATE", "RETRY"


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

    # SERVER-SIDE authorization on the SOAK path (review-9-followup #A2): the SAME evaluator the
    # offline gate uses, so soak metrics and the promotion gate agree. A shown product that is
    # phantom/inactive/unsold, or an UNMEASURED check, surfaces in the soak, not just the replay.
    from src.app.services.recommendation_core.quality import catalog_authorization
    shown_skus = [str(p.get("sku")) for p in (v2.get("products") or [])
                  if isinstance(p, dict) and p.get("sku")]
    authz = catalog_authorization(db, shown_skus, tenant_id=env.tenant_id)

    v1_products = _v1_products_from_trace(db, job.get("trace_id"))
    row: Dict[str, Any] = {
        "trace_id": job.get("trace_id"), "lane": core.lane, "grounding": core.grounding,
        "v2_products": len(core.products), "v2_class": message_class(v2),
        "degraded": bool(core.degraded), "latency_ms": latency_ms, "diffed": False,
        "authz_violations": authz["violations"], "authz_measured": authz["measured"],
        "shown_classified": authz["classified"],
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
            "product_count": row.get("v2_products"),
            "authz_violations": row.get("authz_violations"),
            "authz_measured": row.get("authz_measured"),
            "shown_classified": row.get("shown_classified")})
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
    """[(msg_id, payload_json_or_None)] — a BOUNDED batch of reclaimed stale pending entries
    (dead-consumer recovery via XAUTOCLAIM after _CLAIM_IDLE_MS, capped at _MAX_CLAIM_PER_CYCLE
    so a large stale backlog can't STARVE new work — review-9-followup stream-Q1) PLUS a bounded
    batch of new entries. payload is None for a MALFORMED entry (no `payload` field) — the caller
    dead-letters it (review-9-followup #3), never silently skips it into an eternal pending loop.
    At-least-once: nothing leaves the stream until the processor ACKs (+XDELs) it."""
    out: List[tuple] = []
    try:
        try:
            res = redis.xautoclaim(STREAM_KEY, GROUP, consumer, min_idle_time=_CLAIM_IDLE_MS,
                                   start_id="0-0", count=_MAX_CLAIM_PER_CYCLE)
            claimed = res[1] if isinstance(res, (list, tuple)) and len(res) >= 2 else []
        except AttributeError:
            claimed = []                   # pre-6.2 server/client: skip recovery, never crash
        except Exception as exc:
            logger.debug("xautoclaim skipped: %s", repr(exc)[:80])
            claimed = []
        for msg_id, fields in (claimed or [])[:_MAX_CLAIM_PER_CYCLE]:
            out.append((msg_id, _stream_payload(fields)))   # None payload handled downstream
        # ALWAYS also read new (never early-return on claimed — that's the starvation bug)
        # Redis BLOCK 0 means "wait forever", not "nonblocking". Omit BLOCK entirely when
        # reclaimed work already exists or the caller requested a one-shot read; otherwise a
        # crash-recovery cycle processes the pending item and then hangs before returning it.
        read_kwargs = {"count": _MAX_NEW_PER_CYCLE}
        if not out and block_ms > 0:
            read_kwargs["block"] = block_ms
        res = redis.xreadgroup(GROUP, consumer, {STREAM_KEY: ">"}, **read_kwargs)
        for _stream, entries in res or []:
            for msg_id, fields in entries:
                out.append((msg_id, _stream_payload(fields)))
    except Exception as exc:
        logger.debug("stream read failed: %s", repr(exc)[:80])
    return out


def _attempts(redis, key: str) -> int:
    """Deliveries of this job, tracked in a Redis counter INDEPENDENT of XPENDING (review-9-
    followup #4: XPENDING metadata can be unreadable → the old poison check never converged and a
    worker-crashing payload reclaimed forever). INCR is atomic; TTL bounds the keyspace. 1 on the
    first delivery. On a redis error we return _MAX_DELIVERIES+1 → treat unreadable attempt state
    as 'assume poison', NOT infinite retry permission."""
    try:
        n = int(redis.incr(_ATTEMPT_PREFIX + key))
        if n == 1:
            try:
                redis.expire(_ATTEMPT_PREFIX + key, _KEY_TTL_S)
            except Exception as exc:
                logger.debug("attempt-key TTL set skipped: %s", repr(exc)[:60])
        return n
    except AttributeError:
        return 1   # client can't track attempts (DummyRedis / no INCR) — no poison detection,
        #            process once; a client without INCR also has no redelivery to converge on
    except Exception as exc:
        logger.warning("attempt counter unreadable (%s) — treating as poison, not infinite retry",
                       repr(exc)[:80])
        return _MAX_DELIVERIES + 1   # real infra error on a real client = degraded, assume poison


def _is_done(redis, key: str) -> bool:
    try:
        return bool(redis.get(_DONE_PREFIX + key))
    except Exception:
        return False


def _mark_done(redis, key: str) -> None:
    try:
        redis.setex(_DONE_PREFIX + key, _KEY_TTL_S, "1")
    except Exception as exc:
        logger.debug("done-marker set skipped: %s", repr(exc)[:80])


def run(redis, db_factory, *, once: bool = False, max_jobs: Optional[int] = None,
        consumer: str = "worker-1") -> Dict[str, int]:
    """Drain loop. db_factory() → a fresh read Session per job (short-lived, no cross-job state).
    once=True processes whatever is queued then stops (for tests/CI).

    R10.4b: the STREAM is the primary source (consumer group; a job leaves the stream only when
    ACKed AND XDELed AFTER a durable outcome — process succeeded, or dead-lettered durably;
    otherwise it stays pending for XAUTOCLAIM recovery = zero loss on worker crash). Idempotency
    (a `done` marker) makes duplicate delivery a no-op. The legacy LIST is still drained every
    cycle for stream-less clients + pre-upgrade jobs."""
    import time as _time
    stats = {"processed": 0, "diffed": 0, "dead_lettered": 0, "errors": 0, "duplicate": 0}
    streams = _ensure_group(redis)
    while True:
        worked = False
        # ── stream leg (durable) ─────────────────────────────────────────────
        if streams:
            for msg_id, payload in _read_stream_batch(
                    redis, consumer, block_ms=0 if once else _BRPOP_TIMEOUT_S * 1000):
                worked = True
                key = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
                outcome = _handle_one(redis, db_factory, payload, key, stats)
                if outcome != _RETRY:                # PROCESSED / DEAD_LETTERED / DUPLICATE
                    _ack_and_del(redis, msg_id)
                # RETRY → leave pending: durable output was NOT guaranteed, reclaim later
                if max_jobs and stats["processed"] >= max_jobs:
                    return stats
        # ── legacy list leg (fallback + migration) ───────────────────────────
        # non-blocking rpop first — NEVER brpop(timeout=0), which in redis-py blocks FOREVER
        # (the hang class); block 5s only when this whole cycle found no work.
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
            # list jobs have no msg_id → dedup/attempt key from the payload content
            _handle_one(redis, db_factory, item, _payload_key(item), stats)
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


def _ack_and_del(redis, msg_id) -> None:
    """ACK then XDEL — removes the entry from the group PEL and the stream. XDEL-after-ack keeps
    the stream self-cleaning (only un-acked work remains) so NO length-trim is needed on the
    active input stream (review-9-followup #1: MAXLEN could trim un-processed pending work)."""
    try:
        redis.xack(STREAM_KEY, GROUP, msg_id)
    except Exception as exc:
        logger.warning("xack failed (job may redeliver — idempotent on replay): %s", repr(exc)[:80])
        return
    try:
        redis.xdel(STREAM_KEY, msg_id)
    except Exception as exc:
        logger.debug("xdel skipped (acked, harmless): %s", repr(exc)[:80])


def _payload_key(raw: str) -> str:
    import hashlib
    return "l-" + hashlib.sha256((raw or "").encode("utf-8")).hexdigest()[:24]


def _handle_one(redis, db_factory, payload: Optional[str], key: str,
                stats: Dict[str, int]) -> str:
    """One job → a TYPED outcome (review-9-followup #2). ACK is the CALLER's job, gated on this:
      PROCESSED     — ran to completion (marked done, idempotent on replay)
      DEAD_LETTERED — durably recorded in the DLQ (only returned when the DLQ WRITE SUCCEEDED)
      DUPLICATE     — already done (at-least-once redelivery) → ack, no re-processing/re-counting
      RETRY         — durable output NOT guaranteed (DLQ write failed) → do NOT ack, reclaim later
    """
    # idempotency (review-9-followup #5): a redelivered job never double-processes / double-counts
    if _is_done(redis, key):
        stats["duplicate"] += 1
        return _DUPLICATE
    # malformed stream entry (no payload field) — dead-letter, never eternally-pending (#3)
    if payload is None:
        if _dead_letter(redis, "", "malformed_stream_entry"):
            _mark_done(redis, key)
            stats["dead_lettered"] += 1
            return _DEAD_LETTERED
        return _RETRY
    # poison by attempt COUNT (independent of XPENDING — #4): converges even if pending metadata
    # is unreadable, because the counter is bumped every delivery from either leg.
    attempts = _attempts(redis, key)
    if attempts > _MAX_DELIVERIES:
        if _dead_letter(redis, payload, f"poison_delivered_{attempts}x"):
            _mark_done(redis, key)
            stats["dead_lettered"] += 1
            return _DEAD_LETTERED
        return _RETRY
    try:
        job = json.loads(payload)
    except Exception:
        if _dead_letter(redis, payload, "unparseable"):
            _mark_done(redis, key)
            stats["dead_lettered"] += 1
            return _DEAD_LETTERED
        return _RETRY
    row, outcome = _process_with_retry(redis, db_factory, job, payload, stats)
    if outcome == _PROCESSED:
        if row and row.get("diffed"):
            stats["diffed"] += 1
        stats["processed"] += 1
        _mark_done(redis, key)
    elif outcome == _DEAD_LETTERED:
        _mark_done(redis, key)
    return outcome


def _process_with_retry(redis, db_factory, job, raw, stats):
    """Returns (row_or_None, outcome). On success: (row, PROCESSED). On exhausted retries: the
    DLQ write decides — (None, DEAD_LETTERED) if it persisted, else (None, RETRY) so the source
    entry stays pending rather than vanishing un-recorded (review-9-followup #2)."""
    last_exc = None
    for attempt in range(_MAX_RETRIES):
        db = None
        try:
            db = db_factory()
            return process_job(db, job), _PROCESSED
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
    if _dead_letter(redis, raw, repr(last_exc)[:200] if last_exc else "unknown"):
        stats["dead_lettered"] += 1
        return None, _DEAD_LETTERED
    return None, _RETRY


def _dead_letter(redis, raw, reason: str) -> bool:
    """Durably record a failed/poison/malformed job. Returns True only when the write SUCCEEDED
    (the caller uses this to decide whether the source entry may be ACKed — #2). DLQ is a stream
    (XRANGE-replayable); list fallback for stream-less clients."""
    entry = json.dumps({"raw": raw if isinstance(raw, str) else str(raw), "reason": reason})
    try:
        try:
            redis.xadd(DEADLETTER_STREAM, {"entry": entry}, maxlen=5000, approximate=True)
            return True
        except (AttributeError, TypeError) as exc:
            logger.debug("no stream DLQ support (%s) → list", type(exc).__name__)
        redis.lpush(DEADLETTER_KEY, entry)
        return True
    except Exception as exc:
        logger.error("dead-letter push FAILED (job stays pending for retry): %s", repr(exc)[:100])
        return False


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
