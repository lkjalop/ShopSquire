from __future__ import annotations

import hmac
import hashlib
import base64
from typing import Dict
from fastapi import APIRouter, Request, HTTPException

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


def _verify_shopify_hmac(secret: str, body: bytes, signature: str) -> bool:
    try:
        digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
        expected = base64.b64encode(digest).decode("ascii")
        # constant-time compare
        return hmac.compare_digest(expected, signature or "")
    except Exception:
        return False


@router.post("/shopify")
async def shopify_webhook(request: Request) -> Dict[str, any]:
    secret = (request.app and request.app.state and getattr(request.app.state, "shopify_secret", None)) or None
    if not secret:
        import os
        secret = os.getenv("SHOPIFY_WEBHOOK_SECRET")
    body = await request.body()
    sig = request.headers.get("X-Shopify-Hmac-SHA256") or ""
    if not secret:
        raise HTTPException(status_code=400, detail="missing_secret")
    if not _verify_shopify_hmac(secret, body, sig):
        raise HTTPException(status_code=401, detail="invalid_signature")
    # Best-effort: parse JSON payload
    try:
        import json
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        payload = None
    return {"received": True, "valid": True, "topic": request.headers.get("X-Shopify-Topic"), "payload": payload}