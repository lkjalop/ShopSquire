from fastapi import APIRouter, Depends
from src.app.security.auth import require_role, ROLE_OWNER
from src.app.services.jwks import rotate_keys, jwks_document, ensure_jwks

router = APIRouter(prefix="/api/v1/connectors/admin", tags=["connectors"], dependencies=[Depends(require_role([ROLE_OWNER]))])


@router.get("/jwks")
def list_jwks():
    ensure_jwks()
    return jwks_document()


@router.post("/jwks/rotate")
def rotate():
    kid = rotate_keys()
    return {"rotated": True, "kid": kid}
