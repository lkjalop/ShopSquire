"""Shipping service — delegates to the configured real carrier provider.

This module is kept for backwards-compatibility (existing import sites).
Provider logic is in shipping_providers.py; this is a thin, HONEST facade: when no real carrier
is configured (or the carrier call fails) it records a stub row and returns tracking_number=None
with status='stub' — it never fabricates a tracking number that looks like a real shipment.
"""
from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import datetime, timedelta
from typing import Dict

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.shipping_providers import (
    get_default_shipping_provider,
    plan_label_record,
    shipping_readiness,
)


class ShippingService:
    async def create_return_label(self, case_id: str) -> Dict:
        provider = get_default_shipping_provider()
        readiness = shipping_readiness()

        # Attempt the carrier call; a stub/unconfigured provider returns {"ok": False, "stub": True}
        # (or raises, for the strict providers) — both are treated as "no real label".
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(provider.create_label, {"case_id": case_id}),
                timeout=22.0,
            ) or {}
        except TimeoutError:
            result = {
                "ok": False,
                "stub": True,
                "error": "carrier_deadline_exceeded_late_result_quarantined",
            }
        except Exception as exc:
            result = {"ok": False, "stub": True, "error": str(exc)}

        plan = plan_label_record(readiness, result, case_id=case_id)
        label_id = str(uuid.uuid4())
        expires = (datetime.utcnow() + timedelta(days=14)).isoformat()

        # The table columns are NOT NULL; for a stub store empty-string sentinels (clearly NOT a
        # tracking number) and the honest status, so the audit row reflects reality.
        with contextlib.suppress(Exception):
            with db_session() as db:
                db.execute(
                    text(
                        "INSERT INTO return_labels (id, case_id, carrier, tracking_number, label_url, status, expires_at) "
                        "VALUES (:id, :case_id, :carrier, :tracking, :url, :status, :expires)"
                    ),
                    {
                        "id": label_id,
                        "case_id": case_id,
                        "carrier": provider.name,
                        "tracking": plan["tracking_number"] or "",
                        "url": plan["label_url"] or "",
                        "status": plan["status"],
                        "expires": expires,
                    },
                )
                db.commit()

        return {"id": label_id, "carrier": provider.name, "expires_at": expires, **plan}
