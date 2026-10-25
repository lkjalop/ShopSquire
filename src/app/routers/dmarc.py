import asyncio
from fastapi import APIRouter, Depends, UploadFile, File, Query, HTTPException
from fastapi.responses import ORJSONResponse

from src.app.security.auth import require_role, ROLE_OWNER, ROLE_DEVELOPER
from src.app.services.dmarc_ingest import ingest_aggregate, get_summary

_MAX_DMARC_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

router = APIRouter(prefix="/api/v1/security/dmarc", tags=["security"])


@router.post("/ingest")
async def ingest(
    file: UploadFile = File(...),
    _role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
):
    data = await file.read(_MAX_DMARC_UPLOAD_BYTES + 1)
    if len(data) > _MAX_DMARC_UPLOAD_BYTES:
        from fastapi import HTTPException
        raise HTTPException(status_code=413, detail="DMARC report exceeds 10 MB limit")
    try:
        reports, records = await asyncio.to_thread(ingest_aggregate, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ORJSONResponse({"reports": reports, "records": records})


@router.get("/summary")
def summary(
    days: int = Query(30, ge=1, le=365),
    _role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
):
    return ORJSONResponse(get_summary(days))
