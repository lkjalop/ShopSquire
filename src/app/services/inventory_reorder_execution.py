"""Governed inventory reorder proposal and execution boundary.

Only this module may invoke ``InventoryAgent.execute_reorder`` in production.
Every execution is bound to a tenant-scoped, immutable proposal, an approved
approval record carrying the proposal hash, and a still-current authoritative
supplier offer.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from sqlalchemy import text


class ReorderBoundaryError(RuntimeError):
    def __init__(self, code: str, *, status_code: int = 409, detail: Dict[str, Any] | None = None):
        super().__init__(code)
        self.code = code
        self.status_code = int(status_code)
        self.detail = dict(detail or {})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(value: Dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_payload(value: Dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _json_object(value: Any) -> Dict[str, Any]:
    try:
        parsed = json.loads(value or "{}") if isinstance(value, str) else value
    except (TypeError, ValueError):
        parsed = {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _proposal_ttl_seconds() -> int:
    try:
        value = int(os.getenv("INVENTORY_REORDER_PROPOSAL_TTL_SEC", "3600") or 3600)
    except (TypeError, ValueError):
        value = 3600
    return max(60, min(value, 86400))


def _claim_stale_seconds() -> int:
    try:
        value = int(os.getenv("INVENTORY_REORDER_CLAIM_STALE_SEC", "300") or 300)
    except (TypeError, ValueError):
        value = 300
    return max(30, min(value, 3600))


def _authoritative_offer(
    db,
    *,
    tenant_id: str,
    sku: str,
    currency: str,
    source_record_id: str | None = None,
) -> Dict[str, Any]:
    sql = """
        SELECT supplier_id, landed_unit_cost_cents, currency, source_record_id,
               provenance_json, confidence, effective_from, effective_to
        FROM supplier_offer
        WHERE tenant_id=:tenant AND sku=:sku AND currency=:currency
          AND status='active' AND simulation_only=0
          AND cost_kind='validated_landed_quote'
          AND effective_from <= CURRENT_TIMESTAMP
          AND (effective_to IS NULL OR effective_to > CURRENT_TIMESTAMP)
    """
    params: Dict[str, Any] = {
        "tenant": tenant_id,
        "sku": sku,
        "currency": currency.upper(),
    }
    if source_record_id:
        sql += " AND source_record_id=:source_record_id"
        params["source_record_id"] = source_record_id
    sql += " ORDER BY landed_unit_cost_cents ASC, effective_from DESC LIMIT 1"
    try:
        row = db.execute(text(sql), params).fetchone()
    except Exception as exc:
        raise ReorderBoundaryError(
            "authoritative_supplier_offer_unavailable",
            detail={"reason": type(exc).__name__},
        ) from exc
    if not row:
        raise ReorderBoundaryError("authoritative_supplier_offer_missing")
    try:
        provenance = json.loads(row[4] or "[]")
    except (TypeError, ValueError):
        provenance = []
    if not isinstance(provenance, list) or not provenance:
        raise ReorderBoundaryError("supplier_offer_provenance_missing")
    return {
        "supplier_id": str(row[0]),
        "landed_unit_cost_cents": int(row[1]),
        "currency": str(row[2]).upper(),
        "source_record_id": str(row[3]),
        "provenance_chain": [str(item) for item in provenance],
        "confidence": float(row[5] or 0.0),
        "effective_from": str(row[6] or ""),
        "effective_to": str(row[7] or "") or None,
    }


def create_reorder_proposal(
    db,
    *,
    tenant_id: str,
    sku: str,
    actor_id: str,
    now: datetime | None = None,
) -> Dict[str, Any]:
    """Create an immutable proposal exclusively from current canonical facts."""
    tenant = str(tenant_id or "").strip()
    key = str(sku or "").strip()
    actor = str(actor_id or "").strip()
    if not tenant or not key or not actor:
        raise ReorderBoundaryError("proposal_identity_missing", status_code=400)

    from src.app.services.market_projection import operator_product_projection

    projection = operator_product_projection(db, sku=key, tenant_id=tenant)
    if not projection.get("available"):
        raise ReorderBoundaryError(str(projection.get("reason") or "projection_unavailable"), status_code=404)
    action = (projection.get("action_proposals") or {}).get("replenishment") or {}
    if not action.get("authorized"):
        raise ReorderBoundaryError(
            "proposal_not_authorized",
            detail={"reasons": list(action.get("reasons") or [])},
        )

    quantity = int(action.get("shortfall") or 0)
    lead_time = float(action.get("lead_time_days") or 0.0)
    currency = str(projection.get("currency") or "").upper()
    source_record_id = str(projection.get("cost_source_record_id") or "")
    if quantity <= 0 or lead_time <= 0 or not currency or not source_record_id:
        raise ReorderBoundaryError("proposal_facts_incomplete")
    offer = _authoritative_offer(
        db,
        tenant_id=tenant,
        sku=key,
        currency=currency,
        source_record_id=source_record_id,
    )
    total_cost = int(offer["landed_unit_cost_cents"]) * quantity
    created_at = (now or _utcnow()).astimezone(timezone.utc)
    expires_at = created_at + timedelta(seconds=_proposal_ttl_seconds())
    payload = {
        "schema_version": "inventory_reorder_proposal_v1",
        "tenant_id": tenant,
        "sku": key,
        "supplier_id": offer["supplier_id"],
        "quantity": quantity,
        "landed_unit_cost_cents": int(offer["landed_unit_cost_cents"]),
        "total_cost_cents": total_cost,
        "currency": currency,
        "lead_time_days": lead_time,
        "source_record_id": offer["source_record_id"],
        "provenance_chain": offer["provenance_chain"],
        "created_at": created_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    proposal_hash = _hash_payload(payload)
    proposal_id = f"irp-{uuid.uuid4().hex}"
    try:
        db.execute(text("""
            INSERT INTO inventory_reorder_proposal (
                id, tenant_id, sku, supplier_id, quantity, landed_unit_cost_cents,
                total_cost_cents, currency, lead_time_days, source_record_id,
                proposal_hash, payload_json, status, created_by, created_at, expires_at
            ) VALUES (
                :id, :tenant, :sku, :supplier, :quantity, :unit_cost, :total_cost,
                :currency, :lead_time, :source_record, :proposal_hash, :payload,
                'pending_approval', :actor, :created_at, :expires_at
            )
        """), {
            "id": proposal_id,
            "tenant": tenant,
            "sku": key,
            "supplier": offer["supplier_id"],
            "quantity": quantity,
            "unit_cost": int(offer["landed_unit_cost_cents"]),
            "total_cost": total_cost,
            "currency": currency,
            "lead_time": lead_time,
            "source_record": offer["source_record_id"],
            "proposal_hash": proposal_hash,
            "payload": _canonical_json(payload),
            "actor": actor,
            "created_at": created_at,
            "expires_at": expires_at,
        })
        db.commit()
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        raise ReorderBoundaryError(
            "proposal_persistence_failed",
            status_code=503,
            detail={"reason": type(exc).__name__},
        ) from exc
    return {
        "proposal_id": proposal_id,
        "proposal_hash": proposal_hash,
        "tenant_id": tenant,
        "sku": key,
        "quantity": quantity,
        "supplier_id": offer["supplier_id"],
        "total_cost_cents": total_cost,
        "currency": currency,
        "expires_at": expires_at.isoformat(),
    }


def bind_approval(db, *, tenant_id: str, proposal_id: str, approval_id: str) -> None:
    result = db.execute(text("""
        UPDATE inventory_reorder_proposal
        SET approval_id=:approval
        WHERE id=:proposal AND tenant_id=:tenant AND status='pending_approval'
          AND approval_id IS NULL
    """), {
        "approval": str(approval_id),
        "proposal": str(proposal_id),
        "tenant": str(tenant_id),
    })
    if getattr(result, "rowcount", 0) != 1:
        db.rollback()
        raise ReorderBoundaryError("proposal_approval_bind_failed")
    db.commit()


def _load_proposal(db, *, tenant_id: str, proposal_id: str) -> Dict[str, Any]:
    row = db.execute(text("""
        SELECT id, tenant_id, sku, supplier_id, quantity, landed_unit_cost_cents,
               total_cost_cents, currency, lead_time_days, source_record_id,
               proposal_hash, payload_json, status, approval_id, executed_po_id,
               expires_at, execution_started_at
        FROM inventory_reorder_proposal
        WHERE id=:proposal AND tenant_id=:tenant
    """), {"proposal": str(proposal_id), "tenant": str(tenant_id)}).fetchone()
    if not row:
        raise ReorderBoundaryError("reorder_proposal_not_found", status_code=404)
    return {
        "id": row[0], "tenant_id": row[1], "sku": row[2], "supplier_id": row[3],
        "quantity": int(row[4]), "landed_unit_cost_cents": int(row[5]),
        "total_cost_cents": int(row[6]), "currency": str(row[7]).upper(),
        "lead_time_days": float(row[8]), "source_record_id": row[9],
        "proposal_hash": row[10], "payload": _json_object(row[11]), "status": row[12],
        "approval_id": row[13], "executed_po_id": row[14], "expires_at": row[15],
        "execution_started_at": row[16],
    }


def _recover_execution_claim(
    db,
    *,
    proposal: Dict[str, Any],
    current: datetime,
) -> Dict[str, Any] | None:
    """Resolve a crash between PO persistence and proposal finalization."""
    if proposal["status"] != "executing":
        return None
    existing = db.execute(text("""
        SELECT id FROM purchase_orders
        WHERE tenant_id=:tenant AND reorder_proposal_id=:proposal
        LIMIT 1
    """), {
        "tenant": proposal["tenant_id"],
        "proposal": proposal["id"],
    }).fetchone()
    if existing:
        db.execute(text("""
            UPDATE inventory_reorder_proposal
            SET status='executed', executed_po_id=:po, executed_at=:executed_at
            WHERE id=:proposal AND tenant_id=:tenant AND status='executing'
        """), {
            "po": str(existing[0]),
            "executed_at": current,
            "proposal": proposal["id"],
            "tenant": proposal["tenant_id"],
        })
        db.commit()
        return {
            "status": "po_created",
            "po_number": str(existing[0]),
            "proposal_id": proposal["id"],
            "deduped": True,
            "recovered": True,
        }
    started = proposal.get("execution_started_at")
    if not isinstance(started, datetime):
        try:
            started = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            started = None
    if started is not None and started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if (
        started is not None
        and (current - started.astimezone(timezone.utc)).total_seconds()
        < _claim_stale_seconds()
    ):
        raise ReorderBoundaryError("reorder_execution_in_progress")
    reset = db.execute(text("""
        UPDATE inventory_reorder_proposal
        SET status='pending_approval', execution_started_at=NULL
        WHERE id=:proposal AND tenant_id=:tenant AND status='executing'
    """), {"proposal": proposal["id"], "tenant": proposal["tenant_id"]})
    if getattr(reset, "rowcount", 0) != 1:
        db.rollback()
        raise ReorderBoundaryError("reorder_execution_recovery_conflict")
    db.commit()
    return None


def _verify_approval(db, proposal: Dict[str, Any]) -> Dict[str, Any]:
    approval_id = str(proposal.get("approval_id") or "")
    if not approval_id:
        raise ReorderBoundaryError("reorder_proposal_not_approved")
    row = db.execute(text("""
        SELECT capability, payload, status, approved_by, approved_at
        FROM approvals WHERE id=:approval
    """), {"approval": approval_id}).fetchone()
    if not row or str(row[2]) != "approved":
        raise ReorderBoundaryError("reorder_proposal_not_approved")
    payload = _json_object(row[1])
    expected = {
        "tenant_id": str(proposal["tenant_id"]),
        "proposal_id": str(proposal["id"]),
        "proposal_hash": str(proposal["proposal_hash"]),
    }
    actual = {key: str(payload.get(key) or "") for key in expected}
    if str(row[0]) != "commercial_replenishment" or actual != expected:
        raise ReorderBoundaryError("reorder_approval_binding_mismatch")
    if not row[3] or not row[4]:
        raise ReorderBoundaryError("reorder_approval_actor_missing")
    return {"approval_id": approval_id, "approved_by": str(row[3]), "approved_at": str(row[4])}


def execute_approved_reorder(
    db,
    *,
    tenant_id: str,
    proposal_id: str,
    actor_id: str,
    now: datetime | None = None,
) -> Dict[str, Any]:
    """Verify the immutable authorization chain, then execute exactly once."""
    proposal = _load_proposal(db, tenant_id=tenant_id, proposal_id=proposal_id)
    if proposal["status"] == "executed":
        return {
            "status": "po_created",
            "po_number": proposal["executed_po_id"],
            "proposal_id": proposal["id"],
            "deduped": True,
        }
    current = (now or _utcnow()).astimezone(timezone.utc)
    recovered = _recover_execution_claim(db, proposal=proposal, current=current)
    if recovered is not None:
        return recovered
    if proposal["status"] == "executing":
        proposal = _load_proposal(
            db,
            tenant_id=tenant_id,
            proposal_id=proposal_id,
        )
    if proposal["status"] != "pending_approval":
        raise ReorderBoundaryError("reorder_proposal_not_executable")
    expires = proposal["expires_at"]
    if not isinstance(expires, datetime):
        try:
            expires = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ReorderBoundaryError("reorder_proposal_expiry_invalid") from exc
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if current >= expires.astimezone(timezone.utc):
        raise ReorderBoundaryError("reorder_proposal_expired")
    if _hash_payload(proposal["payload"]) != proposal["proposal_hash"]:
        raise ReorderBoundaryError("reorder_proposal_hash_mismatch")
    approval = _verify_approval(db, proposal)

    offer = _authoritative_offer(
        db,
        tenant_id=str(proposal["tenant_id"]),
        sku=str(proposal["sku"]),
        currency=str(proposal["currency"]),
        source_record_id=str(proposal["source_record_id"]),
    )
    current_offer = (
        offer["supplier_id"],
        int(offer["landed_unit_cost_cents"]),
        offer["currency"],
        offer["source_record_id"],
    )
    approved_offer = (
        str(proposal["supplier_id"]),
        int(proposal["landed_unit_cost_cents"]),
        str(proposal["currency"]),
        str(proposal["source_record_id"]),
    )
    if current_offer != approved_offer:
        raise ReorderBoundaryError("reorder_supplier_offer_changed")

    # Inventory and demand may change while a human reviews the proposal. Require
    # the same deterministic policy to still authorize the same shortfall before
    # consuming the approval.
    from src.app.services.market_projection import operator_product_projection

    current_projection = operator_product_projection(
        db,
        sku=str(proposal["sku"]),
        tenant_id=str(proposal["tenant_id"]),
    )
    current_action = (
        (current_projection.get("action_proposals") or {}).get("replenishment") or {}
    )
    if not current_projection.get("available") or not current_action.get("authorized"):
        raise ReorderBoundaryError(
            "reorder_no_longer_authorized",
            detail={"reasons": list(current_action.get("reasons") or [])},
        )
    if (
        int(current_action.get("shortfall") or 0) != int(proposal["quantity"])
        or str(current_projection.get("cost_source_record_id") or "")
        != str(proposal["source_record_id"])
    ):
        raise ReorderBoundaryError("reorder_facts_changed")

    from src.app.security.authorization_engine import authorize_action

    authz = authorize_action(
        "supplier_order",
        requester="Inventory_Agent",
        value_usd=float(proposal["total_cost_cents"]) / 100.0,
        confidence=float(offer.get("confidence") or 0.0),
        subject_id=str(proposal["supplier_id"]),
        idempotency_key=f"inventory-proposal:{proposal['id']}:{proposal['proposal_hash']}",
        metadata={
            "tenant_id": proposal["tenant_id"],
            "sku": proposal["sku"],
            "approval_id": approval["approval_id"],
            "human_actor": str(actor_id),
        },
    )
    # Consequential inventory execution never treats a shadow deny/escalation as permission.
    if not authz.allowed:
        raise ReorderBoundaryError(
            "supplier_order_not_authorized",
            detail={"authorization": authz.to_dict()},
        )

    from src.app.services.inventory_agent import InventoryAgent, ReorderRecommendation

    recommendation = ReorderRecommendation(
        sku=str(proposal["sku"]),
        supplier_id=str(proposal["supplier_id"]),
        quantity=int(proposal["quantity"]),
        estimated_cost=float(proposal["total_cost_cents"]) / 100.0,
        lead_time_days=max(1, int(round(float(proposal["lead_time_days"])))),
        urgency="normal",
        supplier_trust_score=float(offer.get("confidence") or 0.0),
        supplier_trust_band="high" if float(offer.get("confidence") or 0.0) >= 0.8 else "medium",
        source_confirmations={"approved_proposal": True, "validated_supplier_offer": True},
        tenant_id=str(proposal["tenant_id"]),
        currency=str(proposal["currency"]),
        proposal_id=str(proposal["id"]),
    )
    claim = db.execute(text("""
        UPDATE inventory_reorder_proposal
        SET status='executing', execution_started_at=:started
        WHERE id=:proposal AND tenant_id=:tenant AND status='pending_approval'
    """), {
        "started": current,
        "proposal": proposal["id"],
        "tenant": proposal["tenant_id"],
    })
    if getattr(claim, "rowcount", 0) != 1:
        db.rollback()
        latest = _load_proposal(
            db,
            tenant_id=str(proposal["tenant_id"]),
            proposal_id=str(proposal["id"]),
        )
        if latest["status"] == "executed":
            return {
                "status": "po_created",
                "po_number": latest["executed_po_id"],
                "proposal_id": latest["id"],
                "deduped": True,
            }
        raise ReorderBoundaryError("reorder_execution_in_progress")
    db.commit()
    result = InventoryAgent(tenant_id=str(proposal["tenant_id"])).execute_reorder(
        recommendation,
        approval=approval["approval_id"],
        governed_approval=True,
    )
    if result.get("status") != "po_created":
        db.execute(text("""
            UPDATE inventory_reorder_proposal
            SET status='pending_approval', execution_started_at=NULL
            WHERE id=:proposal AND tenant_id=:tenant AND status='executing'
        """), {"proposal": proposal["id"], "tenant": proposal["tenant_id"]})
        db.commit()
        return {"proposal_id": proposal["id"], **result}
    update = db.execute(text("""
        UPDATE inventory_reorder_proposal
        SET status='executed', executed_po_id=:po, executed_at=:executed_at,
            execution_started_at=NULL
        WHERE id=:proposal AND tenant_id=:tenant AND status='executing'
    """), {
        "po": str(result.get("po_number") or ""),
        "executed_at": current,
        "proposal": proposal["id"],
        "tenant": proposal["tenant_id"],
    })
    if getattr(update, "rowcount", 0) != 1:
        db.rollback()
        raise ReorderBoundaryError("reorder_execution_commit_conflict")
    db.commit()
    return {"proposal_id": proposal["id"], "deduped": False, **result}
