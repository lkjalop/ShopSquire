from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Depends

from src.app.deps import get_redis
from src.app.services.memory import Memory
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER


router = APIRouter(prefix="/api/v1/preferences", tags=["preferences"])


@router.get("")
def get_preferences(uid: str | None = None, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    user_id = uid or "demo-user"
    mem = Memory(get_redis())
    ctx = mem.get_context(user_id)
    return {"uid": user_id, "preferences": ctx.get("kv") or {}}
