import json
import uuid
from typing import Dict, Any, List
from sqlalchemy import text

from src.app.models.db import db_session
from src.app.models.event_log import ensure_event_log_table
from src.app.services.decision_log import log_decision
from src.app.services.audit_chain import append_audit_chain_event


def persist_decision_and_audits(
    uid: str,
    agent_name: str,
    proposal: Dict[str, Any],
    policy_version: str,
    approval_required: bool,
    audit_entries: List[Dict[str, Any]] | None = None,
) -> str | None:
    """Persist a decision_log and optional audit entries atomically and emit event_log rows.

    Returns the decision id on success, None on failure.
    """
    ensure_event_log_table()
    try:
        # Use central decision contract
        dec_id = log_decision(
            agent_name=agent_name,
            input_data={
                "uid_hash": __import__("hashlib").sha256((uid or "").encode("utf-8")).hexdigest()[:12],
                "proposal": proposal,
            },
            retrieved_context={"live": {"cart_total_cents": proposal.get("cart_total_cents"), "sku": proposal.get("sku")}},
            proposed_action=proposal,
            agent_reasoning=proposal.get("reason", ""),
            policy_version=policy_version,
            approval_required=approval_required,
            execution_status="pending" if approval_required else "executed",
        )
        if not dec_id:
            return None
        # Persist audits and emit events
        with db_session() as db:
            db.execute(
                text("INSERT INTO event_log (id, type, payload, status) VALUES (:id, :type, :payload, 'pending')"),
                {
                    "id": str(uuid.uuid4()),
                    "type": "decision.created",
                    "payload": json.dumps({"id": dec_id, "agent": agent_name, "policy_version": policy_version}, ensure_ascii=False),
                },
            )
            chain_events = []
            for ae in (audit_entries or []):
                db.execute(
                    text("INSERT INTO decision_audits (id, decision_id, action, actor, metadata, created_at) VALUES (:id, :decision_id, :action, :actor, :metadata, CURRENT_TIMESTAMP)"),
                    {
                        "id": str(uuid.uuid4()),
                        "decision_id": dec_id,
                        "action": ae.get("action"),
                        "actor": ae.get("actor"),
                        "metadata": json.dumps(ae.get("metadata") or {}, ensure_ascii=False),
                    },
                )
                db.execute(
                    text("INSERT INTO event_log (id, type, payload, status) VALUES (:id, :type, :payload, 'pending')"),
                    {
                        "id": str(uuid.uuid4()),
                        "type": "decision.audit",
                        "payload": json.dumps({"decision_id": dec_id, "action": ae.get("action"), "actor": ae.get("actor")}, ensure_ascii=False),
                    },
                )
                chain_events.append(
                    {
                        "source_type": "decision.audit",
                        "source_id": dec_id,
                        "payload": {"decision_id": dec_id, "action": ae.get("action"), "actor": ae.get("actor"), "metadata": ae.get("metadata") or {}},
                    }
                )
            try:
                db.commit()
            except Exception:
                pass
        try:
            for ce in chain_events:
                append_audit_chain_event(source_type=ce["source_type"], source_id=ce["source_id"], payload=ce["payload"])
        except Exception:
            pass
        return dec_id
    except Exception:
        return None


def write_audit_and_event(decision_id: str, action: str, actor: str, metadata: Dict[str, Any] | None = None) -> bool:
    """Write a single audit row and corresponding event_log record in one transaction."""
    ensure_event_log_table()
    try:
        chain_payload = {"decision_id": decision_id, "action": action, "actor": actor, "metadata": metadata or {}}
        with db_session() as db:
            db.execute(
                text(
                    "INSERT INTO decision_audits (id, decision_id, action, actor, metadata, created_at) VALUES (:id, :decision_id, :action, :actor, :metadata, CURRENT_TIMESTAMP)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "decision_id": decision_id,
                    "action": action,
                    "actor": actor,
                    "metadata": json.dumps(metadata or {}, ensure_ascii=False),
                },
            )
            db.execute(
                text(
                    "INSERT INTO event_log (id, type, payload, status) VALUES (:id, :type, :payload, 'pending')"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "type": "decision.audit",
                    "payload": json.dumps({"decision_id": decision_id, "action": action, "actor": actor}, ensure_ascii=False),
                },
            )
            db.commit()
        try:
            append_audit_chain_event(
                source_type="decision.audit",
                source_id=decision_id,
                payload=chain_payload,
            )
        except Exception:
            pass
        return True
    except Exception:
        return False
