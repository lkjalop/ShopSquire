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
        # Detect PCI patterns on payment endpoints
        try:
            if path.startswith("/api/v1/payments") and method in {"POST", "PUT", "PATCH"}:
                # Read the body without consuming downstream by buffering
                body = b""
                more_body = True
                chunks = []
                while more_body:
                    message = await receive()
                    if message["type"] == "http.request":
                        chunk = message.get("body", b"")
                        if chunk:
                            chunks.append(chunk)
                        more_body = message.get("more_body", False)
                        if not more_body:
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
                    # Short-circuit with 422 to prevent leakage
                    resp = Response(
                        content=json.dumps({"detail": "pci_data_detected"}),
                        status_code=422,
                        media_type="application/json",
                    )
                    await resp(scope, receive, send)
                    return
                else:
                    # Re-inject buffered body to downstream
                    async def _body_sender() -> None:
                        await send({"type": "http.request", "body": body, "more_body": False})
                    scope.setdefault("_body_sender", _body_sender)
        except Exception:
            pass
        # Attach compliance to scope for downstream access
        scope.setdefault("compliance", comp)
        await self.app(scope, receive, send)
