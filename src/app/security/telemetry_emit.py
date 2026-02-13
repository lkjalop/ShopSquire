from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict


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


def emit_to_crowdstrike(event: Dict[str, Any]) -> None:
    """Stub: forward event metadata to CrowdStrike (requires token flow).

    For MVP, just no-op unless CROWDSTRIKE envs are present. In production,
    map to detections or IOC APIs.
    """
    cid = os.getenv("CROWDSTRIKE_CLIENT_ID")
    csec = os.getenv("CROWDSTRIKE_CLIENT_SECRET")
    base = os.getenv("CROWDSTRIKE_API_URL", "https://api.crowdstrike.com")
    if not (cid and csec and base):
        return

    def _send():
        # Minimal placeholder: do nothing but keep shape for future expansion.
        # Could push to a local outbox or metrics.
        return

    _bg(_send)


def emit_security_telemetry(event: Dict[str, Any]) -> None:
    """Emit security event to configured backends.

    Expect keys: event_id, timestamp, interaction_type, severity, details.
    """
    try:
        # Ensure JSON-serializable copy
        payload = json.loads(json.dumps(event, ensure_ascii=False))
    except Exception:
        payload = {"raw": str(event)}
    emit_to_splunk(payload)
    emit_to_crowdstrike(payload)
