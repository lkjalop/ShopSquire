from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import text

from src.app.models.db import db_session


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def write_immutable_decision_bundle(
    *,
    trace_id: str | None,
    actor_type: str,
    actor_id: str,
    tenant_id: str,
    resource_id: str,
    action: str,
    policy_version: str,
    decision: str,
    reason_codes: List[str] | None = None,
    confidence: float | None = None,
    evidence_ids: List[str] | None = None,
    approval_chain: List[str] | None = None,
    ticket_id: str | None = None,
    provider_ref: str | None = None,
    model_inputs: Dict[str, Any] | None = None,
    supplier_docs: Dict[str, Any] | None = None,
    model_card: Dict[str, Any] | None = None,
    model_version: str | None = None,
) -> Dict[str, Any]:
    payload = {
        "trace_id": trace_id,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "tenant_id": tenant_id,
        "resource_id": resource_id,
        "action": action,
        "policy_version": policy_version,
        "decision": decision,
        "reason_codes": list(reason_codes or []),
        "confidence": confidence,
        "valid_from": _now_iso(),
        "valid_to": "infinity",
        "recorded_at": _now_iso(),
        "evidence_ids": list(evidence_ids or []),
        "approval_chain": list(approval_chain or []),
        "ticket_id": ticket_id,
        "provider_ref": provider_ref,
        "model_inputs": model_inputs or {},
        "supplier_docs": supplier_docs or {},
        "model_card": model_card or {},
        "model_version": str(model_version or ""),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    bundle_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    bundle_id = str(uuid.uuid4())
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS decision_bundles (
                        id TEXT PRIMARY KEY,
                        trace_id TEXT,
                        actor_type TEXT,
                        actor_id TEXT,
                        tenant_id TEXT,
                        resource_id TEXT,
                        action TEXT,
                        policy_version TEXT,
                        decision TEXT,
                        payload_json TEXT,
                        bundle_hash TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            db.execute(
                text(
                    """
                    INSERT INTO decision_bundles (
                        id, trace_id, actor_type, actor_id, tenant_id, resource_id, action,
                        policy_version, decision, payload_json, bundle_hash
                    ) VALUES (
                        :id, :trace_id, :actor_type, :actor_id, :tenant_id, :resource_id, :action,
                        :policy_version, :decision, :payload_json, :bundle_hash
                    )
                    """
                ),
                {
                    "id": bundle_id,
                    "trace_id": trace_id,
                    "actor_type": actor_type,
                    "actor_id": actor_id,
                    "tenant_id": tenant_id,
                    "resource_id": resource_id,
                    "action": action,
                    "policy_version": policy_version,
                    "decision": decision,
                    "payload_json": canonical,
                    "bundle_hash": bundle_hash,
                },
            )
            db.commit()
    except Exception:
        # Best-effort persistence only.
        pass
    return {"bundle_id": bundle_id, "bundle_hash": bundle_hash, "payload": payload}
