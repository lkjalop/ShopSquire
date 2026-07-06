"""Uniform data-retention sweeper — storage limitation (GDPR Art. 5(1)(e)).

Ages out ABANDONED ephemeral state on a schedule so personal data does not linger indefinitely:

  - idle draft carts:  soft-expire (draft -> stale, RECOVERABLE, row kept) then hard-purge (DELETE) at the
                       long horizon.
  - conversation:      chat_messages older than the conversation TTL are deleted.
  - Redis sessions:    session:{uid}:* keys with NO TTL get one, so they self-expire.

DELIBERATELY UNIFORM — this runs the same for every user and is NOT gated on IP / GeoIP / ASN. GDPR scope
is set by establishment + the targeting test (Art. 3), not by a request's IP geolocation; geo-gating would
under-protect travelling/VPN'd EU users, over-apply to non-EU users on EU exits, and force us to process
MORE personal data just to decide who gets privacy. See config/retention_policy.json for the full rationale.

This sweeper never touches committed orders and is the STORAGE-LIMITATION half of compliance; the RIGHT TO
ERASURE (on-request, complete) is a separate mechanism in routers/privacy.py. Reuses cart_ttl's idle notion
and user_data_inventory's key templates so labelling, erasure, and sweeping all agree on the same surfaces.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from sqlalchemy import text as _sql

_CONFIG_PATH = os.path.join("config", "retention_policy.json")

_DEFAULTS: Dict[str, int] = {
    "cart_soft_expire_seconds": 28800,    # 8h  — carried-over cart hidden from the active lookup (recoverable)
    "cart_hard_purge_seconds": 2592000,   # 30d — abandoned cart row deleted
    "session_ttl_seconds": 86400,         # 24h — Redis session keys self-expire
    "conversation_ttl_seconds": 86400,    # 24h — chat history aged out
}


def load_sweeper_config() -> Dict[str, int]:
    """Read the `sweeper` block from retention_policy.json; fall back to defaults (never raise)."""
    cfg = dict(_DEFAULTS)
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        sweeper = (data or {}).get("sweeper") or {}
        for key in _DEFAULTS:
            if sweeper.get(key) is not None:
                cfg[key] = int(sweeper[key])
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError, TypeError):
        pass
    if cfg["cart_hard_purge_seconds"] < cfg["cart_soft_expire_seconds"]:   # guard a mis-edited config
        cfg["cart_hard_purge_seconds"] = cfg["cart_soft_expire_seconds"]
    return cfg


def _cutoff(now: datetime, seconds: int) -> str:
    """A 'YYYY-MM-DD HH:MM:SS' cutoff string — compares lexicographically against the TEXT timestamps
    draft_orders.updated_at / chat_messages.created_at store (both UTC, same format)."""
    return (now - timedelta(seconds=int(seconds))).strftime("%Y-%m-%d %H:%M:%S")


def sweep_carts(db, *, now: datetime, soft_seconds: int, hard_seconds: int, dry_run: bool) -> Dict[str, int]:
    """Hard-purge draft/stale carts idle past the hard horizon; soft-expire (draft -> stale) the rest that
    are idle past the soft horizon. Order matters: hard DELETE first, then soft UPDATE the survivors."""
    hard_cut = _cutoff(now, hard_seconds)
    soft_cut = _cutoff(now, soft_seconds)
    hard_n = db.execute(
        _sql("SELECT COUNT(*) FROM draft_orders WHERE status IN ('draft', 'stale') AND updated_at < :c"),
        {"c": hard_cut},
    ).scalar() or 0
    # soft = draft carts between the soft and hard horizons (the >hard ones are hard-purged, not soft-expired)
    soft_n = db.execute(
        _sql("SELECT COUNT(*) FROM draft_orders WHERE status = 'draft' AND updated_at < :soft AND updated_at >= :hard"),
        {"soft": soft_cut, "hard": hard_cut},
    ).scalar() or 0
    if not dry_run:
        db.execute(
            _sql("DELETE FROM draft_orders WHERE status IN ('draft', 'stale') AND updated_at < :c"),
            {"c": hard_cut},
        )
        db.execute(
            _sql("UPDATE draft_orders SET status = 'stale' WHERE status = 'draft' AND updated_at < :soft"),
            {"soft": soft_cut},
        )
    return {"carts_hard_purged": int(hard_n), "carts_soft_expired": int(soft_n)}


def sweep_conversation(db, *, now: datetime, ttl_seconds: int, dry_run: bool) -> Dict[str, int]:
    """Delete chat_messages older than the conversation TTL."""
    cut = _cutoff(now, ttl_seconds)
    n = db.execute(_sql("SELECT COUNT(*) FROM chat_messages WHERE created_at < :c"), {"c": cut}).scalar() or 0
    if not dry_run:
        db.execute(_sql("DELETE FROM chat_messages WHERE created_at < :c"), {"c": cut})
    return {"chat_messages_purged": int(n)}


def sweep_redis_sessions(redis, *, ttl_seconds: int, dry_run: bool) -> Dict[str, int]:
    """Give every TTL-less session:{uid}:* key an expiry so it self-cleans. Uses the SAME key templates as
    erasure (user_data_inventory), so the two never drift. A DummyRedis / missing client is a no-op."""
    if redis is None or not hasattr(redis, "scan_iter"):
        return {"session_keys_expiring": 0}
    try:
        from src.app.services.user_data_inventory import all_redis_key_templates
        patterns = [tpl.replace("{uid}", "*") for tpl in all_redis_key_templates()]
    except Exception:
        patterns = ["session:*"]
    touched = 0
    for pattern in patterns:
        try:
            for key in redis.scan_iter(match=pattern, count=200):
                if redis.ttl(key) == -1:        # -1 == key exists but has no expiry
                    if not dry_run:
                        redis.expire(key, int(ttl_seconds))
                    touched += 1
        except Exception:
            continue
    return {"session_keys_expiring": touched}


def run_sweep(db=None, redis=None, *, now: Optional[datetime] = None,
              dry_run: bool = False, config: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """Run the full sweep and return a report of counts. dry_run reports what WOULD happen without mutating.

    ``now`` is injectable for deterministic tests. Commits once at the end when a db is provided and this is
    not a dry run. Never raises for a missing db/redis — each surface is swept independently.
    """
    now = now or datetime.utcnow()
    cfg = config or load_sweeper_config()
    report: Dict[str, Any] = {
        "swept_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "dry_run": bool(dry_run),
        "geo_gated": False,   # explicit: retention is uniform, never IP/geo gated
        "windows": cfg,
    }
    if db is not None:
        report.update(sweep_carts(db, now=now, soft_seconds=cfg["cart_soft_expire_seconds"],
                                  hard_seconds=cfg["cart_hard_purge_seconds"], dry_run=dry_run))
        report.update(sweep_conversation(db, now=now, ttl_seconds=cfg["conversation_ttl_seconds"], dry_run=dry_run))
        if not dry_run:
            db.commit()
    report.update(sweep_redis_sessions(redis, ttl_seconds=cfg["session_ttl_seconds"], dry_run=dry_run))
    return report


def sweep_now(dry_run: bool = False) -> Dict[str, Any]:
    """Convenience entrypoint for the scheduled task / admin endpoint / CLI: opens its own db + redis."""
    from src.app.models.db import db_session
    try:
        from src.app.deps import get_redis
        redis = get_redis()
    except Exception:
        redis = None
    with db_session() as db:
        return run_sweep(db, redis, dry_run=dry_run)
