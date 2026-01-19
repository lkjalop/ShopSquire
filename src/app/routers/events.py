from fastapi import APIRouter, Header
from src.app.models.schemas import MedusaEvent
from src.app.security.observer import emit_security_event
from src.app.models.db import db_session


router = APIRouter(prefix="/api/v1/orchestrator/events", tags=["events"])


def _idempotent(path: str, key: str | None) -> bool:
    if not key:
        return True
    with db_session() as db:
        exists = db.execute("SELECT 1 FROM idempotency_keys WHERE key = :k", {"k": f"{path}:{key}"}).scalar()
        if exists:
            return False
        db.execute("INSERT INTO idempotency_keys (key) VALUES (:k)", {"k": f"{path}:{key}"})
        db.commit()
        return True


@router.post("/order_placed")
def order_placed(evt: MedusaEvent, idempotency_key: str | None = Header(None)):
    if not _idempotent("order_placed", idempotency_key):
        return {"received": True, "duplicate": True}
    emit_security_event("/api/v1/orchestrator/events/order_placed", evt.model_dump())
    return {"received": True}


@router.post("/cart_updated")
def cart_updated(evt: MedusaEvent, idempotency_key: str | None = Header(None)):
    if not _idempotent("cart_updated", idempotency_key):
        return {"received": True, "duplicate": True}
    emit_security_event("/api/v1/orchestrator/events/cart_updated", evt.model_dump())
    return {"received": True}


@router.post("/refund_requested")
def refund_requested(evt: MedusaEvent, idempotency_key: str | None = Header(None)):
    if not _idempotent("refund_requested", idempotency_key):
        return {"received": True, "duplicate": True}
    emit_security_event("/api/v1/orchestrator/events/refund_requested", evt.model_dump())
    return {"received": True}
