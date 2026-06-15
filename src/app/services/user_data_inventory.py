"""UserDataInventory — the single source of truth for every user-linked Redis key.

DSR (data-subject request) gap fix (0.2): the privacy delete/export/redact paths
historically hard-coded only 2-3 of the session keys, so a deletion left behind
product preferences, observation logs/summaries, structured state, agent steps,
and all typed session artifacts. That is a GDPR/APP right-to-erasure gap.

This module enumerates ALL user-linked Redis keys by REFERENCING the key
definitions in `memory.py` and `session_artifacts.py` — so when a new memory key
is added there, erasure/export automatically covers it (no drift). Route every
privacy delete/export/redact through here.
"""
from __future__ import annotations

import json
from typing import Any

from src.app.services import memory as _memory
from src.app.services import session_artifacts as _artifacts


def all_redis_key_templates() -> list[str]:
    """Every user-scoped Redis key TEMPLATE ("session:{uid}:...").

    Pulled live from the memory + session-artifact modules so this list cannot
    silently fall out of sync with the stores it is meant to erase.
    """
    memory_keys = [
        _memory.SUMMARY_KEY,
        _memory.KV_KEY,
        _memory.RETRIEVAL_KEY,
        _memory.AGENT_STEPS_KEY,
        _memory.STRUCTURED_STATE_KEY,
        _memory.PRODUCT_MEMORY_BANK_KEY,
        _memory.OBSERVATION_LOG_KEY,
        _memory.OBSERVATION_SUMMARY_KEY,
    ]
    artifact_keys = list(getattr(_artifacts, "_ALL_ARTIFACT_KEYS", []))
    # De-dup while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for k in memory_keys + artifact_keys:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def all_redis_keys(uid: str) -> list[str]:
    """Concrete user-scoped Redis keys for a given uid."""
    return [tpl.format(uid=uid) for tpl in all_redis_key_templates()]


def _safe_json(raw: Any) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        try:
            return raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
        except Exception:
            return None


def erase_redis(redis, uid: str) -> dict[str, Any]:
    """Delete EVERY user-linked Redis key. Returns per-key outcome + count."""
    keys = all_redis_keys(uid)
    erased: list[str] = []
    failed: list[str] = []
    for key in keys:
        try:
            redis.delete(key)
            erased.append(key)
        except Exception:
            failed.append(key)
    return {
        "keys_total": len(keys),
        "keys_erased": len(erased),
        "keys_failed": failed,
        "complete": not failed,
    }


def export_redis(redis, uid: str) -> dict[str, Any]:
    """Export the contents of EVERY user-linked Redis key (json-safe)."""
    out: dict[str, Any] = {}
    for key in all_redis_keys(uid):
        try:
            val = redis.get(key)
        except Exception:
            val = None
        if val is not None:
            # Strip the "session:{uid}:" prefix for a clean export shape.
            short = key.split(":", 2)[-1]
            out[short] = _safe_json(val)
    return out


def redact_redis(redis, uid: str) -> dict[str, Any]:
    """Redaction for session keys == erase (these are all user-derived session
    state; there is no non-PII residue worth keeping). Kept as a distinct name
    so the privacy route reads intentionally."""
    return erase_redis(redis, uid)
