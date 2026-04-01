from typing import Any, Dict, Optional
import os
import json
import logging
import time

import requests
from src.app.security.safe_requests import safe_post

logger = logging.getLogger("shopsquire.telemetry")
try:
    from src.app.observability.redaction import sanitize_event_payload, hash_fields
except Exception:
    sanitize_event_payload = None  # type: ignore
    hash_fields = None  # type: ignore
try:
    from src.app.security.atlas_map import enrich_security_event
except Exception:
    enrich_security_event = None  # type: ignore


def _splunk_hec_payload(event: Dict[str, Any], sourcetype: str = "shopsquire:event") -> Dict[str, Any]:
    body = {
        "time": int(time.time()),
        "sourcetype": sourcetype,
        "event": event,
    }
    return body


def telemetry_emit(
    event: Dict[str, Any],
    severity: str = "info",
    sourcetype: str = "shopsquire:event",
    dry_run: Optional[bool] = None,
) -> None:
    """Emit a structured telemetry event.

    Primary sink is Splunk HEC if `SPLUNK_HEC_URL` and `SPLUNK_HEC_TOKEN` are set.
    Falls back to local logging. This is a lightweight helper meant for
    application-level audit/telemetry events.

    Args:
        event: arbitrary serializable map describing the event.
        severity: one of 'debug','info','warning','error'.
        sourcetype: Splunk sourcetype string.
        dry_run: if True, do not send to remote; if None, follow env var `TELEMETRY_DRY_RUN`.
    """
    try:
        if dry_run is None:
            dry_run = os.getenv("TELEMETRY_DRY_RUN", "0") in ("1", "true", "yes")

        # sanitize + hash select identifiers (resource_id/email if present)
        safe_event = event
        try:
            if hash_fields is not None:
                safe_event = hash_fields(safe_event, ["resource_id", "email", "actor_id"])
        except Exception:
            pass
        try:
            if sanitize_event_payload is not None:
                safe_event = sanitize_event_payload(safe_event)
        except Exception:
            pass
        # enrich event minimally
        if enrich_security_event is not None:
            try:
                event_for_enrichment = dict(safe_event) if isinstance(safe_event, dict) else {"event": safe_event}
                if "security" in str(sourcetype or "").lower() or isinstance((event_for_enrichment.get("details") if isinstance(event_for_enrichment, dict) else None), dict):
                    safe_event = enrich_security_event(event_for_enrichment)
            except Exception:
                pass
        payload = {"severity": severity, "payload": safe_event}

        # Try OpenTelemetry event (best-effort)
        try:
            from opentelemetry import trace  # type: ignore

            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span("telemetry_emit"):
                tracer.add_event("telemetry_emit", payload)
        except Exception:
            pass

        # Splunk HEC
        hec_url = os.getenv("SPLUNK_HEC_URL")
        hec_token = os.getenv("SPLUNK_HEC_TOKEN")
        # Skip HEC posting entirely in pytest runs to avoid hanging on
        # unreachable test addresses (e.g. 127.0.0.1:1 in unit tests).
        _in_pytest = "PYTEST_CURRENT_TEST" in os.environ
        _hec_timeout = float(os.getenv("SPLUNK_HEC_TIMEOUT_SEC", "5") or 5)
        if hec_url and hec_token and not dry_run and not _in_pytest:
            try:
                headers = {"Authorization": f"Splunk {hec_token}", "Content-Type": "application/json"}
                body = _splunk_hec_payload(payload, sourcetype=sourcetype)
                safe_post(hec_url, headers=headers, data=json.dumps(body), timeout=_hec_timeout)
            except Exception as exc:
                logger.exception("Failed sending telemetry to Splunk HEC: %s", exc)
                logger.info("Telemetry event fallback: %s", json.dumps(payload))
        # Datadog (optional)
        dd_api_key = os.getenv("DD_API_KEY") or os.getenv("DATADOG_API_KEY")
        dd_site = os.getenv("DD_SITE", "datadoghq.com")
        if dd_api_key and not dry_run:
            try:
                title = f"shopsquire:{sourcetype}:{severity}"
                text = json.dumps(safe_event, ensure_ascii=False)
                dd_url = f"https://api.{dd_site}/api/v1/events?api_key={dd_api_key}"
                dd_body = {
                    "title": title,
                    "text": text,
                    "priority": "normal" if severity in ("info", "debug") else "normal",
                    "tags": [f"severity:{severity}", f"sourcetype:{sourcetype}"],
                }
                safe_post(dd_url, headers={"Content-Type": "application/json"}, data=json.dumps(dd_body), timeout=5)
            except Exception as exc:
                logger.exception("Failed sending telemetry to Datadog: %s", exc)
        # fallback local logging for dev/test
        try:
            logger.info("Telemetry event (local): %s", json.dumps(payload))
        except Exception:
            pass
    except Exception:
        # never raise telemetry failures into application flows
        logger.exception("telemetry_emit fatal error")
