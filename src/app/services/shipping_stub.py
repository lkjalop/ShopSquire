"""Shipping service — delegates to the configured real carrier provider.

This module is kept for backwards-compatibility (existing import sites).
All logic is in shipping_providers.py; this is now a thin facade.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Dict
from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.shipping_providers import get_default_shipping_provider


class ShippingService:
    async def create_return_label(self, case_id: str) -> Dict:
        provider = get_default_shipping_provider()
        label_id = str(uuid.uuid4())
        tracking = f"RR{uuid.uuid4().hex[:10].upper()}"
        expires = (datetime.utcnow() + timedelta(days=14)).isoformat()
        result = provider.create_label({"case_id": case_id, "tracking_number": tracking})
        label_url = (
            (result.get("raw") or {}).get("postage_label", {}).get("label_url")
            or result.get("label_url")
            or f"pending://{case_id}"
        )
        with db_session() as db:
            try:
                db.execute(
                    text(
                        "INSERT INTO return_labels (id, case_id, carrier, tracking_number, label_url, status, expires_at) "
                        "VALUES (:id, :case_id, :carrier, :tracking, :url, 'generated', :expires)"
                    ),
                    {"id": label_id, "case_id": case_id, "carrier": provider.name, "tracking": tracking, "url": label_url, "expires": expires},
                )
                db.commit()
            except Exception:
                pass
        return {"id": label_id, "carrier": provider.name, "tracking_number": tracking, "label_url": label_url, "expires_at": expires}
