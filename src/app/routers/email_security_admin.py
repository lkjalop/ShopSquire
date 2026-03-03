from __future__ import annotations

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from typing import Optional
import httpx

from src.app.security.email_security import process_dmarc_report
from src.app.security.auth import require_role
from src.app.security.security_event_ingest import (
    delete_tenant_storage_policy,
    get_tenant_storage_policy,
    put_tenant_storage_policy,
)

router = APIRouter(prefix="/api/v1/admin/security", tags=["admin-security"])


@router.post("/dmarc_ingest")
async def dmarc_ingest(
    file: Optional[UploadFile] = File(default=None),
    url: Optional[str] = None,
    tenant_id: Optional[str] = None,
    role: str = Depends(require_role(["owner", "developer"]))
):
    if not file and not url:
        raise HTTPException(status_code=400, detail="Provide a file or a URL")
    data = None
    if file:
        data = await file.read()
    else:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.content
        except Exception:
            raise HTTPException(status_code=400, detail="Failed to fetch URL")
    summary = process_dmarc_report(data or b"", tenant_id=tenant_id)
    return {"status": "ok", "summary": summary}


@router.get("/storage-policy")
def get_security_storage_policy(
    tenant_id: Optional[str] = None,
    role: str = Depends(require_role(["owner", "developer"])),
):
    _ = role
    return get_tenant_storage_policy(tenant_id=tenant_id)


@router.put("/storage-policy")
def put_security_storage_policy(
    payload: dict,
    tenant_id: Optional[str] = None,
    role: str = Depends(require_role(["owner", "developer"])),
):
    _ = role
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload_must_be_object")
    targets = payload.get("storage_targets")
    if not isinstance(targets, list):
        raise HTTPException(status_code=400, detail="storage_targets_must_be_array")
    try:
        out = put_tenant_storage_policy(tenant_id=tenant_id, storage_targets=[str(x) for x in targets])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"ok": True, **out}


@router.delete("/storage-policy")
def delete_security_storage_policy(
    tenant_id: Optional[str] = None,
    role: str = Depends(require_role(["owner", "developer"])),
):
    _ = role
    try:
        out = delete_tenant_storage_policy(tenant_id=tenant_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"ok": True, **out}
