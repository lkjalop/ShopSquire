from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from typing import Any


_EXTRACTION_PATTERNS = (
    "repeat your system prompt",
    "print your system prompt",
    "export full prompt",
    "model weights",
    "dump model",
    "recreate this model",
    "training dataset",
    "leak prompt",
    "verbatim output",
)

_TOKEN_RE = re.compile(r"[a-z0-9_]{2,}")


def _enabled() -> bool:
    return str(os.getenv("MODEL_THEFT_GUARD_ENABLED", "1")).lower() in ("1", "true", "yes")


def _watermark_key() -> str:
    return str(os.getenv("MODEL_THEFT_WATERMARK_KEY", "shopsquire-watermark-secret") or "shopsquire-watermark-secret")


def looks_like_extraction_attempt(query: str | None) -> bool:
    q = str(query or "").strip().lower()
    if not q:
        return False
    return any(pat in q for pat in _EXTRACTION_PATTERNS)


def _normalize_query(query: str | None) -> str:
    q = str(query or "").lower().strip()
    q = re.sub(r"\s+", " ", q)
    return q[:4000]


def _query_fingerprint(query: str | None) -> str:
    q = _normalize_query(query)
    toks = sorted(set(_TOKEN_RE.findall(q)))
    base = "|".join(toks[:128])
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]


def _emit_model_theft_alert(*, reason: str, who: str, query: str | None, confidence: float = 0.8) -> None:
    details = {
        "reason": reason,
        "actor": who,
        "query_preview": str(query or "")[:200],
    }
    try:
        from src.app.security.agent_events import (
            AgentInteractionType,
            ThreatCategory,
            log_agent_security_event,
        )

        log_agent_security_event(
            interaction_type=AgentInteractionType.user_input,
            source=who,
            destination="/api/v1/recommend",
            threat_category=ThreatCategory.api_abuse,
            severity="high",
            confidence=float(max(0.0, min(1.0, confidence))),
            details=details,
            requires_escalation=True,
        )
    except Exception:
        pass
    try:
        from src.app.routers.incident import create_ticket

        create_ticket(
            {
                "title": f"LLM10 model-theft signal: {reason}",
                "priority": "high",
                "source": "model_theft_guard",
                "details": details,
            }
        )
    except Exception:
        pass


def enforce_model_theft_rate_limit(
    *,
    redis_client: Any,
    uid: str | None,
    source_ip: str | None,
    query: str | None,
    api_key_id: str | None = None,
) -> tuple[bool, str]:
    if not _enabled():
        return True, "disabled"

    norm_q = _normalize_query(query)
    who = str(uid or source_ip or "anon")
    api_actor = str(api_key_id or "").strip()
    bucket = int(time.time() // 3600)

    # Structural probing controls: repeated near-identical probing and low-diversity
    # enumeration patterns in the same window.
    fp = _query_fingerprint(norm_q)
    repeat_max = int(os.getenv("MODEL_THEFT_MAX_IDENTICAL_QUERY_PER_HOUR", "8") or 8)
    min_samples = int(os.getenv("MODEL_THEFT_MIN_SAMPLES_FOR_DIVERSITY", "20") or 20)
    min_unique = int(os.getenv("MODEL_THEFT_MIN_UNIQUE_FP_PER_HOUR", "4") or 4)
    is_extraction_like = looks_like_extraction_attempt(norm_q)
    try:
        fp_key = f"model_theft:fp:{bucket}:{who}:{fp}"
        total_key = f"model_theft:total:{bucket}:{who}"
        uniq_key = f"model_theft:uniq:{bucket}:{who}:{fp}"

        fp_count = int(redis_client.get(fp_key) or 0) + 1
        redis_client.incrby(fp_key, 1)
        redis_client.expire(fp_key, 3700)

        redis_client.incrby(total_key, 1)
        redis_client.expire(total_key, 3700)

        # We use per-fingerprint presence keys and count active keys by incrementing
        # only on first-seen fp in this bucket.
        if int(redis_client.get(uniq_key) or 0) == 0:
            redis_client.setex(uniq_key, 3700, "1")
            uniq_count_key = f"model_theft:uniq_count:{bucket}:{who}"
            redis_client.incrby(uniq_count_key, 1)
            redis_client.expire(uniq_count_key, 3700)

        total = int(redis_client.get(total_key) or 0)
        uniq_count = int(redis_client.get(f"model_theft:uniq_count:{bucket}:{who}") or 0)

        if fp_count > repeat_max:
            _emit_model_theft_alert(reason="structural_probe_repetition", who=who, query=norm_q, confidence=0.9)
            return False, "structural_probe_repetition"

        if total >= min_samples and uniq_count <= min_unique and is_extraction_like:
            _emit_model_theft_alert(reason="structural_probe_low_diversity", who=who, query=norm_q, confidence=0.88)
            return False, "structural_probe_low_diversity"
    except Exception:
        # Keep availability over strictness when Redis is degraded.
        pass

    if not is_extraction_like:
        return True, "ok"

    max_per_hour = int(os.getenv("MODEL_THEFT_MAX_EXTRACTION_REQ_PER_HOUR", "40") or 40)
    key = f"model_theft:extract:{bucket}:{who}"
    max_api_per_day = int(os.getenv("MODEL_THEFT_MAX_COMPLEX_QUERY_PER_DAY_PER_KEY", "1000") or 1000)
    day_bucket = int(time.time() // 86400)
    try:
        if api_actor:
            day_key = f"model_theft:api_extract:{day_bucket}:{api_actor}"
            day_count = int(redis_client.get(day_key) or 0)
            if day_count >= max_api_per_day:
                _emit_model_theft_alert(reason="api_key_model_extraction_rate_limited", who=api_actor, query=norm_q, confidence=0.94)
                return False, "api_key_model_extraction_rate_limited"
            redis_client.incrby(day_key, 1)
            redis_client.expire(day_key, 90000)

        current = int(redis_client.get(key) or 0)
        if current >= max_per_hour:
            _emit_model_theft_alert(reason="model_extraction_rate_limited", who=who, query=norm_q, confidence=0.95)
            return False, "model_extraction_rate_limited"
        redis_client.incrby(key, 1)
        redis_client.expire(key, 3700)
    except Exception:
        # Fail-open for availability.
        return True, "degraded_allow"
    return True, "ok"


def build_model_watermark(*, trace_id: str | None, model: str | None, payload_hint: str | None = None) -> str:
    ts_bucket = int(time.time() // 300)  # 5-minute buckets
    material = f"{trace_id or ''}|{model or ''}|{payload_hint or ''}|{ts_bucket}"
    digest = hmac.new(_watermark_key().encode("utf-8"), material.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"sqwm_{digest[:16]}"

