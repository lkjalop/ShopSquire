from __future__ import annotations

from typing import Dict, List, Optional
import uuid

from fastapi import APIRouter, HTTPException, Depends
import json
from pydantic import BaseModel
from sqlalchemy import text as sql_text
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.models.db import db_session


router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])

# Keep an in-memory cache for fast local dev visibility; primary store is DB.
_PENDING: Dict[str, Dict] = {}


def enqueue_approval(capability: str, payload: Dict, reason: str | None = None, created_by: str | None = None) -> str:
    approval_id = str(uuid.uuid4())
    item = {
        "id": approval_id,
        "capability": capability,
        "payload": payload,
        "reason": reason,
        "status": "pending",
        "created_by": created_by,
    }
    # Persist to DB for durability
    try:
        with db_session() as db:
            db.execute(
                sql_text("INSERT INTO approvals (id, capability, payload, reason, status, created_by) VALUES (:id, :capability, :payload, :reason, :status, :created_by) ON CONFLICT (id) DO UPDATE SET capability = EXCLUDED.capability, payload = EXCLUDED.payload, reason = EXCLUDED.reason, status = EXCLUDED.status"),
                {
                    "id": approval_id,
                    "capability": capability,
                    "payload": json.dumps(payload, ensure_ascii=False),
                    "reason": reason,
                    "status": "pending",
                    "created_by": created_by,
                },
            )
            try:
                db.commit()
            except Exception:
                pass
    except Exception:
        # Best-effort: fall back to in-memory queue
        _PENDING[approval_id] = item
        return approval_id

    # Update in-memory view for local dev
    _PENDING[approval_id] = item
    return approval_id


class ApprovalRequest(BaseModel):
    capability: str
    payload: Dict
    reason: Optional[str] = None


@router.post("/proposals")
def create_proposal(req: ApprovalRequest, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    approval_id = enqueue_approval(req.capability, req.payload, req.reason, created_by=role)
    return {"created": True, "id": approval_id}


@router.get("/pending")
def list_pending(role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict[str, List[Dict]]:
    try:
        with db_session() as db:
            rows = db.execute(sql_text("SELECT id, capability, payload, reason, status, created_by, created_at FROM approvals WHERE status = 'pending' ORDER BY created_at DESC")).mappings().all()
            out = []
            for r in rows:
                try:
                    pl = json.loads(r.get("payload") or "null")
                except Exception:
                    pl = r.get("payload")
                out.append({
                    "id": r.get("id"),
                    "capability": r.get("capability"),
                    "payload": pl,
                    "reason": r.get("reason"),
                    "status": r.get("status"),
                    "created_by": r.get("created_by"),
                    "created_at": str(r.get("created_at")),
                })
            # Merge in-memory approvals that may not have persisted (best-effort dev fallback).
            try:
                seen = {str(i.get("id")) for i in out if i.get("id")}
                for pid, item in _PENDING.items():
                    if not item or item.get("status") != "pending":
                        continue
                    if str(pid) in seen:
                        continue
                    out.append(item)
            except Exception:
                pass
            return {"pending": out}
    except Exception:
        # Fallback to in-memory
        return {"pending": [v for v in _PENDING.values() if v.get("status") == "pending"]}


@router.post("/{approval_id}/approve")
def approve(approval_id: str, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER]))) -> Dict:
    try:
        with db_session() as db:
            res = db.execute(sql_text("UPDATE approvals SET status = 'approved', approved_by = :approved_by, approved_at = CURRENT_TIMESTAMP WHERE id = :id"), {"id": approval_id, "approved_by": role})
            db.commit()
            if getattr(res, "rowcount", 0) == 0:
                raise HTTPException(status_code=404, detail="Approval not found")
        # Update in-memory cache
        if approval_id in _PENDING:
            _PENDING[approval_id]["status"] = "approved"
        return {"approved": True, "id": approval_id}
    except HTTPException:
        raise
    except Exception:
        # Fallback: attempt in-memory
        item = _PENDING.get(approval_id)
        if not item:
            raise HTTPException(status_code=404, detail="Approval not found")
        item["status"] = "approved"
        return {"approved": True, "id": approval_id}


@router.post("/{approval_id}/reject")
def reject(approval_id: str, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER]))) -> Dict:
    try:
        with db_session() as db:
            res = db.execute(sql_text("UPDATE approvals SET status = 'rejected' WHERE id = :id"), {"id": approval_id})
            db.commit()
            if getattr(res, "rowcount", 0) == 0:
                raise HTTPException(status_code=404, detail="Approval not found")
        if approval_id in _PENDING:
            _PENDING[approval_id]["status"] = "rejected"
        return {"rejected": True, "id": approval_id}
    except HTTPException:
        raise
    except Exception:
        item = _PENDING.get(approval_id)
        if not item:
            raise HTTPException(status_code=404, detail="Approval not found")
        item["status"] = "rejected"
        return {"rejected": True, "id": approval_id}
