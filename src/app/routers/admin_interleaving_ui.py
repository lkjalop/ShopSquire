from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from src.app.security.auth import require_role, ROLE_OWNER, ROLE_DEVELOPER

router = APIRouter()


@router.get("/api/v1/admin/interleaving/ui")
def interleaving_ui(role: str = require_role([ROLE_OWNER, ROLE_DEVELOPER])):
    """Protected redirect to the static admin interleaving UI."""
    return RedirectResponse(url="/static/admin_interleaving.html")
