from __future__ import annotations

import os
import time
from typing import Any, Dict, Tuple

from src.app.deps import get_redis


def _enabled() -> bool:
    return str(os.getenv("REFUND_AGG_WINDOW_ENABLED", "1") or "1").strip().lower() in ("1", "true", "yes", "on")


def _window_seconds() -> int:
    try:
        return max(60, int(float(os.getenv("REFUND_AGG_WINDOW_SECONDS", "3600") or 3600)))
    except Exception:
        return 3600


def _max_amount_usd() -> float:
    try:
        return max(0.0, float(os.getenv("REFUND_AGG_MAX_USD_PER_HOUR", "2500") or 2500.0))
    except Exception:
        return 2500.0


def _bucket(now: float | None = None) -> int:
    ts = float(now if now is not None else time.time())
    return int(ts // _window_seconds())


def _parse_amount_usd(params: Dict[str, Any]) -> float:
    amount = params.get("amount") or params.get("amount_usd") or params.get("refund_amount")
    cents = params.get("amount_cents")
    try:
        if cents is not None and str(cents).strip() != "":
            return max(0.0, float(cents) / 100.0)
    except Exception:
        pass
    try:
        if amount is not None and str(amount).strip() != "":
            return max(0.0, float(amount))
    except Exception:
        pass
    return 0.0


def evaluate_refund_aggregate_window(*, actor: str | None, params: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """Track cumulative refund value per actor per hour and decide if HITL is required.

    Returns `(triggered, details)` where triggered=True means aggregated refund
    amount exceeded threshold and caller should escalate to review/HITL.
    """
    if not _enabled():
        return False, {"enabled": False}

    actor_id = str(actor or "anon")
    refund_usd = _parse_amount_usd(params or {})
    if refund_usd <= 0:
        return False, {"enabled": True, "reason": "no_refund_amount"}

    max_usd = _max_amount_usd()
    b = _bucket()
    key = f"refund_agg:usd:{b}:{actor_id}"
    ttl = int(_window_seconds() + 120)

    current = 0.0
    try:
        r = get_redis()
        try:
            cur_raw = r.get(key)
            current = float(cur_raw or 0.0)
        except Exception:
            current = 0.0
        try:
            current = float(r.incrbyfloat(key, float(refund_usd)) or (current + refund_usd))
            r.expire(key, ttl)
        except Exception:
            current = current + refund_usd
    except Exception:
        current = refund_usd

    triggered = current >= max_usd
    return triggered, {
        "enabled": True,
        "bucket": b,
        "actor": actor_id,
        "window_seconds": _window_seconds(),
        "refund_added_usd": round(refund_usd, 2),
        "refund_total_usd": round(current, 2),
        "max_usd": round(max_usd, 2),
    }
