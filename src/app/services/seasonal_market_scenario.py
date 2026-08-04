"""Deterministic, isolated market-history scenarios for demos and regression labs.

These facts are not customer traffic and never enter a production tenant. They use
the governed canonical contracts so BI and market-policy tests exercise the same
schema, deduplication, provenance and tenant boundaries as real connectors.
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List


def _seed(value: str) -> int:
    return int.from_bytes(hashlib.sha256(value.encode("utf-8")).digest()[:8], "big")


def build_back_to_school_scenario(products: Iterable[Dict[str, Any]], *, tenant_id: str,
                                  year: int = 2026, max_products: int = 12,
                                  seed: int = 20260724) -> Dict[str, List[Dict[str, Any]]]:
    """Build Jan-Mar AU back-to-school funnel and ATP facts.

    Demand is intentionally strongest from late January through February and
    normalizes in March. The curve is a documented scenario assumption, not a
    forecast or training label.
    """
    tenant = str(tenant_id or "").strip()
    if not tenant.startswith("synthetic-"):
        raise ValueError("seasonal scenarios require an isolated synthetic-* tenant")
    rows = [dict(row) for row in products if int(row.get("price_cents") or 0) > 0]
    rows = sorted(rows, key=lambda row: str(row.get("sku") or ""))[:max_products]
    marketing: List[Dict[str, Any]] = []
    atp: List[Dict[str, Any]] = []
    start = datetime(year, 1, 5, 9, 0, tzinfo=timezone.utc)
    for week in range(13):
        week_start = start + timedelta(days=7 * week)
        demand_multiplier = 1.0
        if 3 <= week <= 7:
            demand_multiplier = 1.65
        elif 8 <= week <= 9:
            demand_multiplier = 1.25
        elif week >= 10:
            demand_multiplier = 0.8
        for product_index, product in enumerate(rows):
            sku = str(product.get("sku") or "").strip()
            currency = str(product.get("currency") or "AUD").upper()
            price = int(product.get("price_cents") or 0)
            if not sku:
                continue
            rng = random.Random(seed + _seed(f"{sku}:{week}"))
            sessions = max(2, int(round((4 + product_index % 3) * demand_multiplier)))
            purchases = 0
            for session_index in range(sessions):
                session = f"{tenant}:{year}:w{week:02d}:{sku}:{session_index}"
                occurred = week_start + timedelta(hours=session_index)
                path = ["view_item"]
                if rng.random() < 0.72:
                    path.append("select_item")
                if rng.random() < 0.42:
                    path.append("add_to_cart")
                    if rng.random() < (0.58 if 3 <= week <= 8 else 0.42):
                        path.append("purchase")
                        purchases += 1
                for event_index, event in enumerate(path):
                    record = f"{session}:{event_index}:{event}"
                    marketing.append({
                        "tenant_id": tenant, "deduplication_id": f"scenario:{record}",
                        "event_type": event, "subject_hash": hashlib.sha256(session.encode()).hexdigest(),
                        "session_id": session, "sku": sku,
                        "campaign_id": "au-back-to-school", "creative_id": f"week-{week:02d}",
                        "channel": "synthetic_scenario", "value": price if event == "purchase" else None,
                        "currency": currency if event == "purchase" else None,
                        "quantity": 1, "consent_state": "granted", "attribution_window": "7d_click",
                        "source_system": "synthetic_scenario", "source_record_id": record,
                        "occurred_at": (occurred + timedelta(minutes=event_index)).isoformat(),
                        "provenance_chain": ["scenario/au-back-to-school-v1", f"week/{week}", f"products/{sku}"],
                        "confidence": 1.0, "freshness_policy": "scenario_history_only",
                    })
            if purchases and rng.random() < 0.08:
                return_session = f"{tenant}:{year}:w{week:02d}:{sku}:return"
                marketing.append({
                    "tenant_id": tenant, "deduplication_id": f"scenario:{return_session}",
                    "event_type": "return", "subject_hash": hashlib.sha256(return_session.encode()).hexdigest(),
                    "session_id": return_session, "sku": sku, "campaign_id": "au-back-to-school",
                    "channel": "synthetic_scenario", "value": price, "currency": currency, "quantity": 1,
                    "consent_state": "not_required", "attribution_window": "order_lifecycle",
                    "source_system": "synthetic_scenario", "source_record_id": return_session,
                    "occurred_at": (week_start + timedelta(days=1)).isoformat(),
                    "provenance_chain": ["scenario/au-back-to-school-v1", f"returns/{sku}/week/{week}"],
                    "confidence": 1.0, "freshness_policy": "scenario_history_only",
                })
            on_hand = max(0, 35 - int(week * demand_multiplier) - product_index)
            incoming = 20 if week in {2, 6} else 0
            atp_record = f"{tenant}:{year}:w{week:02d}:{sku}:sydney"
            atp.append({
                "tenant_id": tenant, "deduplication_id": f"scenario-atp:{atp_record}",
                "material_id": sku, "sku": sku, "location_id": "sydney",
                "on_hand_quantity": on_hand, "committed_quantity": min(5, purchases),
                "incoming_receipts_quantity": incoming, "safety_stock_quantity": 5,
                "lead_time_days": 7 + product_index % 4,
                "confirmed_quantity": max(0, on_hand - min(5, purchases)),
                "source_system": "synthetic_scenario", "source_record_id": atp_record,
                "observed_at": week_start.isoformat(),
                "provenance_chain": ["scenario/au-back-to-school-v1", f"atp/{sku}/sydney/week/{week}"],
                "confidence": 1.0, "freshness_policy": "scenario_history_only",
            })
    return {"marketing": marketing, "atp": atp}
