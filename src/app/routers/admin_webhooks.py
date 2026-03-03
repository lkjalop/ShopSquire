import json
import os
from typing import Dict

from fastapi import APIRouter, HTTPException, Depends, Header
from sqlalchemy import text as sql_text

from src.app.security.auth import require_role, ROLE_OWNER, ROLE_DEVELOPER
from src.app.models.db import db_session

router = APIRouter(prefix="/api/v1/admin/webhooks", tags=["admin:webhooks"])


def _assert_tenant_non_dev(tenant_id: str | None) -> None:
    env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
    if env not in ("local", "dev", "development", "test", "testing") and not str(tenant_id or "").strip():
        raise HTTPException(status_code=400, detail="missing_tenant_scope")


@router.get("/dlq")
def list_dlq(limit: int = 50, offset: int = 0, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])), tenant_id: str | None = Header(default=None, alias="X-Tenant-Id")) -> Dict:
    _assert_tenant_non_dev(tenant_id)
    try:
        with db_session() as db:
            rows = db.execute(
                sql_text("SELECT id, url, tenant_id, attempts, max_attempts, last_error, created_at FROM webhook_deliveries WHERE status = 'dlq' ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
                {"limit": limit, "offset": offset},
            ).mappings().all()
            return {"items": [dict(r) for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dlq/{item_id}/requeue")
def requeue_dlq(item_id: str, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])), tenant_id: str | None = Header(default=None, alias="X-Tenant-Id")) -> Dict:
    _assert_tenant_non_dev(tenant_id)
    try:
        with db_session() as db:
            row = db.execute(sql_text("SELECT id FROM webhook_deliveries WHERE id = :id AND status = 'dlq'"), {"id": item_id}).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="DLQ item not found")
            db.execute(sql_text("UPDATE webhook_deliveries SET status = 'pending', attempts = 0, next_attempt_at = CURRENT_TIMESTAMP WHERE id = :id"), {"id": item_id})
            db.commit()
            return {"requeued": True, "id": item_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
