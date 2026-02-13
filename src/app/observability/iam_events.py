from __future__ import annotations

from typing import Any, Dict, List, Optional
import uuid
import time

from src.app.observability.telemetry import telemetry_emit
try:
    from src.app.observability.redaction import hash_fields
except Exception:
    def hash_fields(ev: Dict[str, Any], fields: List[str]) -> Dict[str, Any]:
        return ev


def emit_iam_activity(
    action: str,
    outcome: str,
    subject: Dict[str, Any],
    resource: Dict[str, Any],
    risk: str = "low",
    tags: Optional[List[str]] = None,
    correlation_id: Optional[str] = None,
) -> None:
    """Emit a sanitized IAM activity event via telemetry_emit.

    Args:
        action: e.g., 'authn_check', 'authz_check', 'access_granted'.
        outcome: 'granted', 'denied', 'missing', 'invalid'.
        subject: map with actor_id, role, tenant_id.
        resource: map with path, method, target_role, scope.
        risk: 'low' | 'medium' | 'high'.
        tags: optional list of classification tags.
        correlation_id: optional correlation identifier.
    """
    try:
        cid = correlation_id or str(uuid.uuid4())
        evt: Dict[str, Any] = {
            "type": "iam_activity",
            "action": action,
            "outcome": outcome,
            "actor_id": subject.get("actor_id"),
            "actor_role": subject.get("role"),
            "tenant_id": subject.get("tenant_id"),
            "resource": resource,
            "risk": risk,
            "tags": tags or [],
            "correlation_id": cid,
            "ts": int(time.time()),
        }
        try:
            evt = hash_fields(evt, ["actor_id"])
        except Exception:
            pass
        sev = "error" if outcome in ("denied", "invalid", "missing") else "info"
        telemetry_emit(evt, severity=sev, sourcetype="shopsquire:security")
    except Exception:
        # never raise
        pass
