from fastapi import APIRouter


router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


@router.get("/health")
def health():
    return {"status": "ok"}
