from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


@dataclass
class EligibilityResult:
    eligible: bool
    reasons: List[str]
    details: Dict[str, Any]


def _parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def evaluate_eligibility(payload: Dict[str, Any], thresholds: Dict[str, Any], taxonomy: Dict[str, Any]) -> EligibilityResult:
    """Rules-first eligibility checks.

    This function is intentionally conservative: missing data => do not deny.
    """
    reasons: List[str] = []
    details: Dict[str, Any] = {}

    sku = str(payload.get("sku") or "").strip()
    if not sku:
        return EligibilityResult(eligible=False, reasons=["missing_sku"], details=details)

    # Optional SKU blacklist (config-driven)
    bl = payload.get("sku_blacklist") or thresholds.get("sku_blacklist") or []
    try:
        if sku and sku in set(map(str, bl)):
            return EligibilityResult(eligible=False, reasons=["sku_blacklisted"], details={"sku": sku})
    except Exception:
        pass

    # Optional return window evaluation
    window_days = payload.get("return_window_days") or thresholds.get("return_window_days")
    days_since = payload.get("days_since_delivery")
    if window_days is not None and days_since is not None:
        try:
            if int(days_since) > int(window_days):
                return EligibilityResult(
                    eligible=False,
                    reasons=["outside_return_window"],
                    details={"days_since_delivery": int(days_since), "return_window_days": int(window_days)},
                )
        except Exception:
            pass

    # If explicit delivery_date exists, compute days since (best-effort)
    if window_days is not None and days_since is None and payload.get("delivery_date"):
        dt = _parse_date(str(payload.get("delivery_date")))
        if dt:
            days = int((datetime.utcnow() - dt.replace(tzinfo=None)).days)
            details["days_since_delivery"] = days
            try:
                if days > int(window_days):
                    return EligibilityResult(eligible=False, reasons=["outside_return_window"], details=details)
            except Exception:
                pass

    return EligibilityResult(eligible=True, reasons=reasons, details=details)

