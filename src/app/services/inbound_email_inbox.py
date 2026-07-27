from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text

from src.app.security.linked_artifact_analysis import redact_sensitive_artifact


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)


def _message_id(email: Dict[str, Any]) -> str:
    value = str(email.get("message_id") or email.get("id") or "").strip()
    if not value:
        raise ValueError("provider_message_id_required")
    return value[:512]


def _sanitized_payload(email: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(email or {})
    attachments = []
    for item in payload.get("attachments") or []:
        row = dict(item or {})
        row.pop("content_b64", None)
        row.pop("raw_bytes", None)
        attachments.append(row)
    payload["attachments"] = attachments
    return dict(redact_sensitive_artifact(payload))


def _raw_reference(email: Dict[str, Any]) -> str:
    digest = hashlib.sha256(_json(email).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _existing(db, *, tenant_id: str, provider: str, provider_message_id: str) -> Optional[Dict[str, Any]]:
    row = db.execute(
        text(
            "SELECT id, status, security_route, fulfillment_case_id, raw_evidence_ref "
            "FROM inbound_email_inbox "
            "WHERE tenant_id=:tenant AND provider=:provider AND provider_message_id=:message"
        ),
        {"tenant": tenant_id, "provider": provider, "message": provider_message_id},
    ).fetchone()
    if not row:
        return None
    return {
        "inbox_id": row[0],
        "status": row[1],
        "security_route": row[2],
        "fulfillment_case_id": row[3],
        "raw_evidence_ref": row[4],
        "duplicate": True,
    }


def ingest_email(
    db,
    *,
    provider: str,
    tenant_id: str,
    email: Dict[str, Any],
    subscription_id: Optional[str] = None,
    fulfillment_case_id: Optional[str] = None,
    security_evaluator=None,
) -> Dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    if not tenant:
        raise ValueError("tenant_id_required")
    provider_key = str(provider or "").strip().lower()
    if provider_key not in {"gmail", "m365"}:
        raise ValueError("unsupported_email_provider")
    message_id = _message_id(email)
    duplicate = _existing(
        db,
        tenant_id=tenant,
        provider=provider_key,
        provider_message_id=message_id,
    )
    if duplicate:
        return duplicate

    if security_evaluator is None:
        from src.app.security.email_security import evaluate_email_security

        security_evaluator = evaluate_email_security
    verdict = dict(security_evaluator(dict(email), tenant_id=tenant) or {})
    route = str(verdict.get("route") or "security_review")
    status = "quarantined" if route in {"security_review", "block", "block_and_escalate"} else "evaluated"
    inbox_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    db.execute(
        text(
            "INSERT INTO inbound_email_inbox "
            "(id, tenant_id, provider, provider_message_id, subscription_id, fulfillment_case_id, "
            "status, security_route, sanitized_payload_json, security_verdict_json, raw_evidence_ref, "
            "received_at, updated_at) "
            "VALUES (:id,:tenant,:provider,:message,:subscription,:case_id,:status,:route,:payload,"
            ":verdict,:raw_ref,:now,:now)"
        ),
        {
            "id": inbox_id,
            "tenant": tenant,
            "provider": provider_key,
            "message": message_id,
            "subscription": str(subscription_id or "") or None,
            "case_id": str(fulfillment_case_id or "") or None,
            "status": status,
            "route": route,
            "payload": _json(_sanitized_payload(email)),
            "verdict": _json(verdict),
            "raw_ref": _raw_reference(email),
            "now": now,
        },
    )

    case_result = None
    if fulfillment_case_id:
        from src.app.services.fulfillment.external_comms import receive_email_reply

        sender = str(email.get("from_addr") or "")
        sender_domain = sender.rsplit("@", 1)[-1].split(">", 1)[0].strip().lower()
        case_result = receive_email_reply(
            db,
            case_id=str(fulfillment_case_id),
            email=dict(email),
            sender_domain=sender_domain,
            provider_ref=message_id,
            tenant_id=tenant,
            security_evaluator=lambda _payload, tenant_id=None: verdict,
        )
        status = "case_quarantined" if case_result.state == "SUPPLIER_RESPONSE_QUARANTINED" else "case_correlated"
        db.execute(
            text(
                "UPDATE inbound_email_inbox SET status=:status, updated_at=:now "
                "WHERE id=:id AND tenant_id=:tenant"
            ),
            {"status": status, "now": now, "id": inbox_id, "tenant": tenant},
        )

    return {
        "inbox_id": inbox_id,
        "status": status,
        "security_route": route,
        "fulfillment_case_id": fulfillment_case_id,
        "case_state": getattr(case_result, "state", None),
        "raw_evidence_ref": _raw_reference(email),
        "duplicate": False,
    }
