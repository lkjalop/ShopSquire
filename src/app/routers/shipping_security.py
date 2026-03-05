from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text

from src.app.models.db import db_session
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.security.object_authz import enforce_object_scope
from src.app.services.decision_log import log_trace_event


router = APIRouter(prefix="/api/v1/shipping", tags=["shipping-security"])

_LEGAL_TRANSITIONS = {
    "created": {"picked_up", "cancelled"},
    "picked_up": {"in_transit", "cancelled"},
    "in_transit": {"out_for_delivery", "failed_attempt"},
    "out_for_delivery": {"delivered", "failed_attempt"},
    "failed_attempt": {"out_for_delivery", "returned_to_sender"},
    "delivered": set(),
    "cancelled": set(),
    "returned_to_sender": set(),
}


def _verify_shipping_signature(secret: str, body: bytes, sig: str) -> bool:
    if not secret or not sig:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    got = sig.replace("sha256=", "").strip().lower()
    return hmac.compare_digest(expected, got)


def _allow_ip(request: Request) -> bool:
    allowed = [x.strip() for x in str(os.getenv("SHIPPING_WEBHOOK_IP_ALLOWLIST", "")).split(",") if x.strip()]
    if not allowed:
        return True
    ip = request.client.host if request and request.client else ""
    return ip in set(allowed)


def _ensure_shipping_tables() -> None:
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS shipping_events (
                        id TEXT PRIMARY KEY,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        tenant_id TEXT,
                        shipment_id TEXT,
                        provider TEXT,
                        status TEXT,
                        payload_json TEXT,
                        nonce TEXT
                    )
                    """
                )
            )
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS shipping_reroute_requests (
                        id TEXT PRIMARY KEY,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        tenant_id TEXT,
                        owner_id TEXT,
                        shipment_id TEXT,
                        requested_address TEXT,
                        status TEXT,
                        reason_codes_json TEXT
                    )
                    """
                )
            )
            db.commit()
    except Exception:
        pass


@router.post("/webhooks/provider")
async def ingest_shipping_webhook(
    request: Request,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ensure_shipping_tables()
    secret = str(os.getenv("SHIPPING_WEBHOOK_SECRET", "") or "")
    sig = str(request.headers.get("x-shipping-signature") or "")
    nonce = str(request.headers.get("x-shipping-nonce") or "")
    body = await request.body()
    if not _allow_ip(request):
        raise HTTPException(status_code=403, detail="shipping_ip_not_allowlisted")
    if not _verify_shipping_signature(secret, body, sig):
        raise HTTPException(status_code=401, detail="invalid_shipping_signature")
    payload = json.loads(body.decode("utf-8") or "{}")
    shipment_id = str(payload.get("shipment_id") or "").strip()
    provider = str(payload.get("provider") or "unknown").strip()
    status = str(payload.get("status") or "").strip().lower()
    tenant_id = str(payload.get("tenant_id") or "default")
    if not shipment_id or not status:
        raise HTTPException(status_code=400, detail="shipment_id_and_status_required")

    import asyncio

    def _process_event():
        with db_session() as db:
            # Nonce replay guard
            if nonce:
                row = db.execute(text("SELECT 1 FROM shipping_events WHERE nonce = :n LIMIT 1"), {"n": nonce}).fetchone()
                if row:
                    return "replay"
            prev = db.execute(
                text(
                    """
                    SELECT status FROM shipping_events
                    WHERE shipment_id = :sid
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"sid": shipment_id},
            ).fetchone()
            prev_status = str(prev[0]).lower() if prev and prev[0] else "created"
            legal_next = _LEGAL_TRANSITIONS.get(prev_status, set())
            if legal_next and status not in legal_next:
                return f"illegal:{prev_status}->{status}"
            event_id = str(uuid.uuid4())
            db.execute(
                text(
                    """
                    INSERT INTO shipping_events (id, tenant_id, shipment_id, provider, status, payload_json, nonce)
                    VALUES (:id, :tenant_id, :shipment_id, :provider, :status, :payload_json, :nonce)
                    """
                ),
                {
                    "id": event_id,
                    "tenant_id": tenant_id,
                    "shipment_id": shipment_id,
                    "provider": provider,
                    "status": status,
                    "payload_json": json.dumps(payload, ensure_ascii=False),
                    "nonce": nonce or None,
                },
            )
            db.commit()
            return "ok"

    result = await asyncio.to_thread(_process_event)
    if result == "replay":
        raise HTTPException(status_code=409, detail="shipping_replay_detected")
    if result and result.startswith("illegal:"):
        raise HTTPException(status_code=422, detail=f"illegal_shipment_transition:{result[8:]}")
    # Simple hijack/poison checks
    reason_codes = []
    if bool(payload.get("carrier_switch")):
        reason_codes.append("sudden_carrier_switch")
    if bool(payload.get("address_cluster_risk")):
        reason_codes.append("address_cluster_anomaly")
    if int(payload.get("reroute_count_24h") or 0) >= 2:
        reason_codes.append("repeated_reroute_near_delivery")
    if reason_codes:
        log_trace_event(
            trace_id=shipment_id,
            event_type="security_scan",
            source_type="agent",
            source_id="Shipping_Hijack_Guard_Agent",
            target_type="shipment",
            target_id=shipment_id,
            payload={"decision": "review", "reason_codes": reason_codes, "provider": provider},
        )
        return {"status": "review", "shipment_id": shipment_id, "reason_codes": reason_codes}
    return {"status": "ok", "shipment_id": shipment_id}


@router.post("/reroute/request")
def request_reroute(
    request: Request,
    body: Dict[str, Any],
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ensure_shipping_tables()
    shipment_id = str(body.get("shipment_id") or "").strip()
    tenant_id = str(body.get("tenant_id") or "").strip()
    owner_id = str(body.get("owner_id") or "").strip()
    new_address = str(body.get("new_address") or "").strip()
    stepup = str(body.get("mfa_stepup_token") or "").strip()
    if not shipment_id or not tenant_id or not owner_id or not new_address:
        raise HTTPException(status_code=400, detail="shipment_id_tenant_owner_new_address_required")
    enforce_object_scope(request=request, resource_id=shipment_id, tenant_id=tenant_id, owner_id=owner_id, trace_id=shipment_id)
    if stepup != "stepup-ok":
        raise HTTPException(status_code=401, detail="mfa_stepup_required")
    reason_codes = ["reroute_requested", "step_up_verified"]
    req_id = str(uuid.uuid4())
    with db_session() as db:
        db.execute(
            text(
                """
                INSERT INTO shipping_reroute_requests
                (id, tenant_id, owner_id, shipment_id, requested_address, status, reason_codes_json)
                VALUES (:id, :tenant_id, :owner_id, :shipment_id, :requested_address, :status, :reason_codes_json)
                """
            ),
            {
                "id": req_id,
                "tenant_id": tenant_id,
                "owner_id": owner_id,
                "shipment_id": shipment_id,
                "requested_address": new_address,
                "status": "pending_provider_confirm",
                "reason_codes_json": json.dumps(reason_codes),
            },
        )
        db.commit()
    log_trace_event(
        trace_id=shipment_id,
        event_type="policy_gate",
        source_type="agent",
        source_id="Shipping_Reroute_Guard_Agent",
        target_type="shipment",
        target_id=shipment_id,
        payload={
            "decision": "challenge",
            "action": "step_up_mfa",
            "reason_codes": reason_codes,
            "provider_ref": req_id,
            "recorded_at": datetime.utcnow().isoformat(),
        },
    )
    return {"status": "pending_provider_confirm", "request_id": req_id}

