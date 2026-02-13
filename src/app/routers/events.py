from fastapi import APIRouter, Header, Depends
from src.app.models.schemas import MedusaEvent
from src.app.models.db import db_session
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER


router = APIRouter(prefix="/api/v1/orchestrator/events", tags=["events"])


def _idempotent(path: str, key: str | None) -> bool:
    if not key:
        return True
    with db_session() as db:
        # Ensure idempotency table exists (SQLite tests)
        try:
            from sqlalchemy import text
            try:
                if getattr(db.bind, "dialect", None) is not None and db.bind.dialect.name == "sqlite":
                    db.execute(
                        text(
                            "CREATE TABLE IF NOT EXISTS idempotency_keys (key TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
                        )
                    )
            except Exception:
                pass
        except Exception:
            pass
        try:
            # Use atomic INSERT OR IGNORE to avoid race conditions and extra SELECTs
            from sqlalchemy import text
            res = db.execute(text("INSERT OR IGNORE INTO idempotency_keys (key) VALUES (:k)"), {"k": f"{path}:{key}"})
            db.commit()
            try:
                return bool(getattr(res, "rowcount", 0))
            except Exception:
                return True
        except Exception:
            return True


@router.post("/order_placed")
def order_placed(evt: MedusaEvent, idempotency_key: str | None = Header(None), role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))):
    if not _idempotent("order_placed", idempotency_key):
        return {"received": True, "duplicate": True}
    return {"received": True}


@router.post("/cart_updated")
def cart_updated(evt: MedusaEvent, idempotency_key: str | None = Header(None), role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))):
    if not _idempotent("cart_updated", idempotency_key):
        return {"received": True, "duplicate": True}
    return {"received": True}


@router.post("/refund_requested")
def refund_requested(evt: MedusaEvent, idempotency_key: str | None = Header(None), role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))):
    if not _idempotent("refund_requested", idempotency_key):
        return {"received": True, "duplicate": True}
    return {"received": True}
