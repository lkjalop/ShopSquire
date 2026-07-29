from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text

from src.app.security.linked_artifact_analysis import redact_sensitive_artifact

_CASE_REF_RE = re.compile(
    r"(?<![0-9a-f])"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})"
    r"(?![0-9a-f])",
    re.IGNORECASE,
)


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


def _correlated_case_id(email: Dict[str, Any]) -> Optional[str]:
    """Extract the immutable RFQ case reference that ShopSquire put in the outbound subject.

    A connector-supplied ``fulfillment_case_id`` is only a hint and is never authoritative:
    accepting it without finding the same reference in reply metadata would let an inbound
    payload select an unrelated case.
    """
    searchable = "\n".join(
        str(email.get(field) or "")
        for field in ("subject", "in_reply_to", "references")
    )
    matches = {match.group(1).lower() for match in _CASE_REF_RE.finditer(searchable)}
    if len(matches) != 1:
        return None
    reference = next(iter(matches))
    hint = str(email.get("fulfillment_case_id") or "").strip().lower()
    if hint and hint != reference:
        return None
    return reference


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

        verdict = dict(
            evaluate_email_security(
                dict(email),
                tenant_id=tenant,
                bounded_ingress=True,
            ) or {}
        )
    else:
        verdict = dict(security_evaluator(dict(email), tenant_id=tenant) or {})
    # Deep enrichment can only strengthen a decision after ingress. Messages carrying
    # attachments or fetchable URLs therefore remain quarantined until an operator
    # reviews the completed enrichment; they can never race ahead into quote state.
    body_and_subject = f"{email.get('subject') or ''}\n{email.get('body') or ''}"
    deep_enrichment_required = bool(email.get("attachments")) or bool(
        re.search(r"https?://", body_and_subject, re.IGNORECASE)
    )
    if security_evaluator is None and deep_enrichment_required:
        verdict["route"] = "security_review"
        verdict["verdict_action"] = "security_review"
        if str(verdict.get("severity") or "").lower() not in {"high", "critical", "error"}:
            verdict["severity"] = "warn"
        verdict["reasons"] = list(
            dict.fromkeys(
                list(verdict.get("reasons") or []) + ["deep_enrichment_pending"]
            )
        )
    route = str(verdict.get("route") or "security_review")
    status = "quarantined" if route in {"security_review", "block", "block_and_escalate"} else "evaluated"
    correlation_email = dict(email)
    if fulfillment_case_id and not correlation_email.get("fulfillment_case_id"):
        correlation_email["fulfillment_case_id"] = fulfillment_case_id
    correlated_case_id = _correlated_case_id(correlation_email)
    if not correlated_case_id:
        from src.app.services.email_thread_correlation import resolve_case_from_thread

        correlated_case_id = resolve_case_from_thread(
            db,
            tenant_id=tenant,
            provider=provider_key,
            email=email,
        )
    from src.app.services.inbound_email_evidence import store_raw_evidence

    raw_evidence_ref = store_raw_evidence(
        db,
        tenant_id=tenant,
        provider=provider_key,
        provider_message_id=message_id,
        email=email,
    )
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
            "case_id": correlated_case_id,
            "status": status,
            "route": route,
            "payload": _json(_sanitized_payload(email)),
            "verdict": _json(verdict),
            "raw_ref": raw_evidence_ref,
            "now": now,
        },
    )
    communication = None
    try:
        party_ref = None
        sender = str(email.get("from_addr") or "").strip()
        sender_external_id = (
            sender.rsplit("<", 1)[-1].split(">", 1)[0].strip().lower()
            if sender
            else ""
        )
        if status != "quarantined" and subscription_id and sender_external_id:
            from src.app.services.communication_party_binding import (
                bind_authoritative_party,
            )
            binding = bind_authoritative_party(
                db,
                tenant_id=tenant,
                party_type="supplier",
                source=provider_key,
                object_type="supplier_sender",
                external_id=sender_external_id,
                authority="verified_connector_sender",
                provenance_ref=(
                    f"subscription:{subscription_id}|evidence:{raw_evidence_ref}"
                ),
                display_name=sender_external_id,
            )
            party_ref = str(binding["party_id"])
        from src.app.services.communication_observations import record_message_observation
        communication = record_message_observation(
            db=db,
            tenant_id=tenant,
            party_type="supplier",
            direction="inbound",
            channel=provider_key,
            provider_message_id=message_id,
            purpose="supplier_reply",
            consent_status="not_required",
            security_status="quarantined" if status == "quarantined" else "accepted",
            sanitized_payload=_sanitized_payload(email),
            thread_ref=str(email.get("thread_id") or email.get("conversation_id") or "") or None,
            case_ref=correlated_case_id,
            party_ref=party_ref,
            evidence_ref=raw_evidence_ref,
        )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "communication projection unavailable inbox_id=%s: %s", inbox_id, exc
        )
        if str(os.getenv("APP_ENV") or "").strip().lower() in {"prod", "production", "staging"}:
            raise RuntimeError("communication_projection_required") from exc

    env = str(os.getenv("APP_ENV") or "dev").strip().lower()
    async_default = env in {"prod", "production", "staging"}
    async_enabled = str(
        os.getenv("EMAIL_ENRICHMENT_ASYNC_ENABLED", "1" if async_default else "0")
    ).strip().lower() in {"1", "true", "yes", "on"}
    if async_enabled:
        try:
            from src.app.tasks.email_enrichment_tasks import enrich_inbound_email

            enrich_inbound_email.apply_async(args=[inbox_id, tenant], countdown=2)
            db.execute(
                text(
                    "UPDATE inbound_email_inbox SET enrichment_status='queued' "
                    "WHERE id=:id AND tenant_id=:tenant"
                ),
                {"id": inbox_id, "tenant": tenant},
            )
        except Exception as exc:
            db.execute(
                text(
                    "UPDATE inbound_email_inbox SET enrichment_status='enqueue_failed', "
                    "enrichment_error=:error WHERE id=:id AND tenant_id=:tenant"
                ),
                {"error": repr(exc)[:500], "id": inbox_id, "tenant": tenant},
            )

    case_result = None
    # Correlation is derived from the immutable RFQ reference, never from a connector
    # payload-selected case id. The explicit argument remains for compatibility but is
    # treated only as a consistency hint.
    if correlated_case_id:
        from src.app.services.fulfillment.external_comms import receive_email_reply

        sender = str(email.get("from_addr") or "")
        sender_domain = sender.rsplit("@", 1)[-1].split(">", 1)[0].strip().lower()
        case_result = receive_email_reply(
            db,
            case_id=correlated_case_id,
            email=dict(email),
            sender_domain=sender_domain,
            provider_ref=message_id,
            raw_evidence_ref=raw_evidence_ref,
            inbox_id=inbox_id,
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
        "fulfillment_case_id": correlated_case_id,
        "case_state": getattr(case_result, "state", None),
        "raw_evidence_ref": raw_evidence_ref,
        "communication_observation_id": communication["id"] if communication else None,
        "duplicate": False,
    }
