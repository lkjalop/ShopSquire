from __future__ import annotations

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from typing import Optional
import httpx

from src.app.security.email_security import process_dmarc_report
from src.app.security.auth import require_role

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
