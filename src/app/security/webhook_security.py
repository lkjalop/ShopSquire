from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Iterable, Tuple

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from src.app.deps import get_redis
from src.app.security.agent_events import (
    AgentInteractionType,
    ThreatCategory,
    log_agent_security_event,
)
from src.app.observability.metrics import record_webhook_verification


def _normalize_signature(sig: str) -> str:
    if not sig:
        return ""
    if sig.startswith("sha256="):
        return sig.split("=", 1)[1]
    return sig


def _verify_signature(secret: str, payload: bytes, signature: str, timestamp: str) -> bool:
    if not secret or not signature or not timestamp:
        return False
    signed = f"{timestamp}.".encode("utf-8") + payload
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, _normalize_signature(signature))


def _parse_stripe_signature(header: str) -> Tuple[str | None, list[str]]:
    timestamp = None
    signatures: list[str] = []
    for part in (header or "").split(","):
        part = part.strip()
        if part.startswith("t="):
            timestamp = part.split("=", 1)[1]
        elif part.startswith("v1="):
            signatures.append(part.split("=", 1)[1])
    return timestamp, signatures


def _verify_stripe_signature(secret: str, payload: bytes, header: str, tolerance: int) -> bool:
    ts, sigs = _parse_stripe_signature(header)
    if not secret or not ts or not sigs:
        return False
    try:
        ts_int = int(ts)
        if abs(int(time.time()) - ts_int) > tolerance:
            return False
    except Exception:
        return False
    signed = f"{ts}.{payload.decode('utf-8', errors='ignore')}"
    expected = hmac.new(secret.encode("utf-8"), signed.encode("utf-8"), hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in sigs)


def _verify_github_signature(secret: str, payload: bytes, header: str) -> bool:
    if not secret or not header:
        return False
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(_normalize_signature(header), expected)


