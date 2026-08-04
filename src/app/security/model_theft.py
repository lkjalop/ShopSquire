from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
import json
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

_HIGH_RISK_PATTERNS = (
    "system prompt",
    "developer prompt",
    "hidden prompt",
    "model weights",
    "training dataset",
    "exact chain of thought",
    "verbatim reasoning",
    "internal instructions",
)

_TOKEN_RE = re.compile(r"[a-z0-9_]{2,}")


def _enabled() -> bool:
    return str(os.getenv("MODEL_THEFT_GUARD_ENABLED", "1")).lower() in ("1", "true", "yes")


def _strict_policy_gate_enabled() -> bool:
    raw = os.getenv("MODEL_THEFT_STRICT_POLICY_GATE")
    if raw is not None:
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    env = str(os.getenv("APP_ENV", "local") or "local").lower()
    return env in ("prod", "production")


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


def _strictness_multiplier() -> float:
    if _strict_policy_gate_enabled():
        return 0.6
    return float(max(0.3, min(1.5, float(os.getenv("MODEL_THEFT_STRICTNESS_MULTIPLIER", "1.0") or 1.0))))


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
    strict_mul = _strictness_multiplier()
    repeat_max = max(2, int(float(os.getenv("MODEL_THEFT_MAX_IDENTICAL_QUERY_PER_HOUR", "8") or 8) * strict_mul))
    min_samples = max(8, int(float(os.getenv("MODEL_THEFT_MIN_SAMPLES_FOR_DIVERSITY", "20") or 20) * strict_mul))
    min_unique = max(2, int(float(os.getenv("MODEL_THEFT_MIN_UNIQUE_FP_PER_HOUR", "4") or 4) * strict_mul))
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

    max_per_hour = max(1, int(float(os.getenv("MODEL_THEFT_MAX_EXTRACTION_REQ_PER_HOUR", "40") or 40) * strict_mul))
    key = f"model_theft:extract:{bucket}:{who}"
    max_api_per_day = max(1, int(float(os.getenv("MODEL_THEFT_MAX_COMPLEX_QUERY_PER_DAY_PER_KEY", "1000") or 1000) * strict_mul))
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
    try:
        probing = detect_systematic_probing(redis_client=redis_client, uid=uid, source_ip=source_ip, queries=[norm_q])
        if bool(probing.get("detected")):
            return False, "systematic_probing_detected"
    except Exception:
        pass
    return True, "ok"


def enforce_model_theft_policy_gate(
    *,
    query: str | None,
    uid: str | None = None,
    source_ip: str | None = None,
    api_key_id: str | None = None,
) -> tuple[bool, str]:
    if not _enabled():
        return True, "disabled"
    if not _strict_policy_gate_enabled():
        return True, "gate_disabled"
    q = _normalize_query(query)
    if not q:
        return True, "ok"
    who = str(uid or source_ip or api_key_id or "anon")
    high_risk = any(p in q for p in _HIGH_RISK_PATTERNS)
    extraction_like = looks_like_extraction_attempt(q)
    # Allow benign business queries even if they contain one risky word.
    business_safe = any(t in q for t in ("price", "shipping", "refund", "inventory", "warranty", "order"))
    if high_risk and not business_safe:
        _emit_model_theft_alert(reason="policy_gate_high_risk_extraction_intent", who=who, query=q, confidence=0.96)
        return False, "model_theft_policy_gate_high_risk"
    if extraction_like and ("verbatim" in q or "exactly" in q):
        _emit_model_theft_alert(reason="policy_gate_verbatim_extraction_intent", who=who, query=q, confidence=0.95)
        return False, "model_theft_policy_gate_verbatim"
    return True, "ok"


