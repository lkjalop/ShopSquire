from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict
from src.app.security.atlas_map import enrich_security_event


def _bg(target, *args, **kwargs):
    t = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
    t.start()


def _post_json(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: float = 3.0) -> bool:
    try:
        import httpx

        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, headers=headers, json=payload)
            return 200 <= resp.status_code < 300
    except Exception:
        return False


def emit_to_splunk(event: Dict[str, Any]) -> None:
    """Fire-and-forget emit to Splunk HEC if configured.

    Env: SPLUNK_HEC_URL, SPLUNK_HEC_TOKEN
    """
    url = os.getenv("SPLUNK_HEC_URL")
    token = os.getenv("SPLUNK_HEC_TOKEN")
    if not url or not token:
        return

    def _send():
        payload = {
            "time": event.get("timestamp") or time.time(),
            "sourcetype": "shopsquire:security",
            "source": "shopsquire-api",
            "event": event,
        }
        _post_json(url, {"Authorization": f"Splunk {token}"}, payload)

    _bg(_send)


# CrowdStrike OAuth token cache — module-level for cross-call reuse.
_cs_lock = threading.Lock()
_cs_token: str | None = None
_cs_token_expiry: float = 0.0


def _get_crowdstrike_token(cid: str, csec: str, base: str) -> str | None:
    """Return a valid CrowdStrike bearer token, refreshing if within 60s of expiry."""
    global _cs_token, _cs_token_expiry
    with _cs_lock:
        if _cs_token and time.monotonic() < _cs_token_expiry - 60:
            return _cs_token
        try:
            import httpx

            resp = httpx.post(
                f"{base}/oauth2/token",
                data={"client_id": cid, "client_secret": csec, "grant_type": "client_credentials"},
                timeout=5.0,
            )
            if resp.status_code == 201 or resp.status_code == 200:
                body = resp.json()
                _cs_token = body.get("access_token")
                expires_in = int(body.get("expires_in", 1799))
                _cs_token_expiry = time.monotonic() + expires_in
                return _cs_token
        except Exception:
            pass
        return None


def emit_to_crowdstrike(event: Dict[str, Any]) -> None:
    """Forward security event to CrowdStrike via OAuth2 client-credentials + Events API.

    Env: CROWDSTRIKE_CLIENT_ID, CROWDSTRIKE_CLIENT_SECRET,
         CROWDSTRIKE_API_URL (default https://api.crowdstrike.com),
         CROWDSTRIKE_EVENTS_PATH (default /api/v1/events)
    """
    cid = os.getenv("CROWDSTRIKE_CLIENT_ID")
    csec = os.getenv("CROWDSTRIKE_CLIENT_SECRET")
    base = os.getenv("CROWDSTRIKE_API_URL", "https://api.crowdstrike.com")
    path = os.getenv("CROWDSTRIKE_EVENTS_PATH", "/api/v1/events")
    if not (cid and csec):
        return

    def _send():
        token = _get_crowdstrike_token(cid, csec, base)
        if not token:
            return
        _post_json(
            f"{base}{path}",
            {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            {"resources": [event]},
        )

    _bg(_send)


def emit_security_telemetry(event: Dict[str, Any]) -> None:
    """Persist and queue a canonical security handoff.

    Expect keys: event_id, timestamp, interaction_type, severity, details.
    """
    # Incident lifecycle events are consequences of a security observation.
    # Forwarding them back into the same observer creates an alert/incident loop.
    if str(event.get("event") or "").startswith("security.auto_"):
        return
    try:
        # Ensure JSON-serializable copy
        payload = json.loads(json.dumps(event, ensure_ascii=False))
        payload = enrich_security_event(payload)
    except Exception:
        payload = {"raw": str(event)}
    payload.setdefault("schema_version", "shopsquire.security.v1")
    payload.setdefault("source", "shopsquire_security_observer")
    payload.setdefault("tenant_id", str(event.get("tenant_id") or "default"))
    payload.setdefault("trace_id", event.get("trace_id") or event.get("event_id"))
    from src.app.security.siem_adapter import emit_security_handoff

    emit_security_handoff(payload)
