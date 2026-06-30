from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any, Dict

from src.app.services.erp_edi import ERPEDIConnector
from src.app.services.notifications import NotificationService
from src.app.services.shipping_providers import get_default_shipping_provider
from src.app.services.secrets_manager import get_secret
import time

_REDIS_CLIENT = None

def _get_redis_client():
    global _REDIS_CLIENT
    if _REDIS_CLIENT is not None:
        return _REDIS_CLIENT
    try:
        from src.app.services.redis_factory import create_redis_client
        _REDIS_CLIENT = create_redis_client()
        return _REDIS_CLIENT
    except Exception:
        return None


def _run_async(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        # Running inside an event loop (e.g., test runtime): execute in a dedicated thread.
        import threading

        out: Dict[str, Any] = {"value": None, "error": None}

        def _worker():
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                out["value"] = loop.run_until_complete(coro)
            except Exception as exc:  # pragma: no cover - defensive
                out["error"] = exc
            finally:
                try:
                    loop.close()
                except Exception:
                    pass

        th = threading.Thread(target=_worker, daemon=True)
        th.start()
        th.join(timeout=20)
        if out.get("error") is not None:
            raise out["error"]  # type: ignore[misc]
        return out.get("value")


def _send_via_smtp(*, to: str, subject: str, body: str) -> Dict[str, Any]:
    host = str(get_secret("SMTP_HOST", "") or "").strip()
    port = int(str(get_secret("SMTP_PORT", "587") or "587") or 587)
    user = str(get_secret("SMTP_USER", "") or "").strip()
    password = str(get_secret("SMTP_PASSWORD", "") or "").strip()
    sender = str(get_secret("SMTP_SENDER", user or "noreply@shopsquire.local") or (user or "noreply@shopsquire.local"))
    if not host:
        return {"ok": False, "reason": "smtp_not_configured"}
    try:
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
        return {"ok": True, "provider": "smtp", "to": to}
    except Exception as exc:
        return {"ok": False, "reason": str(exc), "provider": "smtp"}


def email_action(action: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    to = str(params.get("to") or context.get("email") or "").strip()
    subject = str(params.get("subject") or "ShopSquire notification")
    body = str(params.get("body") or json.dumps(params.get("payload") or {}, ensure_ascii=False))
    if not to:
        return {"ok": False, "reason": "missing_recipient"}
    provider = str(os.getenv("EMAIL_PROVIDER", "notification_service")).lower()
    if provider == "smtp":
        out = _send_via_smtp(to=to, subject=subject, body=body)
        return out
    # Default provider-backed path: NotificationService -> SES when configured.
    svc = NotificationService()
    event = str(params.get("event") or "analysis_complete")
    payload = dict(context or {})
    payload.update(
        {
            "customer_email": to,
            "case_id": str(params.get("case_id") or context.get("case_id") or "N/A"),
            "ai_summary": str(params.get("ai_summary") or "Action completed"),
            "next_action": str(params.get("next_action") or "No action required"),
            "track_url": str(params.get("track_url") or ""),
            "label_url": str(params.get("label_url") or ""),
        }
    )
    _run_async(svc.send_notification(event=event, context=payload, channels=["email"]))
    return {"ok": True, "provider": "notification_service", "event": event, "to": to}


def shipping_action(action: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    case_id = str(params.get("case_id") or context.get("case_id") or f"case-{uuid.uuid4().hex[:8]}")
    try:
        provider = get_default_shipping_provider()
    except (RuntimeError, Exception) as exc:
        # Honest: a missing provider is NOT a success. Surface stub=True, ok=False.
        return {"ok": False, "provider": "stub", "case_id": case_id, "stub": True,
                "note": str(exc)[:120]}
    shipment_info = {"case_id": case_id, "from_address": params.get("from_address"), "to_address": params.get("to_address"), "parcel": params.get("parcel")}
    try:
        label = provider.create_label(shipment_info) or {}
    except Exception as exc:
        label = {"ok": False, "stub": True, "error": str(exc)[:160]}
    ok = bool(label.get("ok"))
    return {"ok": ok, "provider": provider.name, "case_id": case_id,
            "stub": bool(label.get("stub")) or not ok, "label": label}


def erp_action(action: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    order_id = str(params.get("order_id") or context.get("order_id") or "")
    if not order_id:
        return {"ok": False, "reason": "missing_order_id"}
    connector = ERPEDIConnector()
    signals = connector.get_supplier_signals(order_id)
    return {"ok": True, "provider": "erp_edi", "order_id": order_id, "signals": signals}


def ip_block_action(action: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    ip = str(params.get("ip") or context.get("ip") or "").strip()
    duration_min = int(params.get("duration_min", 60) or 60)
    if not ip:
        return {"ok": False, "reason": "missing_ip", "provider": "redis_guard"}
    client = _get_redis_client()
    if client is None:
        return {"ok": False, "reason": "redis_not_configured", "provider": "redis_guard"}
    try:
        key = f"ip_block:{ip}"
        ttl = max(1, duration_min) * 60
        client.set(key, "blocked", ex=ttl, nx=True)
        return {"ok": True, "provider": "redis_guard", "ip": ip, "ttl_sec": ttl, "backoff_ms": 0}
    except Exception as exc:
        return {"ok": False, "reason": str(exc), "provider": "redis_guard"}


def rate_limit_action(action: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    scope = str(params.get("scope") or context.get("scope") or "tenant")
    limit_per_min = int(params.get("limit_per_min", 60) or 60)
    client = _get_redis_client()
    if client is None:
        return {"ok": False, "reason": "redis_not_configured", "provider": "redis_guard"}
    try:
        now = int(time.time())
        window = now // 60
        key = f"rate_limit:{scope}:{window}"
        current = client.incr(key)
        if current == 1:
            client.expire(key, 60)
        exceeded = current > limit_per_min
        return {
            "ok": True,
            "provider": "redis_guard",
            "scope": scope,
            "limit_per_min": limit_per_min,
            "current": current,
            "exceeded": exceeded,
            "backoff_ms": 0,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc), "provider": "redis_guard"}
