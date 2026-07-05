"""Owner control plane for the outbound-DLP quarantine (human-release queue).

A send the outbound content DLP hard-blocked (a secret in the body) parks here. An OWNER reviews
and either RELEASES it (the content is intended — e.g. a licence key the supplier needs) or
DISCARDS it. Release is the GATE-2 second-person judgement, recorded with the actor; it re-sends
ONCE with the DLP block bypassed. Owner-only — the bodies hold the very secrets that were flagged.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from src.app.models.db import db_session
from src.app.security.auth import ROLE_OWNER, require_role
from src.app.services import outbound_dlp_quarantine as q

logger = logging.getLogger("shopsquire.outbound_quarantine")

router = APIRouter(prefix="/api/v1/email/outbound/quarantine", tags=["email", "outbound"])


def _tenant(x: Optional[str]) -> Optional[str]:
    return (x.strip() or None) if x else None


@router.get("")
def list_pending(role: str = Depends(require_role([ROLE_OWNER])),
                 status: str = "pending_release",
                 x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id")) -> Dict[str, Any]:
    """The review queue. Bodies are NOT returned here (they hold the flagged secret) — only the
    dlp findings + metadata; fetch the body via the inspect route on an explicit decision."""
    with db_session() as db:
        return {"items": q.list_quarantine(db, status=status, tenant_id=_tenant(x_tenant_id))}


@router.get("/{qid}")
def inspect(qid: str, role: str = Depends(require_role([ROLE_OWNER]))) -> Dict[str, Any]:
    """Fetch one quarantined send WITH its body for owner review before release/discard."""
    with db_session() as db:
        item = q.get_quarantined(db, qid)
    if not item:
        raise HTTPException(status_code=404, detail="quarantine_item_not_found")
    return item


@router.post("/{qid}/release")
def release(qid: str, role: str = Depends(require_role([ROLE_OWNER]))) -> Dict[str, Any]:
    """OWNER releases a quarantined send: re-transmit ONCE with the DLP block bypassed (the human
    has judged the flagged content intended), then mark it released with the actor recorded."""
    with db_session() as db:
        item = q.get_quarantined(db, qid)
        if not item:
            raise HTTPException(status_code=404, detail="quarantine_item_not_found")
        if item.get("status") != "pending_release":
            raise HTTPException(status_code=409, detail={"message": "not_pending", "status": item.get("status")})
    from src.app.services.email_providers import get_default_email_provider
    provider = get_default_email_provider()
    result = provider.send(item["to_addr"], item["subject"], item["body"],
                           agent_id=item.get("agent_id") or "Owner_Release", tenant_id=item.get("tenant_id"),
                           _dlp_release=True)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail={"message": "release_send_failed", "result": result})
    with db_session() as db:
        q.mark_status(db, qid, status="released", actor=role)
    logger.info("outbound DLP quarantine %s RELEASED by role=%s", qid, role)
    return {"id": qid, "status": "released", "sent": True}


@router.post("/{qid}/discard")
def discard(qid: str, role: str = Depends(require_role([ROLE_OWNER]))) -> Dict[str, Any]:
    """OWNER discards a quarantined send — it is never transmitted."""
    with db_session() as db:
        ok = q.mark_status(db, qid, status="discarded", actor=role)
    if not ok:
        raise HTTPException(status_code=409, detail="not_pending_or_not_found")
    return {"id": qid, "status": "discarded"}