def _verify_slack_signature(secret: str, payload: bytes, signature: str, timestamp: str, tolerance: int) -> bool:
    if not secret or not signature or not timestamp:
        return False
    try:
        ts_int = int(timestamp)
        if abs(int(time.time()) - ts_int) > tolerance:
            return False
    except Exception:
        return False
    basestring = f"v0:{timestamp}:{payload.decode('utf-8', errors='ignore')}"
    expected = "v0=" + hmac.new(secret.encode("utf-8"), basestring.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


class WebhookSecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, paths: Iterable[str] | None = None):
        super().__init__(app)
        self.secret = os.getenv("WEBHOOK_SECRET", "")
        self.signature_header = os.getenv("WEBHOOK_SIGNATURE_HEADER", "x-webhook-signature").lower()
        self.timestamp_header = os.getenv("WEBHOOK_TIMESTAMP_HEADER", "x-webhook-timestamp").lower()
        self.tolerance_seconds = int(os.getenv("WEBHOOK_TOLERANCE_SECONDS", "300"))
        self.replay_ttl = int(os.getenv("WEBHOOK_REPLAY_TTL_SECONDS", "300"))
        self.enforce_vendor = str(os.getenv("WEBHOOK_ENFORCE_VENDOR_SIGNATURES", "true")).lower() not in ("0", "false", "no")
        self.stripe_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
        self.github_secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
        self.slack_secret = os.getenv("SLACK_WEBHOOK_SECRET", "")
        if paths:
            self.paths = list(paths)
        else:
            self.paths = [
                "/api/v1/orchestrator/events/",
                "/api/v1/admin/connectors/test",
            ]

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not any(path.startswith(p) for p in self.paths):
            return await call_next(request)

        body = await request.body()
        signature = (request.headers.get(self.signature_header) or "").strip()
        timestamp = (request.headers.get(self.timestamp_header) or "").strip()
        stripe_sig = (request.headers.get("stripe-signature") or "").strip()
        github_sig = (request.headers.get("x-hub-signature-256") or "").strip()
        slack_sig = (request.headers.get("x-slack-signature") or "").strip()
        slack_ts = (request.headers.get("x-slack-request-timestamp") or "").strip()
        now = int(time.time())
        webhook_id_hdr = (
            (request.headers.get("x-webhook-id") or "").strip()
            or (request.headers.get("x-event-id") or "").strip()
            or (request.headers.get("x-shopify-webhook-id") or "").strip()
        )
        try:
            ts = int(timestamp) if timestamp else 0
        except Exception:
            ts = 0

        vendor_verified = False
        vendor = None
        if stripe_sig:
            vendor = "stripe"
            if not self.stripe_secret:
                if self.enforce_vendor:
                    record_webhook_verification(vendor, "missing_secret")
                    log_agent_security_event(
                        interaction_type=AgentInteractionType.webhook_received,
                        source=request.client.host if request.client else "unknown",
                        destination=path,
                        threat_category=ThreatCategory.webhook_spoofing,
                        severity="high",
                        confidence=0.8,
                        details={"vendor": "stripe", "reason": "missing_secret"},
                        requires_escalation=True,
                    )
                    raise HTTPException(status_code=401, detail="Missing Stripe webhook secret")
            else:
                if not _verify_stripe_signature(self.stripe_secret, body, stripe_sig, self.tolerance_seconds):
                    record_webhook_verification(vendor, "invalid_signature")
                    log_agent_security_event(
                        interaction_type=AgentInteractionType.webhook_received,
                        source=request.client.host if request.client else "unknown",
                        destination=path,
                        threat_category=ThreatCategory.webhook_spoofing,
                        severity="high",
                        confidence=0.9,
                        details={"vendor": "stripe", "reason": "signature_mismatch"},
                        requires_escalation=True,
                    )
                    raise HTTPException(status_code=401, detail="Invalid Stripe webhook signature")
                vendor_verified = True
        elif github_sig:
            vendor = "github"
            if not self.github_secret:
                if self.enforce_vendor:
                    record_webhook_verification(vendor, "missing_secret")
                    log_agent_security_event(
                        interaction_type=AgentInteractionType.webhook_received,
                        source=request.client.host if request.client else "unknown",
                        destination=path,
                        threat_category=ThreatCategory.webhook_spoofing,
                        severity="high",
                        confidence=0.8,
                        details={"vendor": "github", "reason": "missing_secret"},
                        requires_escalation=True,
                    )
                    raise HTTPException(status_code=401, detail="Missing GitHub webhook secret")
            else:
                if not _verify_github_signature(self.github_secret, body, github_sig):
                    record_webhook_verification(vendor, "invalid_signature")
                    log_agent_security_event(
                        interaction_type=AgentInteractionType.webhook_received,
                        source=request.client.host if request.client else "unknown",
                        destination=path,
                        threat_category=ThreatCategory.webhook_spoofing,
                        severity="high",
                        confidence=0.9,
                        details={"vendor": "github", "reason": "signature_mismatch"},
                        requires_escalation=True,
                    )
                    raise HTTPException(status_code=401, detail="Invalid GitHub webhook signature")
                vendor_verified = True
        elif slack_sig:
            vendor = "slack"
            if not self.slack_secret:
                if self.enforce_vendor:
                    record_webhook_verification(vendor, "missing_secret")
                    log_agent_security_event(
                        interaction_type=AgentInteractionType.webhook_received,
                        source=request.client.host if request.client else "unknown",
                        destination=path,
                        threat_category=ThreatCategory.webhook_spoofing,
                        severity="high",
                        confidence=0.8,
                        details={"vendor": "slack", "reason": "missing_secret"},
                        requires_escalation=True,
                    )
                    raise HTTPException(status_code=401, detail="Missing Slack webhook secret")
            else:
                if not _verify_slack_signature(self.slack_secret, body, slack_sig, slack_ts, self.tolerance_seconds):
                    record_webhook_verification(vendor, "invalid_signature")
                    log_agent_security_event(
                        interaction_type=AgentInteractionType.webhook_received,
                        source=request.client.host if request.client else "unknown",
                        destination=path,
                        threat_category=ThreatCategory.webhook_spoofing,
                        severity="high",
                        confidence=0.9,
                        details={"vendor": "slack", "reason": "signature_mismatch"},
                        requires_escalation=True,
                    )
                    raise HTTPException(status_code=401, detail="Invalid Slack webhook signature")
                vendor_verified = True

        if self.secret and not vendor_verified:
            if not ts or abs(now - ts) > self.tolerance_seconds:
                record_webhook_verification(vendor or "generic", "invalid_timestamp")
                log_agent_security_event(
                    interaction_type=AgentInteractionType.webhook_received,
                    source=request.client.host if request.client else "unknown",
                    destination=path,
                    threat_category=ThreatCategory.webhook_spoofing,
                    severity="high",
                    confidence=0.8,
                    details={"reason": "timestamp_out_of_range"},
                    requires_escalation=True,
                )
                raise HTTPException(status_code=401, detail="Invalid webhook timestamp")

            if not _verify_signature(self.secret, body, signature, timestamp):
                record_webhook_verification(vendor or "generic", "invalid_signature")
                log_agent_security_event(
                    interaction_type=AgentInteractionType.webhook_received,
                    source=request.client.host if request.client else "unknown",
                    destination=path,
                    threat_category=ThreatCategory.webhook_spoofing,
                    severity="high",
                    confidence=0.9,
                    details={"reason": "signature_mismatch"},
                    requires_escalation=True,
                )
                raise HTTPException(status_code=401, detail="Invalid webhook signature")

            # Replay protection using Redis (best-effort)
            try:
                replay_key = f"webhook_replay:{hashlib.sha256((signature + timestamp).encode('utf-8')).hexdigest()}"
                redis = get_redis()
                if redis.get(replay_key):
                    log_agent_security_event(
                        interaction_type=AgentInteractionType.webhook_received,
                        source=request.client.host if request.client else "unknown",
                        destination=path,
                        threat_category=ThreatCategory.webhook_spoofing,
                        severity="high",
                        confidence=0.85,
                        details={"reason": "replay_detected"},
                        requires_escalation=True,
                    )
                    raise HTTPException(status_code=409, detail="Replay detected")
                redis.setex(replay_key, self.replay_ttl, "1")
            except HTTPException:
                raise
            except Exception:
                pass
        elif not vendor_verified:
            record_webhook_verification(vendor or "generic", "skipped")
            log_agent_security_event(
                interaction_type=AgentInteractionType.webhook_received,
                source=request.client.host if request.client else "unknown",
                destination=path,
                threat_category=ThreatCategory.webhook_spoofing,
                severity="warn",
                confidence=0.4,
                details={"reason": "secret_not_configured"},
                requires_escalation=False,
            )
        else:
            record_webhook_verification(vendor or "generic", "ok")
            try:
                replay_sig = stripe_sig or github_sig or slack_sig
                # Some providers (e.g., GitHub) may not send timestamps on every
                # webhook. Use a rolling replay window bucket to avoid false
                # positives across independent runs while still catching quick
                # replays inside TTL.
                replay_ts = slack_ts or (timestamp if timestamp else str(int(time.time() // max(1, self.replay_ttl))))
                body_event_id = ""
                if not webhook_id_hdr:
                    try:
                        import json as _json

                        obj = _json.loads(body.decode("utf-8"))
                        if isinstance(obj, dict):
                            body_event_id = str(
                                obj.get("id")
                                or obj.get("event_id")
                                or obj.get("delivery_id")
                                or obj.get("message_id")
                                or ""
                            ).strip()
                    except Exception:
                        body_event_id = ""
                replay_id = webhook_id_hdr or body_event_id
                replay_material = path + "|" + (vendor or "generic") + "|" + replay_sig + "|" + replay_ts + "|" + replay_id
                replay_key = f"webhook_replay:{hashlib.sha256(replay_material.encode('utf-8')).hexdigest()}"
                redis = get_redis()
                if redis.get(replay_key):
                    log_agent_security_event(
                        interaction_type=AgentInteractionType.webhook_received,
                        source=request.client.host if request.client else "unknown",
                        destination=path,
                        threat_category=ThreatCategory.webhook_spoofing,
                        severity="high",
                        confidence=0.85,
                        details={"vendor": vendor, "reason": "replay_detected"},
                        requires_escalation=True,
                    )
                    raise HTTPException(status_code=409, detail="Replay detected")
                redis.setex(replay_key, self.replay_ttl, "1")
            except HTTPException:
                raise
            except Exception:
                pass

        return await call_next(request)
