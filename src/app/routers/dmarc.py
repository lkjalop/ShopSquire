from fastapi import APIRouter, UploadFile, File
from fastapi.responses import ORJSONResponse

from src.app.services.dmarc_ingest import ingest_aggregate, get_summary

router = APIRouter(prefix="/api/v1/security/dmarc", tags=["security"])


@router.post("/ingest")
async def ingest(file: UploadFile = File(...)):
    data = await file.read()
    reports, records = ingest_aggregate(data)
    return ORJSONResponse({"reports": reports, "records": records})


@router.get("/summary")
def summary(days: int = 30):
    return ORJSONResponse(get_summary(days))
