"""Procurement fraud signals (agnostic CORE) — amendment-churn + cancellation-abuse detection.

Two attack vectors on the fluid-procurement flow:
  • amendment-churn DoS — a buyer amends an order dozens of times, thrashing sourcing and (post-send) spamming
    suppliers with redrafts. Bounded by a per-PR amendment cap.
  • fraudulent cancellation — a buyer repeatedly CANCELS after the supplier PO is committed, extracting value
    while the business eats restock + penalties. Flagged by a post-commitment cancellation pattern.

Pure signals over COUNTS — vertical-blind, no PII beyond an opaque buyer key — feeding the gate + governance.
Caps default from the StoreProfile (agnostic policy DATA). Pure; never raises.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

DEFAULT_AMENDMENT_CAP = 10               # amendments to one PR before it must go to a human (churn brake)
DEFAULT_POST_COMMIT_CANCEL_CAP = 3       # post-commitment cancellations before a buyer is flagged


def _profile(slot: str, default: Any) -> Any:
    try:
        from src.app.platform.store_profile import profile_slot
        v = profile_slot(slot, default=None)
        return v if v is not None else default
    except Exception:
        return default


def _int(v: Any) -> int:
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return 0


def assess_amendments(*, amendment_count: Any, cap: Optional[int] = None) -> Dict[str, Any]:
    """Whether a PR has been amended too many times (churn brake). At/over the cap → over_cap (route to a human
    / cool-down) so a single order can't thrash sourcing indefinitely."""
    c = int(cap if cap is not None else _profile("amendment_cap", DEFAULT_AMENDMENT_CAP))
    n = _int(amendment_count)
    return {"amendment_count": n, "cap": c, "over_cap": n >= c}


def assess_cancellation_pattern(*, post_commit_cancellations: Any, total_orders: Any = 0,
                                cap: Optional[int] = None) -> Dict[str, Any]:
    """Whether a buyer's POST-COMMITMENT cancellations look abusive. At/over the cap → flagged (feeds the fraud
    scorer + the human cancellation gate). Also reports the cancellation RATE for context."""
    c = int(cap if cap is not None else _profile("post_commit_cancellation_cap", DEFAULT_POST_COMMIT_CANCEL_CAP))
    n = _int(post_commit_cancellations)
    total = _int(total_orders)
    rate = round(n / total, 4) if total else 0.0
    return {"post_commit_cancellations": n, "cap": c, "flagged": n >= c, "cancellation_rate": rate,
            "total_orders": total}