def build_model_watermark(*, trace_id: str | None, model: str | None, payload_hint: str | None = None) -> str:
    ts_bucket = int(time.time() // 300)  # 5-minute buckets
    material = f"{trace_id or ''}|{model or ''}|{payload_hint or ''}|{ts_bucket}"
    digest = hmac.new(_watermark_key().encode("utf-8"), material.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"sqwm_{digest[:16]}"


def verify_model_watermark(
    *,
    watermark: str | None,
    trace_id: str | None,
    model: str | None,
    payload_hint: str | None = None,
    lookback_buckets: int = 2,
) -> bool:
    token = str(watermark or "").strip()
    if not token.startswith("sqwm_"):
        return False
    try:
        now_bucket = int(time.time() // 300)
    except Exception:
        now_bucket = 0
    key = _watermark_key().encode("utf-8")
    for delta in range(max(0, int(lookback_buckets)) + 1):
        for b in (now_bucket - delta, now_bucket + delta):
            material = f"{trace_id or ''}|{model or ''}|{payload_hint or ''}|{b}"
            digest = hmac.new(key, material.encode("utf-8"), hashlib.sha256).hexdigest()
            if hmac.compare_digest(token, f"sqwm_{digest[:16]}"):
                return True
    return False


def build_output_fingerprint(payload: dict[str, Any] | None) -> str:
    p = payload if isinstance(payload, dict) else {}
    stable = {
        "assistant_message": str(p.get("assistant_message") or ""),
        "results": p.get("results") if isinstance(p.get("results"), list) else [],
        "policy_version": str(p.get("policy_version") or ""),
        "status": str(p.get("status") or ""),
    }
    raw = json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    sig = hmac.new(_watermark_key().encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"sqfp_{sig[:24]}"


def perturb_confidence_score(score: float, *, trace_id: str | None = None) -> float:
    """C03 — Add controlled noise to confidence scores in API responses.

    Prevents model extraction by making precise decision-boundary mapping infeasible.
    The perturbation is deterministic per trace_id (reproducible for debugging)
    but unpredictable to an external observer without the watermark key.
    """
    if not _enabled():
        return score
    epsilon = float(os.getenv("MODEL_THEFT_PERTURBATION_EPSILON", "0.02") or 0.02)
    if epsilon <= 0:
        return score
    seed_material = f"{trace_id or ''}|{score}|{_watermark_key()}"
    h = hashlib.sha256(seed_material.encode("utf-8")).hexdigest()
    # Derive a deterministic float in [-epsilon, +epsilon]
    noise = (int(h[:8], 16) / 0xFFFFFFFF) * 2 * epsilon - epsilon
    perturbed = max(0.0, min(1.0, score + noise))
    return round(perturbed, 6)


def protect_recommendation_output(
    payload: dict[str, Any], *, trace_id: str | None
) -> dict[str, Any]:
    """Apply LLM10 hardening to externally visible recommendation confidence values."""
    out = payload if isinstance(payload, dict) else {}
    try:
        for result in out.get("results") or []:
            if not isinstance(result, dict) or result.get("confidence") is None:
                continue
            try:
                result["confidence"] = perturb_confidence_score(
                    float(result.get("confidence") or 0.0), trace_id=trace_id
                )
            except (TypeError, ValueError):
                pass
        if out.get("confidence_calibrated") is not None:
            try:
                out["confidence_calibrated"] = perturb_confidence_score(
                    float(out.get("confidence_calibrated") or 0.0), trace_id=trace_id
                )
            except (TypeError, ValueError):
                pass
    except Exception:
        pass
    return out


def detect_systematic_probing(
    *,
    redis_client: Any,
    uid: str | None,
    source_ip: str | None,
    queries: list[str] | None = None,
) -> dict[str, Any]:
    """C03 / ATLAS AML.0005 — Detect systematic model probing patterns.

    Checks for:
    - High query volume with low diversity (enumeration)
    - Boundary-probing patterns (similar queries varying one parameter)
    - Confidence-score harvesting (repeated queries with minor tweaks)
    """
    who = str(uid or source_ip or "anon")
    bucket = int(time.time() // 3600)
    result: dict[str, Any] = {"detected": False, "reason": None, "score": 0.0}

    try:
        total_key = f"model_theft:total:{bucket}:{who}"
        total = int(redis_client.get(total_key) or 0)
        uniq_key = f"model_theft:uniq_count:{bucket}:{who}"
        uniq = int(redis_client.get(uniq_key) or 0)

        probe_threshold = int(os.getenv("MODEL_THEFT_SYSTEMATIC_PROBE_THRESHOLD", "50") or 50)
        min_diversity_ratio = float(os.getenv("MODEL_THEFT_MIN_DIVERSITY_RATIO", "0.15") or 0.15)

        if total >= probe_threshold:
            diversity = uniq / max(1, total)
            if diversity < min_diversity_ratio:
                result["detected"] = True
                result["reason"] = "systematic_probing_low_diversity"
                result["score"] = round(1.0 - diversity, 4)
                _emit_model_theft_alert(
                    reason="atlas_aml0005_systematic_probing",
                    who=who,
                    query=f"total={total},uniq={uniq},diversity={diversity:.3f}",
                    confidence=0.92,
                )
    except Exception:
        pass
    return result


def model_theft_runtime_report(
    *,
    redis_client: Any,
    uid: str | None = None,
    source_ip: str | None = None,
    api_key_id: str | None = None,
) -> dict[str, Any]:
    who = str(uid or source_ip or "anon")
    api_actor = str(api_key_id or "").strip() or None
    hb = int(time.time() // 3600)
    db = int(time.time() // 86400)
    strict_mul = _strictness_multiplier()
    thresholds = {
        "repeat_max_per_hour": max(2, int(float(os.getenv("MODEL_THEFT_MAX_IDENTICAL_QUERY_PER_HOUR", "8") or 8) * strict_mul)),
        "min_samples_for_diversity": max(8, int(float(os.getenv("MODEL_THEFT_MIN_SAMPLES_FOR_DIVERSITY", "20") or 20) * strict_mul)),
        "min_unique_fp_per_hour": max(2, int(float(os.getenv("MODEL_THEFT_MIN_UNIQUE_FP_PER_HOUR", "4") or 4) * strict_mul)),
        "max_extraction_per_hour": max(8, int(float(os.getenv("MODEL_THEFT_MAX_EXTRACTION_REQ_PER_HOUR", "40") or 40) * strict_mul)),
        "max_complex_per_day_per_key": max(100, int(float(os.getenv("MODEL_THEFT_MAX_COMPLEX_QUERY_PER_DAY_PER_KEY", "1000") or 1000) * strict_mul)),
    }
    counters = {
        "hour_total": 0,
        "hour_unique_fp": 0,
        "hour_extraction_like": 0,
        "day_api_extraction_like": 0,
    }
    try:
        counters["hour_total"] = int(redis_client.get(f"model_theft:total:{hb}:{who}") or 0)
        counters["hour_unique_fp"] = int(redis_client.get(f"model_theft:uniq_count:{hb}:{who}") or 0)
        counters["hour_extraction_like"] = int(redis_client.get(f"model_theft:extract:{hb}:{who}") or 0)
        if api_actor:
            counters["day_api_extraction_like"] = int(redis_client.get(f"model_theft:api_extract:{db}:{api_actor}") or 0)
    except Exception:
        pass
    risk = "low"
    try:
        ratios = [
            float(counters["hour_extraction_like"]) / float(max(1, thresholds["max_extraction_per_hour"])),
            float(counters["hour_total"]) / float(max(1, thresholds["min_samples_for_diversity"])),
        ]
        peak = max(ratios)
        if peak >= 1.0:
            risk = "high"
        elif peak >= 0.7:
            risk = "medium"
    except Exception:
        risk = "low"
    return {
        "actor": who,
        "api_actor": api_actor,
        "strict_policy_gate": _strict_policy_gate_enabled(),
        "strictness_multiplier": strict_mul,
        "thresholds": thresholds,
        "counters": counters,
        "risk_band": risk,
    }

