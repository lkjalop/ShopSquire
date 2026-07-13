from fastapi import APIRouter, Header, Depends
from src.app.models.schemas import MedusaEvent
from src.app.models.db import db_session
from src.app.policy.route_enforcement import enforce_action_authority
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
            idem_key = f"{path}:{key}"
            is_sqlite = bool(getattr(db.bind, "dialect", None) is not None and db.bind.dialect.name == "sqlite")
            if is_sqlite:
                res = db.execute(text("INSERT OR IGNORE INTO idempotency_keys (key) VALUES (:k)"), {"k": idem_key})
            else:
                res = db.execute(
                    text("INSERT INTO idempotency_keys (key) VALUES (:k) ON CONFLICT (key) DO NOTHING"),
                    {"k": idem_key},
                )
            db.commit()
            try:
                return bool(getattr(res, "rowcount", 0))
            except Exception:
                return True   # insert+commit succeeded; can't read rowcount → treat as first-seen
        except Exception:
            # P0-2: cannot verify idempotency (DB error) → do NOT default to first-seen (that
            # reprocesses a retried webhook). Re-raise so the endpoint 5xxs and the sender RETRIES
            # once the store recovers and dedup works — better than a silent double-process.
            raise


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
    data = evt.data if isinstance(evt.data, dict) else {}
    amount_cents = int(data.get("amount_cents") or round(float(data.get("amount") or 0.0) * 100))
    enforce_action_authority(
        "refund",
        value_aud_cents=max(0, amount_cents),
        context={
            "event_type": evt.type,
            "order_id": data.get("order_id"),
            "refund_reason": data.get("reason"),
            "requested_by_role": role,
        },
    )
    return {"received": True}
