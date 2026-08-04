from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any
import logging
import time
from sqlalchemy import text as sql_text

from src.app.models.db import db_session
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_OWNER, ROLE_MERCHANT

logger = logging.getLogger("shopsquire.fraud")
router = APIRouter(prefix="/api/v1/fraud", tags=["fraud"])

# Simple in-memory cache: key -> (ts, value)
_cache: Dict[str, Any] = {}
_CACHE_TTL = 30  # seconds


def _cache_get(key: str):
    rec = _cache.get(key)
    if not rec:
        return None
    ts, val = rec
    if time.time() - ts > _CACHE_TTL:
        try:
            del _cache[key]
        except Exception:
            pass
        return None
    return val


def _cache_set(key: str, val: Any):
    _cache[key] = (time.time(), val)


@router.post("/score")
def score(payload: Dict[str, Any], role: str = Depends(require_role([ROLE_DEVELOPER, ROLE_OWNER, ROLE_MERCHANT]))):
    """Score request for fraud risk.

    payload may include: customer_id, ip, device_fp, image_phash, sku
    Returns: {score, top_signals, version, confidence}
    """
    key = None
    try:
        key = payload.get("customer_id") or payload.get("device_fp") or payload.get("ip")
    except Exception:
        key = None
    if key:
        cached = _cache_get(key)
        if cached:
            return cached

    score = 0
    signals = []
    # FAIL-CLOSED (Track A A3/A4): when a DB-backed fraud check can't run, we CANNOT prove the
    # request is clean — surface `degraded` so the review layer routes to manual review instead of
    # a silently-pristine score. Loud (logged), never a silent `except: pass`.
    degraded = False

    # allowlist/denylist from env
    import os

    deny_ips = [p.strip() for p in os.getenv("FRAUD_DENY_IPS", "").split(",") if p.strip()]
    allow_customers = [p.strip() for p in os.getenv("FRAUD_ALLOW_CUSTOMERS", "").split(",") if p.strip()]

    cid = payload.get("customer_id")
    ip = payload.get("ip")
    device = payload.get("device_fp")
    phash = payload.get("image_phash")

    if cid and cid in allow_customers:
        out = {"score": 0, "top_signals": ["allowlisted_customer"], "version": "v1", "confidence": 0.99}
        if key:
            _cache_set(key, out)
        return out

    if ip and ip in deny_ips:
        score += 90
        signals.append({"signal": "deny_ip", "value": ip})

    # Check image phash against known fraud hashes
    if phash:
        try:
            with db_session() as db:
                res = db.execute(sql_text("SELECT times_seen, confirmed_fraud FROM fraud_image_hashes WHERE phash = :p"), {"p": phash}).fetchone()
                if res:
                    try:
                        ts = res[0]
                        cf = res[1]
                    except Exception:
                        try:
                            ts = res._mapping.get("times_seen")
                            cf = res._mapping.get("confirmed_fraud")
                        except Exception:
                            ts = None
                            cf = None
                    score += 80
                    signals.append({"signal": "image_phash_known", "times_seen": ts, "confirmed": cf})
        except Exception as exc:
            degraded = True
            signals.append({"signal": "image_phash_check_unavailable"})
            logger.error("fraud phash check FAILED — degraded (routes to review): %s", repr(exc)[:120])

    # Device and IP heuristics
    if device:
        if len(device) < 10:
            score += 10
            signals.append({"signal": "weak_device_fp"})
    try:
        if float(payload.get("ip_velocity_per_hour") or 0.0) >= 20.0:
            score += 25
            signals.append({"signal": "ip_velocity_spike", "value": payload.get("ip_velocity_per_hour")})
    except Exception:
        pass
    try:
        if int(payload.get("shipping_address_cluster_size") or 0) >= 4:
            score += 25
            signals.append({"signal": "shipping_address_clustered", "value": payload.get("shipping_address_cluster_size")})
    except Exception:
        pass

    # Customer trust score heuristic
    if cid:
        try:
            with db_session() as db:
                r = db.execute(sql_text("SELECT trust_score FROM customer_trust_scores WHERE customer_id = :c"), {"c": cid}).fetchone()
                if r:
                    try:
                        ts = r[0]
                    except Exception:
                        ts = getattr(r, "_mapping", {}).get("trust_score")
                    if ts is not None and float(ts) < 0.5:
                        score += 30
                        signals.append({"signal": "low_trust_score", "trust_score": ts})
        except Exception as exc:
            degraded = True
            signals.append({"signal": "trust_score_check_unavailable"})
            logger.error("fraud trust-score check FAILED — degraded (routes to review): %s", repr(exc)[:120])

    # Normalize score and compute confidence
    score = min(100, int(score))
    confidence = 0.5 + min(0.5, len(signals) * 0.1)
    # `degraded` = a fraud check couldn't run; a degraded score is NOT a trustworthy 'clean',
    # so it carries reduced confidence and the flag the review layer keys on (fail-closed).
    if degraded:
        confidence = min(confidence, 0.4)
    out = {"score": score, "top_signals": signals, "version": "v1",
           "confidence": round(confidence, 2), "degraded": degraded}
    if key:
        _cache_set(key, out)
    # Audit: write an entry to security_events. Best-effort (the score is already computed) but
    # LOUD on failure (Track A) — a vanished fraud-decision audit row must not be silent.
    try:
        with db_session() as db:
            db.execute(sql_text("INSERT INTO security_events (id, path, severity, details) VALUES (lower(hex(randomblob(16))), :p, :s, :d)"), {"p": "/api/v1/fraud/score", "s": "info", "d": str(out)})
            db.commit()
    except Exception as exc:
        logger.error("fraud audit write failed (score computed, audit lost): %s", repr(exc)[:120])

    return out
