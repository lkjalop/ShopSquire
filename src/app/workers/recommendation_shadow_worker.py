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

QUEUE_KEY = "shadow:core:queue"
DEADLETTER_KEY = "shadow:core:deadletter"
_MAX_RETRIES = 3
_BRPOP_TIMEOUT_S = 5


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


def process_job(db, job: Dict[str, Any]) -> Dict[str, Any]:
    """Run V2 for one shadow job, diff against V1-from-trace, return the scorecard row.
    Pure except for the read-only DB + metrics; never raises (caller handles retry)."""
    from src.app.services.recommend_parity_full import diff_responses, evaluate_case, message_class
    from src.app.services.recommendation_core.core import recommend_turn
    from src.app.services.recommendation_core.envelope import TurnEnvelope
    from src.app.services.recommendation_core.legacy_adapter import to_legacy

    env = TurnEnvelope.from_suggest_params(
        query=job.get("query", ""), uid=job.get("uid", ""),
        tenant_id=job.get("tenant_id", "default"), budget_min=job.get("budget_min"),
        budget_max=job.get("budget_max"), trace_id=job.get("trace_id"))
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
    except Exception:
        pass
    logger.info("shadow %s", json.dumps(row))


def run(redis, db_factory, *, once: bool = False, max_jobs: Optional[int] = None) -> Dict[str, int]:
    """Drain loop. db_factory() → a fresh read Session per job (short-lived, no cross-job state).
    once=True processes whatever is queued then stops (for tests/CI)."""
    stats = {"processed": 0, "diffed": 0, "dead_lettered": 0, "errors": 0}
    while True:
        item = None
        try:
            popped = redis.brpop(QUEUE_KEY, timeout=_BRPOP_TIMEOUT_S)
            item = popped[1] if popped else None
        except Exception as exc:
            logger.warning("brpop failed: %s", repr(exc)[:100])
        if item is None:
            if once:
                break
            continue
        try:
            job = json.loads(item)
        except Exception:
            _dead_letter(redis, item, "unparseable")
            stats["dead_lettered"] += 1
            continue
        row = _process_with_retry(redis, db_factory, job, item, stats)
        if row and row.get("diffed"):
            stats["diffed"] += 1
        stats["processed"] += 1
        if max_jobs and stats["processed"] >= max_jobs:
            break
    return stats


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
                except Exception:
                    pass
    stats["errors"] += 1
    _dead_letter(redis, raw, repr(last_exc)[:200] if last_exc else "unknown")
    stats["dead_lettered"] += 1
    return None


def _dead_letter(redis, raw, reason: str) -> None:
    try:
        redis.lpush(DEADLETTER_KEY, json.dumps({"raw": raw if isinstance(raw, str) else str(raw),
                                                "reason": reason}))
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
