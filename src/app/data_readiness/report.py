from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from src.app.models.db import db_session


@dataclass(frozen=True)
class ReadinessReport:
    score: float
    level: str  # "good" | "warn" | "bad"
    checks: List[Dict[str, Any]]
    summary: Dict[str, Any]


def _age_hours(ts: str | None) -> Optional[float]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        try:
            dt = datetime.fromisoformat(str(ts))
        except Exception:
            return None
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return max(0.0, (datetime.utcnow() - dt).total_seconds() / 3600.0)


def compute_inventory_readiness(*, freshness_hours: int = 48) -> ReadinessReport:
    """Compute a conservative data-readiness score for inventory/ERP automation.

    Goal: block autonomous actions when the customer's data is missing/stale/conflicting.
    """
    checks: List[Dict[str, Any]] = []
    score = 1.0
    summary: Dict[str, Any] = {}

    with db_session() as db:
        # Coverage
        products = 0
        inventory_rows = 0
        try:
            products = int(db.execute(text("SELECT COUNT(*) FROM products")).scalar() or 0)
        except Exception:
            products = 0
        try:
            inventory_rows = int(db.execute(text("SELECT COUNT(*) FROM inventory")).scalar() or 0)
        except Exception:
            inventory_rows = 0
        summary.update({"products": products, "inventory_rows": inventory_rows})
        if products <= 0:
            score -= 0.6
            checks.append({"id": "inv.products_missing", "ok": False, "message": "No products found."})
        else:
            checks.append({"id": "inv.products_present", "ok": True, "message": f"{products} products."})
        if inventory_rows <= 0:
            score -= 0.6
            checks.append({"id": "inv.inventory_missing", "ok": False, "message": "No inventory rows found."})
        else:
            checks.append({"id": "inv.inventory_present", "ok": True, "message": f"{inventory_rows} inventory rows."})

        # Freshness
        p_ts = None
        i_ts = None
        try:
            p_ts = db.execute(text("SELECT MAX(updated_at) FROM products")).scalar()
        except Exception:
            p_ts = None
        try:
            i_ts = db.execute(text("SELECT MAX(updated_at) FROM inventory")).scalar()
        except Exception:
            i_ts = None
        p_age = _age_hours(str(p_ts) if p_ts is not None else None)
        i_age = _age_hours(str(i_ts) if i_ts is not None else None)
        summary.update({"products_updated_at": str(p_ts) if p_ts is not None else None, "inventory_updated_at": str(i_ts) if i_ts is not None else None})

        if p_age is None or p_age > freshness_hours:
            score -= 0.25
            checks.append({"id": "inv.products_stale", "ok": False, "message": f"Products appear stale (age_hours={p_age})."})
        else:
            checks.append({"id": "inv.products_fresh", "ok": True, "message": f"Products fresh (age_hours={round(p_age, 2)})."})

        if i_age is None or i_age > freshness_hours:
            score -= 0.25
            checks.append({"id": "inv.inventory_stale", "ok": False, "message": f"Inventory appears stale (age_hours={i_age})."})
        else:
            checks.append({"id": "inv.inventory_fresh", "ok": True, "message": f"Inventory fresh (age_hours={round(i_age, 2)})."})

        # Referential integrity (best-effort): inventory.product_id should resolve
        try:
            missing = int(
                db.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM inventory i
                        LEFT JOIN products p ON p.id = i.product_id
                        WHERE i.product_id IS NOT NULL AND p.id IS NULL
                        """
                    )
                ).scalar()
                or 0
            )
        except Exception:
            missing = 0
        summary["inventory_missing_products"] = missing
        if missing > 0:
            score -= 0.25
            checks.append({"id": "inv.orphans", "ok": False, "message": f"{missing} inventory rows reference missing products."})
        else:
            checks.append({"id": "inv.orphans", "ok": True, "message": "No orphan inventory rows detected."})

    score = max(0.0, min(1.0, float(score)))
    if score >= 0.8:
        level = "good"
    elif score >= 0.55:
        level = "warn"
    else:
        level = "bad"
    return ReadinessReport(score=score, level=level, checks=checks, summary=summary)

