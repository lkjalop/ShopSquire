"""Project verified supplier email into observation-only supply evidence.

The projection is intentionally downstream of connector identity, custody,
security, and immutable case correlation. Email can add evidence to a
hypothesis; it cannot supersede a hypothesis or authorize an action.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy import text

from src.app.services.email_connector_identity import ConnectorIdentity
from src.app.services.supply_hypothesis_workflow import (
    record_supplier_hypothesis_observation,
)


_CONTRADICTION = re.compile(
    r"\b(no|not|cannot|can't|unavailable|incorrect|delay(?:ed)?|shortage)\b",
    re.IGNORECASE,
)
_NARROWING = re.compile(
    r"\b(only|limited|until|from\s+\d|between|lead time|allocation|capacity)\b",
    re.IGNORECASE,
)


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _classify(payload: dict[str, Any]) -> tuple[str, float, list[str]]:
    """Conservative deterministic classification, never an authority decision."""
    text_value = "\n".join(
        str(payload.get(field) or "") for field in ("subject", "body", "text")
    )
    alternatives: list[str] = []
    if _CONTRADICTION.search(text_value):
        kind, confidence = "contradiction", 0.65
        alternatives.append("narrowing")
    elif _NARROWING.search(text_value):
        kind, confidence = "narrowing", 0.6
        alternatives.append("confirmation")
    else:
        kind, confidence = "confirmation", 0.5
        alternatives.extend(["narrowing", "contradiction"])
    return kind, confidence, alternatives


def project_governed_supplier_inbox(
    db,
    *,
    inbox_id: str,
    connector_identity: ConnectorIdentity,
    transport_identity_verified: bool,
    recorded_by: str = "supplier-inbox-projector-v1",
) -> dict[str, Any]:
    """Project one accepted, correlated inbox row into the latest case hypothesis."""
    if not transport_identity_verified:
        return {
            "status": "blocked_unverified_transport_identity",
            "projected": False,
            "execution_allowed": False,
        }
    row = db.execute(
        text(
            """
            SELECT tenant_id,provider,subscription_id,provider_message_id,
                   fulfillment_case_id,status,security_route,
                   sanitized_payload_json,security_verdict_json,
                   raw_evidence_ref,received_at
            FROM inbound_email_inbox
            WHERE id=:id
            """
        ),
        {"id": str(inbox_id)},
    ).mappings().first()
    if not row:
        raise ValueError("supplier_inbox_not_found")
    if (
        str(row["tenant_id"]) != connector_identity.tenant_id
        or str(row["provider"]) != connector_identity.provider
        or str(row["subscription_id"] or "") != connector_identity.subscription_id
    ):
        raise ValueError("supplier_inbox_connector_identity_mismatch")
    if str(row["status"]) != "case_correlated":
        return {
            "status": "blocked_inbox_not_accepted",
            "projected": False,
            "inbox_status": str(row["status"]),
            "execution_allowed": False,
        }
    if str(row["security_route"]) in {
        "security_review", "block", "block_and_escalate", "human_review",
    }:
        return {
            "status": "blocked_security_route",
            "projected": False,
            "security_route": str(row["security_route"]),
            "execution_allowed": False,
        }
    case_id = str(row["fulfillment_case_id"] or "").strip()
    evidence_ref = str(row["raw_evidence_ref"] or "").strip()
    if not case_id or not evidence_ref:
        return {
            "status": "blocked_missing_case_or_evidence",
            "projected": False,
            "execution_allowed": False,
        }
    hypothesis = db.execute(
        text(
            """
            SELECT id FROM causal_impact_hypothesis
            WHERE tenant_id=:tenant AND case_id=:case
            ORDER BY created_at DESC,id DESC LIMIT 1
            """
        ),
        {"tenant": connector_identity.tenant_id, "case": case_id},
    ).first()
    if not hypothesis:
        return {
            "status": "awaiting_correlated_hypothesis",
            "projected": False,
            "execution_allowed": False,
        }
    payload = _object(row["sanitized_payload_json"])
    verdict = _object(row["security_verdict_json"])
    kind, confidence, alternatives = _classify(payload)
    sender = str(payload.get("from_addr") or "").strip().lower()
    domain = sender.rsplit("@", 1)[-1].split(">", 1)[0].strip()
    supplier_ref = "domain:" + hashlib.sha256(domain.encode()).hexdigest()[:16]
    result = record_supplier_hypothesis_observation(
        db,
        tenant_id=connector_identity.tenant_id,
        hypothesis_id=str(hypothesis[0]),
        observation_type=kind,
        supplier_ref=supplier_ref,
        source_message_id=str(row["provider_message_id"]),
        observation={
            "classification": kind,
            "classification_confidence": confidence,
            "alternative_classifications": alternatives,
            "subject": str(payload.get("subject") or "")[:500],
            "sanitized_body": str(payload.get("body") or payload.get("text") or "")[:5000],
            "requires_human_interpretation": True,
        },
        provenance={
            "inbox_id": str(inbox_id),
            "raw_evidence_ref": evidence_ref,
            "provider": connector_identity.provider,
            "subscription_id": connector_identity.subscription_id,
            "transport_identity_verified": True,
            "security_route": str(row["security_route"]),
            "security_verdict": verdict,
        },
        observed_at=str(row["received_at"]),
        recorded_by=recorded_by,
    )
    return {
        "status": "projected_observation_only",
        "projected": True,
        "supplier_observation": result,
        "execution_allowed": False,
        "requires_superseding_hypothesis": True,
    }
