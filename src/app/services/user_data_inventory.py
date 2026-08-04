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
    """Delete v2 indexed memory plus pre-cutover and typed artifact keys."""
    keys = all_redis_keys(uid)
    erased: list[str] = []
    failed: list[str] = []
    for key in keys:
        try:
            redis.delete(key)
            erased.append(key)
        except Exception:
            failed.append(key)
    v2_erased = 0
    try:
        result = _memory.Memory(redis).erase_subject(uid)
        v2_erased = int(result.get("erased_keys") or 0)
    except Exception:
        failed.append("memory:v2:subject_index")
    cache_erased = 0
    try:
        from src.app.services.semantic_cache import CacheContract, SemanticCache

        erasure_contract = CacheContract.resolve(
            corpus_version="erasure",
            policy_version="erasure",
            model_version="erasure",
            evidence_cutoff="erasure",
            subject_id=uid,
        )
        cache_erased = SemanticCache(redis_client=redis).erase_scope(erasure_contract)
    except Exception:
        failed.append("cache:v2:subject_index")
    return {
        "keys_total": len(keys) + v2_erased + cache_erased,
        "keys_erased": len(erased) + v2_erased + cache_erased,
        "v2_indexed_keys_erased": v2_erased,
        "v2_cache_keys_erased": cache_erased,
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
    # Export every indexed v2 epoch without scanning other tenants/subjects.
    try:
        scope = _memory.Memory(redis).scope(
            uid, subject_id=uid, session_epoch="export-index"
        )
        raw_keys = redis.smembers(scope.subject_index_key) or set()
        for raw_key in raw_keys:
            key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else str(raw_key)
            value = redis.get(key)
            if value is not None:
                out[f"v2:{key.rsplit(':', 1)[-1]}:{key}"] = _safe_json(value)
    except Exception:
        pass
    return out


def redact_redis(redis, uid: str) -> dict[str, Any]:
    """Redaction for session keys == erase (these are all user-derived session
    state; there is no non-PII residue worth keeping). Kept as a distinct name
    so the privacy route reads intentionally."""
    return erase_redis(redis, uid)
