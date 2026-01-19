from fastapi import APIRouter, HTTPException
from typing import Dict

from src.app.config import get_settings
from src.app.services.payments import StripeClientStub
from src.app.models.db import db_session


router = APIRouter(prefix="/api/v1/payments", tags=["payments"])


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


@router.post("/intent")
def create_intent(amount_cents: int, currency: str = "USD", idempotency_key: str | None = None) -> Dict:
    settings = get_settings()
    client = StripeClientStub(settings.stripe_api_key)
    if not _idempotent("payment_intent", idempotency_key):
        raise HTTPException(status_code=409, detail="Duplicate payment intent")
    return client.create_payment_intent(amount_cents, currency)
