"""Carrier webhook endpoints for inbound shipping status updates.

EasyPost  → POST /api/v1/shipping/webhook/easypost
ShipStation → POST /api/v1/shipping/webhook/shipstation
AusPost   → POST /api/v1/shipping/webhook/auspost
StarTrack → POST /api/v1/shipping/webhook/startrack  (same infrastructure as AusPost)

Each provider sends status events when a parcel moves through the carrier network.
We translate those events into order status transitions and persist the tracking number.

Status mapping (carrier → orders.status):
  in_transit / out_for_delivery → "shipped"   (if currently "paid" or "fulfilling")
  delivered                     → "delivered" (if currently "shipped")
  return_to_sender              → "return_requested"
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text as sql_text

from src.app.models.db import db_session

router = APIRouter(prefix="/api/v1/shipping/webhook", tags=["shipping-webhooks"])
_log = logging.getLogger("shopsquire.shipping_webhooks")

# ── shared helpers ─────────────────────────────────────────────────────────────

_TRANSIT_STATUSES = {"in_transit", "out_for_delivery", "pre_transit", "accepted", "accepted_at_origin"}
_DELIVERED_STATUSES = {"delivered"}
_RETURNED_STATUSES = {"return_to_sender", "returned_to_sender", "undeliverable", "voided"}


def _transition_order(tracking_number: str, new_status: str, carrier: str) -> bool:
    """Update order row keyed by tracking_number.  Returns True if a row was changed."""
    allowed_from: set[str] = set()
    if new_status == "shipped":
        allowed_from = {"paid", "fulfilling", "created"}
    elif new_status == "delivered":
        allowed_from = {"shipped"}
    elif new_status == "return_requested":
        allowed_from = {"shipped", "delivered"}
    else:
        return False

    placeholders = ", ".join(f"'{s}'" for s in allowed_from)
    with db_session() as db:
        result = db.execute(
            sql_text(
                f"UPDATE orders SET status = :ns, tracking_number = :tn, carrier = :carrier, "
                f"updated_at = CURRENT_TIMESTAMP "
                f"WHERE tracking_number = :tn AND status IN ({placeholders})"
            ),
            {"ns": new_status, "tn": tracking_number, "carrier": carrier},
        )
        db.commit()
    changed = getattr(result, "rowcount", 0) or 0
    if changed:
        _log.info("shipping_webhook: %s → %s (tracking=%s)", carrier, new_status, tracking_number)
    return bool(changed)


def _require_secret_outside_dev(carrier: str, secret: str) -> None:
    """Fail CLOSED in non-dev when a carrier webhook secret is unset: an unsigned carrier event can
    transition orders (shipped/delivered), so accepting it unverified in production is an order-state
    forgery vector. Dev/test keeps the warn-and-accept path so flows run without carrier credentials."""
    if secret:
        return
    env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
    if env not in ("local", "dev", "development", "test", "testing"):
        _log.error("%s_webhook: webhook secret not configured in %s — rejecting unverified event (fail closed)",
                   carrier, env)
        raise HTTPException(status_code=503, detail=f"{carrier} webhook signature verification not configured")
    _log.warning("%s_webhook: webhook secret not set — skipping verification (dev only)", carrier)


def _verify_easypost_hmac(body: bytes, sig_header: str, secret: str) -> bool:
    if not secret:
        return True  # verification skipped — logged below
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header.strip())


# ── EasyPost ──────────────────────────────────────────────────────────────────

@router.post("/easypost")
async def easypost_webhook(request: Request) -> Dict[str, Any]:
    body = await request.body()
    sig = request.headers.get("X-Hmac-Signature-256", "")
    secret = os.environ.get("EASYPOST_WEBHOOK_SECRET", "").strip()

    if secret and not _verify_easypost_hmac(body, sig, secret):
        _log.warning("easypost_webhook: invalid HMAC signature")
        raise HTTPException(status_code=400, detail="Invalid EasyPost webhook signature")
    elif not secret:
        _require_secret_outside_dev("easypost", secret)

    try:
        event = json.loads(body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")

    event_type = str(event.get("description") or "").lower()
    tracker = (event.get("result") or {})
    tracking_number = str(tracker.get("tracking_code") or "").strip()
    carrier = str(tracker.get("carrier") or "easypost").lower()
    status_raw = str(tracker.get("status") or "").lower()

    if not tracking_number:
        return {"received": True, "action": "skipped", "reason": "no_tracking_code"}

    new_status = None
    if status_raw in _TRANSIT_STATUSES:
        new_status = "shipped"
    elif status_raw in _DELIVERED_STATUSES:
        new_status = "delivered"
    elif status_raw in _RETURNED_STATUSES:
        new_status = "return_requested"

    if new_status:
        changed = _transition_order(tracking_number, new_status, carrier)
        return {"received": True, "tracking": tracking_number, "new_status": new_status, "changed": changed}

    return {"received": True, "tracking": tracking_number, "status_raw": status_raw, "action": "no_transition"}


# ── ShipStation ───────────────────────────────────────────────────────────────

@router.post("/shipstation")
async def shipstation_webhook(request: Request) -> Dict[str, Any]:
    # ShipStation sends Basic Auth with the configured webhook credentials.
    # Check the "X-ShipStation-Hmac-SHA256" header when a secret is set.
    body = await request.body()
    secret = os.environ.get("SHIPSTATION_WEBHOOK_SECRET", "").strip()

    if secret:
        sig = request.headers.get("X-ShipStation-Hmac-SHA256", "")
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig.strip()):
            _log.warning("shipstation_webhook: invalid HMAC signature")
            raise HTTPException(status_code=400, detail="Invalid ShipStation webhook signature")
    else:
        _require_secret_outside_dev("shipstation", secret)

    try:
        event = json.loads(body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")

    resource_type = str(event.get("resource_type") or "").upper()
    resource_url = str(event.get("resource_url") or "")

    if resource_type != "SHIP_NOTIFY":
        return {"received": True, "action": "skipped", "resource_type": resource_type}

    # ShipStation webhook carries the resource URL but not full detail inline —
    # for now record the event and let a background sync job fetch details.
    _log.info("shipstation_webhook: SHIP_NOTIFY from %s", resource_url)
    return {"received": True, "resource_type": resource_type, "action": "queued"}


# ── AusPost / StarTrack ───────────────────────────────────────────────────────
# AusPost pushes tracking events via their Merchant Notifications API.
# The payload wraps one or more articles with status codes.

_AUSPOST_STATUS_MAP = {
    "TRANSIT": "shipped",
    "IN_TRANSIT": "shipped",
    "DELIVERED": "delivered",
    "DELIVERED_PARCEL": "delivered",
    "DELIVERED_PARCEL_COLLECT": "delivered",
    "RETURN_TO_SENDER": "return_requested",
    "ATTEMPTED_DELIVERY": "shipped",
    "ONBOARD_FOR_DELIVERY": "shipped",
}


@router.post("/auspost")
async def auspost_webhook(request: Request) -> Dict[str, Any]:
    return await _handle_auspost_event(request, carrier_name="auspost")


@router.post("/startrack")
async def startrack_webhook(request: Request) -> Dict[str, Any]:
    return await _handle_auspost_event(request, carrier_name="startrack")


async def _handle_auspost_event(request: Request, carrier_name: str) -> Dict[str, Any]:
    body = await request.body()
    secret = os.environ.get(
        "AUSPOST_WEBHOOK_SECRET" if carrier_name == "auspost" else "STARTRACK_WEBHOOK_SECRET",
        os.environ.get("AUSPOST_WEBHOOK_SECRET", ""),
    ).strip()

    if secret:
        sig = request.headers.get("X-AusPost-Signature", "")
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig.strip()):
            _log.warning("%s_webhook: invalid signature", carrier_name)
            raise HTTPException(status_code=400, detail=f"Invalid {carrier_name} webhook signature")
    else:
        _require_secret_outside_dev(carrier_name, secret)

    try:
        event = json.loads(body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")

    # AusPost notification format: {"articles": [{"article_id": "...", "events": [...]}]}
    articles = event.get("articles") or []
    if not articles and isinstance(event.get("article_id"), str):
        articles = [event]  # single-article flat format

    results = []
    for article in articles:
        tracking_number = str(article.get("article_id") or article.get("tracking_number") or "").strip()
        if not tracking_number:
            continue
        events = article.get("events") or []
        if events:
            latest_event = events[0]
            status_raw = str(latest_event.get("type") or latest_event.get("status") or "").upper()
        else:
            status_raw = str(article.get("status") or "").upper()

        new_status = _AUSPOST_STATUS_MAP.get(status_raw)
        if new_status:
            changed = _transition_order(tracking_number, new_status, carrier_name)
            results.append({"tracking": tracking_number, "new_status": new_status, "changed": changed})
        else:
            results.append({"tracking": tracking_number, "status_raw": status_raw, "action": "no_transition"})

    return {"received": True, "carrier": carrier_name, "processed": results}
