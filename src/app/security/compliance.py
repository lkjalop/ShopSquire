from __future__ import annotations

import os
import json
from typing import Any, Dict
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.responses import Response
from src.app.security.pci import contains_pci_data
from src.app.observability.telemetry import telemetry_emit


class ComplianceMiddleware:
    """Request-scoped compliance middleware.

    - Detects PCI data in incoming payloads for payment routes and raises a flag.
    - Attaches a lightweight compliance object to `scope['compliance']` for downstream handlers.
    - Emits a Splunk HEC telemetry event `shopsquire:compliance` on high-severity flags.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = (scope.get("path") or "")
        method = (scope.get("method") or "").upper()
        # Build initial compliance object
        comp: Dict[str, Any] = {
            "frameworks": [],
            "flags": [],
        }
        # Basic TLS hint from headers (best-effort)
        headers = {k.decode().lower(): v.decode() for k, v in (scope.get("headers") or [])}
        https_hint = (headers.get("x-forwarded-proto") == "https") or (headers.get("forwarded", "").lower().find("proto=https") >= 0)
        comp["frameworks"].append({
            "name": "pci_dss",
            "status": "partial",
            "controls": [
                {"key": "tls", "status": https_hint},
                {"key": "firewall", "status": True},
            ],
            "last_checked_at": __import__("datetime").datetime.utcnow().isoformat(),
        })
        # PCI DSS 4.0.1 Req 4.2.1 — in production, TLS on the payment surface is ASSERTED, not
        # observed: a payment request that is neither https nor proxy-forwarded-as-https is
        # rejected (override with REQUIRE_TLS_FOR_PAYMENTS=0 only deliberately). Dev stays open.
        # P0-2: decide THEN send — never wrap the whole gate in `except: pass` (that let a plaintext
        # payment request proceed if determining/sending the reject threw). If we cannot determine
        # TLS status, fail CLOSED on the payment surface in prod: reject rather than silently allow.
        try:
            env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
            enforce_tls = str(os.getenv("REQUIRE_TLS_FOR_PAYMENTS", "1")).lower() in ("1", "true", "yes")
            _tls_ok = https_hint or str(scope.get("scheme") or "").lower() == "https"
            _reject_tls = (env in ("production", "prod") and enforce_tls
                           and path.startswith("/api/v1/payments") and not _tls_ok)
        except Exception:
            _reject_tls = (str(os.getenv("APP_ENV", "local") or "local").strip().lower() in ("production", "prod")
                           and str(path or "").startswith("/api/v1/payments"))
        if _reject_tls:
            resp = Response(
                content=json.dumps({"detail": "tls_required", "message": "Payment endpoints require TLS"}),
                status_code=403, media_type="application/json")
            await resp(scope, receive, send)
            return
        # Detect PCI patterns on payment endpoints
        downstream_receive = receive
        try:
            if path.startswith("/api/v1/payments") and method in {"POST", "PUT", "PATCH"}:
                # Buffer the request body for the PAN scan. The receive channel is consumed by
                # this, so downstream MUST be handed a replaying receive (below) — the previous
                # "scope['_body_sender']" approach never replayed anything, which made EVERY
                # customer payment POST hang at body parse until the client timed out.
                body = b""
                chunks = []
                pending: list[dict] = []  # terminal non-body message (e.g. http.disconnect) to replay
                while True:
                    message = await receive()
                    if message["type"] == "http.request":
                        chunk = message.get("body", b"")
                        if chunk:
                            chunks.append(chunk)
                        if not message.get("more_body", False):
                            body = b"".join(chunks)
                            break
                    else:
                        # client disconnected mid-body — stop buffering, replay the event downstream
                        pending.append(message)
                        body = b"".join(chunks)
                        break
                text = body.decode("utf-8", errors="ignore") if body else ""
                if text and contains_pci_data(text):
                    comp.setdefault("flags", []).append({
                        "framework": "pci_dss",
                        "control": "no_storage",
                        "severity": "high",
                        "reason": "pci_data_detected_in_request",
                        "gating_action": "block_payment",
                    })
                    # Emit compliance telemetry (best-effort)
                    try:
                        telemetry_emit({"path": path, "compliance": comp}, severity="warn", sourcetype="shopsquire:compliance")
                    except Exception:
                        pass
                    # PCI DSS 4.0.1 Req 12.10.7: PAN found where it must never be is an INCIDENT
                    # with a response procedure, not a log line. Best-effort; the 422 still fires.
                    try:
                        from src.app.observability.metrics import record_incident_alert
                        record_incident_alert("pci_pan_in_request", "p1")
                    except Exception:
                        pass
                    # Short-circuit with 422 to prevent leakage
                    resp = Response(
                        content=json.dumps({"detail": "pci_data_detected"}),
                        status_code=422,
                        media_type="application/json",
                    )
                    await resp(scope, receive, send)
                    return
                # Clean body: replay it to the app, then any buffered terminal message, then
                # fall through to the live channel (disconnect notifications etc.).
                replay = [{"type": "http.request", "body": body, "more_body": False}] + pending

                async def _replaying_receive():
                    if replay:
                        return replay.pop(0)
                    return await receive()

                downstream_receive = _replaying_receive
        except Exception:
            pass
        # Attach compliance to scope for downstream access
        scope.setdefault("compliance", comp)
        await self.app(scope, downstream_receive, send)
