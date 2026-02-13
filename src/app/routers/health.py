from fastapi import APIRouter
from datetime import datetime
import os

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
def api_health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat() + "Z"}


@router.get("/health/db")
def db_health():
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        return {"db": {"status": "unknown", "reason": "DATABASE_URL not set"}}
    if db_url.lower().startswith("sqlite"):
        return {"db": {"status": "ok", "dialect": "sqlite", "migrated": True}}

    try:
        from src.app.models.migration_guard import _alembic_head_and_current

        head, current = _alembic_head_and_current(db_url)
        migrated = bool(head) and current == head
        return {
            "db": {
                "status": "ok" if migrated else "degraded",
                "dialect": "postgres" if "postgres" in db_url.lower() else "sql",
                "alembic": {"current": current, "head": head},
                "migrated": migrated,
            }
        }
    except Exception as exc:
        return {"db": {"status": "error", "error": str(exc)}}
