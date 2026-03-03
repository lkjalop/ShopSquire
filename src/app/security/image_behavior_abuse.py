from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default)) or default))
    except Exception:
        return int(default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)) or default)
    except Exception:
        return float(default)


def _to_int(v: Any, default: int = 0) -> int:
    try:
        return int(float(v))
    except Exception:
        return int(default)


def _redis_get_int(redis_client: Any, key: str) -> int:
    try:
        return _to_int(redis_client.get(key), 0)
    except Exception:
        return 0


def _redis_incr(redis_client: Any, key: str, ttl_seconds: int) -> int:
    try:
        n = _to_int(redis_client.incrby(key, 1), 0)
    except Exception:
        n = _redis_get_int(redis_client, key) + 1
    try:
        redis_client.expire(key, max(60, int(ttl_seconds)))
    except Exception:
        pass
    return n


def _redis_setex(redis_client: Any, key: str, value: str, ttl_seconds: int) -> None:
    try:
        redis_client.setex(key, max(60, int(ttl_seconds)), value)
    except Exception:
        pass


def _bucket(ts: float | None = None) -> int:
    return int((ts if ts is not None else time.time()) // 60)


def _sum_window(redis_client: Any, prefix: str, entity: str, minutes: int, bucket_now: int) -> int:
    total = 0
    m = max(1, int(minutes))
    for off in range(m):
        total += _redis_get_int(redis_client, f"{prefix}:{entity}:{bucket_now - off}")
    return total


def _is_anonymous_uid(uid: str | None) -> bool:
    s = str(uid or "").strip().lower()
    if not s:
        return True
    return s in {"demo-user", "guest", "anonymous", "anon"} or s.startswith("anon")


def _maybe_count_unique_uid(
    redis_client: Any,
    *,
    dimension: str,
    entity: str,
    uid: str,
    bucket_now: int,
    ttl_seconds: int,
) -> None:
    if not entity or not uid:
        return
    seen_key = f"imgabuse:seen:{dimension}_uid:{entity}:{uid}:{bucket_now}"
    if _redis_get_int(redis_client, seen_key) > 0:
        return
    _redis_setex(redis_client, seen_key, "1", ttl_seconds)
    uniq_key = f"imgabuse:uniq:{dimension}_uid:{entity}:{bucket_now}"
    _redis_incr(redis_client, uniq_key, ttl_seconds)


@dataclass
class ChallengeDecision:
    required: bool
    satisfied: bool
    mode: str | None
    reason: str | None


def _verify_challenge(
    redis_client: Any,
    *,
    uid: str,
    source_ip: str,
    mode: str | None,
    captcha_token: str | None,
    mfa_stepup_token: str | None,
) -> ChallengeDecision:
    if not mode:
        return ChallengeDecision(required=False, satisfied=True, mode=None, reason=None)

    pass_ttl = _env_int("IMAGE_ABUSE_CHALLENGE_PASS_TTL_SECONDS", 1800)
    pass_key = f"imgabuse:challenge_pass:{uid}:{source_ip}:{mode}"
    already = _redis_get_int(redis_client, pass_key) > 0
    if already:
        return ChallengeDecision(required=True, satisfied=True, mode=mode, reason="prior_challenge_pass")

    satisfied = False
    reason = "challenge_required"
    if mode == "captcha":
        expected = str(os.getenv("IMAGE_UPLOAD_CAPTCHA_TOKEN", "captcha-ok") or "captcha-ok").strip()
        provided = str(captcha_token or "").strip()
        satisfied = bool(expected and provided and expected == provided)
        reason = "captcha_required"
    elif mode == "step_up_auth":
        expected = str(os.getenv("LOCAL_MFA_STEPUP_TOKEN", "stepup-ok") or "stepup-ok").strip()
        provided = str(mfa_stepup_token or "").strip()
        satisfied = bool(expected and provided and expected == provided)
        reason = "mfa_stepup_required"

    if satisfied:
        _redis_setex(redis_client, pass_key, "1", pass_ttl)
    return ChallengeDecision(required=True, satisfied=satisfied, mode=mode, reason=reason)


def evaluate_behavioral_upload_abuse(
    redis_client: Any,
    *,
    uid: str | None,
    source_ip: str | None,
    asn: int | None,
    image_hash: str | None,
    session_id: str | None = None,
    captcha_token: str | None = None,
    mfa_stepup_token: str | None = None,
    now_ts: float | None = None,
) -> Dict[str, Any]:
    """Behavioral image-upload abuse detector backed by Redis sliding windows."""
    uid_s = str(uid or "").strip() or "anonymous"
    ip_s = str(source_ip or "").strip() or "unknown"
    asn_s = str(asn if isinstance(asn, int) else "").strip() or "0"
    hash_s = str(image_hash or "").strip()
    sess_s = str(session_id or "").strip() or "session"
    bkt = _bucket(now_ts)

    window_minutes = _env_int("IMAGE_ABUSE_WINDOW_MINUTES", 10)
    ttl_seconds = max(120, window_minutes * 60 + 120)

    # Sliding-window counters.
    _redis_incr(redis_client, f"imgabuse:uploads:uid:{uid_s}:{bkt}", ttl_seconds)
    _redis_incr(redis_client, f"imgabuse:uploads:ip:{ip_s}:{bkt}", ttl_seconds)
    if asn_s != "0":
        _redis_incr(redis_client, f"imgabuse:uploads:asn:{asn_s}:{bkt}", ttl_seconds)

    _maybe_count_unique_uid(
        redis_client,
        dimension="ip",
        entity=ip_s,
        uid=uid_s,
        bucket_now=bkt,
        ttl_seconds=ttl_seconds,
    )
    if asn_s != "0":
        _maybe_count_unique_uid(
            redis_client,
            dimension="asn",
            entity=asn_s,
            uid=uid_s,
            bucket_now=bkt,
            ttl_seconds=ttl_seconds,
        )

    uid_uploads = _sum_window(redis_client, "imgabuse:uploads:uid", uid_s, window_minutes, bkt)
    ip_uploads = _sum_window(redis_client, "imgabuse:uploads:ip", ip_s, window_minutes, bkt)
    asn_uploads = _sum_window(redis_client, "imgabuse:uploads:asn", asn_s, window_minutes, bkt) if asn_s != "0" else 0
    ip_unique_uids = _sum_window(redis_client, "imgabuse:uniq:ip_uid", ip_s, window_minutes, bkt)
    asn_unique_uids = _sum_window(redis_client, "imgabuse:uniq:asn_uid", asn_s, window_minutes, bkt) if asn_s != "0" else 0

    # Duplicate hash probing (same hash repeated to tune detector thresholds).
    dup_uid = 0
    dup_sess = 0
    if hash_s:
        dup_ttl = _env_int("IMAGE_ABUSE_DUP_HASH_TTL_SECONDS", 900)
        dup_uid = _redis_incr(redis_client, f"imgabuse:dup:uid:{uid_s}:{hash_s}", dup_ttl)
        dup_sess = _redis_incr(redis_client, f"imgabuse:dup:session:{sess_s}:{hash_s}", dup_ttl)

    # Thresholds.
    thr_uid_challenge = _env_int("IMAGE_ABUSE_UID_UPLOADS_CHALLENGE", 18)
    thr_ip_challenge = _env_int("IMAGE_ABUSE_IP_UPLOADS_CHALLENGE", 48)
    thr_asn_challenge = _env_int("IMAGE_ABUSE_ASN_UPLOADS_CHALLENGE", 120)
    thr_dup_challenge = _env_int("IMAGE_ABUSE_DUP_HASH_CHALLENGE", 3)
    thr_ip_sybil_challenge = _env_int("IMAGE_ABUSE_IP_UNIQUE_UIDS_CHALLENGE", 5)
    thr_asn_sybil_challenge = _env_int("IMAGE_ABUSE_ASN_UNIQUE_UIDS_CHALLENGE", 16)
    thr_ip_sybil_escalate = _env_int("IMAGE_ABUSE_IP_UNIQUE_UIDS_ESCALATE", 10)
    thr_asn_sybil_escalate = _env_int("IMAGE_ABUSE_ASN_UNIQUE_UIDS_ESCALATE", 32)
    thr_dup_escalate = _env_int("IMAGE_ABUSE_DUP_HASH_ESCALATE", 8)
    thr_risk_escalate = _env_float("IMAGE_ABUSE_RISK_ESCALATE", 0.82)

    signals: Dict[str, Any] = {
        "window_minutes": window_minutes,
        "uid_uploads": uid_uploads,
        "ip_uploads": ip_uploads,
        "asn_uploads": asn_uploads,
        "ip_unique_uids": ip_unique_uids,
        "asn_unique_uids": asn_unique_uids,
        "duplicate_hash_uid": dup_uid,
        "duplicate_hash_session": dup_sess,
    }

    # Cumulative risk score.
    risk = 0.0
    if uid_uploads >= thr_uid_challenge:
        risk += 0.22
        signals["repeated_upload_abuse"] = True
    if ip_uploads >= thr_ip_challenge:
        risk += 0.18
        signals["ip_volume_spike"] = True
    if asn_uploads >= thr_asn_challenge:
        risk += 0.14
        signals["asn_volume_spike"] = True
    if dup_uid >= thr_dup_challenge or dup_sess >= thr_dup_challenge:
        risk += 0.24
        signals["hash_duplicate_bombing"] = True
    if ip_unique_uids >= thr_ip_sybil_challenge:
        risk += 0.30
        signals["ip_sybil_rotation"] = True
    if asn_unique_uids >= thr_asn_sybil_challenge:
        risk += 0.20
        signals["asn_sybil_rotation"] = True
    risk = min(1.0, max(0.0, risk))

    verdict = "allow"
    reason = "low_behavioral_risk"
    if risk >= 0.45:
        verdict = "challenge"
        reason = "behavioral_threshold_exceeded"
    if ip_unique_uids >= thr_ip_sybil_challenge or asn_unique_uids >= thr_asn_sybil_challenge:
        verdict = "challenge" if verdict == "allow" else verdict
        reason = "sybil_rotation_detected"
    if (
        risk >= thr_risk_escalate
        or ip_unique_uids >= thr_ip_sybil_escalate
        or asn_unique_uids >= thr_asn_sybil_escalate
        or dup_uid >= thr_dup_escalate
        or dup_sess >= thr_dup_escalate
    ):
        verdict = "escalate"
        reason = "coordinated_or_progressive_abuse"

    mode: str | None = None
    if verdict == "challenge":
        mode = "captcha" if _is_anonymous_uid(uid_s) else "step_up_auth"

    challenge = _verify_challenge(
        redis_client,
        uid=uid_s,
        source_ip=ip_s,
        mode=mode,
        captcha_token=captcha_token,
        mfa_stepup_token=mfa_stepup_token,
    )

    if verdict == "challenge" and challenge.satisfied:
        signals["challenge_passed"] = True
        verdict = "allow"
        reason = "challenge_verified"

    actions = {
        "captcha_required": bool(verdict == "challenge" and challenge.mode == "captcha" and not challenge.satisfied),
        "auth_stepup_required": bool(verdict == "challenge" and challenge.mode == "step_up_auth" and not challenge.satisfied),
        "soc_escalate": bool(verdict in {"escalate", "block"}),
        "reupload_needed": False,
    }

    return {
        "verdict": verdict,
        "reason": reason if verdict != "challenge" else (challenge.reason or reason),
        "risk_score": round(float(risk), 4),
        "risk_band": ("high" if risk >= 0.75 else "medium" if risk >= 0.45 else "low"),
        "signals": signals,
        "actions": actions,
        "challenge": {
            "required": bool(challenge.required),
            "satisfied": bool(challenge.satisfied),
            "mode": challenge.mode,
            "reason": challenge.reason,
        },
        "thresholds": {
            "uid_uploads_challenge": thr_uid_challenge,
            "ip_uploads_challenge": thr_ip_challenge,
            "asn_uploads_challenge": thr_asn_challenge,
            "dup_hash_challenge": thr_dup_challenge,
            "ip_unique_uids_challenge": thr_ip_sybil_challenge,
            "asn_unique_uids_challenge": thr_asn_sybil_challenge,
            "ip_unique_uids_escalate": thr_ip_sybil_escalate,
            "asn_unique_uids_escalate": thr_asn_sybil_escalate,
            "dup_hash_escalate": thr_dup_escalate,
            "risk_escalate": thr_risk_escalate,
        },
    }
