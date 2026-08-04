"""Support-context helpers used by the V2 recommendation facade."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.platform.tenant_context import current_tenant_id
from src.app.rules.config_defaults import returns_policy_defaults
from src.app.services.cart_ttl import parse_timestamp


logger = logging.getLogger(__name__)


def parse_explicit_spec_blocks(query: str | None) -> dict[str, Any]:
    value = str(query or "")
    lowered = value.lower()
    output: dict[str, Any] = {
        "minimum": {},
        "recommended": {},
        "has_explicit_blocks": False,
    }
    if not value.strip():
        return output

    def extract(marker: str, fallback_end: str | None = None) -> str:
        index = lowered.find(marker)
        if index < 0:
            return ""
        start = index + len(marker)
        end = len(value)
        if fallback_end:
            next_index = lowered.find(fallback_end, start)
            if next_index >= 0:
                end = next_index
        return value[start:end].strip(" :.-")

    minimum = extract("minimum", "recommended")
    recommended = extract("recommended")
    if not minimum and not recommended:
        minimum_match = re.search(r"\b(min(?:imum)? specs?)\b", lowered)
        recommended_match = re.search(r"\b(recommended specs?)\b", lowered)
        if minimum_match:
            start = minimum_match.end()
            end = recommended_match.start() if recommended_match else len(value)
            minimum = value[start:end].strip(" :.-")
        if recommended_match:
            recommended = value[recommended_match.end():].strip(" :.-")

    def parse(block: str) -> dict[str, Any]:
        normalized = str(block or "").lower()
        parsed: dict[str, Any] = {}
        ram = re.search(r"(\d+)\s*gb\s*(?:ram|memory)?", normalized)
        if ram:
            parsed["ram_gb_min"] = int(ram.group(1))
        storage_tb = re.search(
            r"(\d+)\s*tb\s*(?:ssd|nvme|storage|drive)?",
            normalized,
        )
        if storage_tb:
            parsed["storage_gb_min"] = int(storage_tb.group(1)) * 1024
        else:
            storage_gb = re.search(
                r"(\d+)\s*gb\s*(?:ssd|nvme|storage|drive)",
                normalized,
            )
            if storage_gb:
                parsed["storage_gb_min"] = int(storage_gb.group(1))
        if any(token in normalized for token in (
            "rtx",
            "geforce",
            "radeon",
            "arc",
            "dedicated gpu",
            "discrete gpu",
        )):
            parsed["gpu_class"] = "discrete"
            parsed["gpu_needed"] = True
        if any(token in normalized for token in (
            "i7",
            "i9",
            "ryzen 7",
            "ryzen 9",
            "ultra 7",
            "ultra 9",
            "m3 pro",
            "m3 max",
        )):
            parsed["cpu_tier"] = "performance"
        elif any(token in normalized for token in (
            "i5",
            "ryzen 5",
            "ultra 5",
            "m2",
            "m3",
        )):
            parsed["cpu_tier"] = "midrange"
        return parsed

    output["minimum"] = parse(minimum)
    output["recommended"] = parse(recommended)
    output["has_explicit_blocks"] = bool(
        output["minimum"] or output["recommended"]
    )
    return output


def infer_account_warranty_status(uid: str | None) -> dict[str, Any]:
    user = str(uid or "").strip()
    if not user:
        return {
            "status": "unknown",
            "message": "Sign in to check coverage status.",
        }
    try:
        with db_session() as db:
            try:
                latest_order = db.execute(text(
                    "SELECT id, status, created_at FROM orders "
                    "WHERE customer_id = :uid ORDER BY created_at DESC LIMIT 1"
                ), {"uid": user}).fetchone()
            except Exception:
                latest_order = None
            try:
                session_link = db.execute(text(
                    "SELECT order_id, created_at FROM order_sessions "
                    "WHERE uid = :uid ORDER BY created_at DESC LIMIT 1"
                ), {"uid": user}).fetchone()
            except Exception:
                session_link = None
            has_warranty_like = False
            try:
                rows = db.execute(text(
                    "SELECT line_items FROM draft_orders "
                    "WHERE customer_id = :uid AND tenant_id = :tenant "
                    "ORDER BY updated_at DESC LIMIT 3"
                ), {
                    "uid": user,
                    "tenant": current_tenant_id(),
                }).fetchall()
                for row in rows or []:
                    raw = str(row[0] or "")
                    if any(token in raw.lower() for token in (
                        "warranty",
                        "care+",
                        "accidental damage",
                        "protection plan",
                    )):
                        has_warranty_like = True
                        break
            except Exception:
                has_warranty_like = False
            order_ref = str(
                (
                    latest_order[0]
                    if latest_order
                    else session_link[0]
                    if session_link
                    else ""
                ) or ""
            )
            if has_warranty_like:
                return {
                    "status": "likely_extended",
                    "message": (
                        "Protection-plan signals were found in your recent "
                        "basket/order data."
                    ),
                    "order_ref": order_ref,
                }
            if latest_order:
                try:
                    purchased_at = parse_timestamp(
                        latest_order[2] if len(latest_order) > 2 else None,
                    )
                    window = int(
                        (returns_policy_defaults() or {}).get(
                            "warranty_window_days",
                            365,
                        ) or 365
                    )
                    if purchased_at is not None:
                        age = max(0, (datetime.utcnow() - purchased_at).days)
                        if age <= window:
                            return {
                                "status": "in_warranty_window",
                                "message": (
                                    f"Your latest purchase is {age} day(s) old "
                                    f"— inside the {window}-day warranty window."
                                ),
                                "order_ref": order_ref,
                                "purchase_age_days": age,
                            }
                        return {
                            "status": "window_expired_guarantees_may_apply",
                            "message": (
                                f"Your latest purchase is {age} day(s) old — "
                                f"beyond the {window}-day warranty window, but "
                                "consumer-law guarantees can still apply "
                                "(durability is assessed, not capped by the window)."
                            ),
                            "order_ref": order_ref,
                            "purchase_age_days": age,
                        }
                except Exception as exc:
                    logger.debug("warranty window arithmetic skipped: %s", exc)
            if latest_order or session_link:
                return {
                    "status": "needs_verification",
                    "message": (
                        "Order history found. Verify receipt/order details to "
                        "confirm exact coverage terms."
                    ),
                    "order_ref": order_ref,
                }
            return {
                "status": "not_found",
                "message": (
                    "No linked order history found for this account. Upload "
                    "receipt/order reference to continue."
                ),
            }
    except Exception:
        return {
            "status": "unknown",
            "message": (
                "Coverage lookup unavailable right now; proceed with receipt "
                "verification."
            ),
        }
