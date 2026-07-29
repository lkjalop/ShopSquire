from __future__ import annotations

import hashlib
import json
import logging
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from src.app.models.db import db_session

logger = logging.getLogger(__name__)


def record_message_observation(
    *,
    db=None,
    tenant_id: str,
    party_type: str,
    direction: str,
    channel: str,
    provider_message_id: str,
    purpose: str,
    consent_status: str,
    security_status: str,
    sanitized_payload: dict[str, Any],
    thread_ref: str | None = None,
    case_ref: str | None = None,
    party_ref: str | None = None,
    trace_ref: str | None = None,
    evidence_ref: str | None = None,
) -> dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    party = str(party_type or "").strip().lower()
    flow = str(direction or "").strip().lower()
    transport = str(channel or "").strip().lower()
    message_id = str(provider_message_id or "").strip()
    if not all((tenant, transport, message_id, purpose)):
        raise ValueError("communication_observation_scope_required")
    if party not in {"supplier", "buyer"}:
        raise ValueError("unsupported_communication_party")
    if flow not in {"inbound", "outbound"}:
        raise ValueError("unsupported_communication_direction")
    if consent_status not in {"not_required", "granted", "unknown", "revoked"}:
        raise ValueError("unsupported_consent_status")
    payload_json = json.dumps(
        sanitized_payload or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    observation_id = hashlib.sha256(
        f"{tenant}|{transport}|{message_id}".encode("utf-8")
    ).hexdigest()
    owns_session = db is None
    with (db_session() if owns_session else nullcontext(db)) as session:
        existing = session.execute(
            text(
                """
                SELECT id, authority
                FROM communication_observation
                WHERE tenant_id=:tenant AND channel=:channel
                  AND provider_message_id=:message
                """
            ),
            {"tenant": tenant, "channel": transport, "message": message_id},
        ).fetchone()
        if existing:
            return {
                "id": str(existing[0]),
                "duplicate": True,
                "authority": str(existing[1]),
            }
        session.execute(
            text(
                """
                INSERT INTO communication_observation
                (id, tenant_id, party_type, direction, channel,
                 provider_message_id, thread_ref, case_ref, party_ref, trace_ref, purpose,
                 consent_status, authority, security_status,
                 sanitized_payload_json, evidence_ref, observed_at)
                VALUES
                (:id, :tenant, :party, :direction, :channel,
                 :message, :thread, :case_ref, :party_ref, :trace_ref, :purpose,
                 :consent, 'observation_only', :security,
                 :payload, :evidence, :observed)
                """
            ),
            {
                "id": observation_id,
                "tenant": tenant,
                "party": party,
                "direction": flow,
                "channel": transport,
                "message": message_id,
                "thread": thread_ref,
                "case_ref": case_ref,
                "party_ref": party_ref,
                "trace_ref": trace_ref,
                "purpose": str(purpose),
                "consent": consent_status,
                "security": str(security_status or "unverified"),
                "payload": payload_json,
                "evidence": evidence_ref,
                "observed": datetime.now(timezone.utc).isoformat(),
            },
        )
        try:
            from src.app.services.communication_lifecycle import append_transition
            initial_state = (
                "quarantined" if str(security_status).lower() == "quarantined"
                else ("responded" if flow == "inbound" else "proposed")
            )
            append_transition(
                session, tenant_id=tenant, observation_id=observation_id,
                state=initial_state, idempotency_key="observation-created",
                actor_type="connector" if flow == "inbound" else "agent",
                reason=f"{transport}:{security_status}",
            )
        except Exception as exc:
            # Lifecycle schema may not exist during an older migration's isolated test.
            logger.debug("communication lifecycle projection unavailable: %s", exc)
        if owns_session:
            session.commit()
    return {"id": observation_id, "duplicate": False, "authority": "observation_only"}
