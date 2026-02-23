"""Per-vendor invoice baseline storage and anomaly detection.

Maintains a rolling window of invoice amounts per vendor and flags
anomalies when a new invoice deviates significantly from the vendor's
historical pattern (z-score > threshold).

Storage is in-memory by default; swap ``_store`` for a DB-backed dict
in production.
"""
from __future__ import annotations

import math
import os
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_WINDOW_DAYS = int(os.getenv("VENDOR_BASELINE_WINDOW_DAYS", "90"))
_Z_THRESHOLD = float(os.getenv("VENDOR_BASELINE_Z_THRESHOLD", "2.0"))
_MIN_SAMPLES = int(os.getenv("VENDOR_BASELINE_MIN_SAMPLES", "3"))

# ---------------------------------------------------------------------------
# In-memory store: vendor_domain → list of (timestamp, amount)
# ---------------------------------------------------------------------------
_store: Dict[str, List[Tuple[float, float]]] = defaultdict(list)


def _prune(vendor: str, now: float | None = None) -> None:
    """Remove entries older than the rolling window."""
    cutoff = (now or time.time()) - _WINDOW_DAYS * 86400
    _store[vendor] = [(ts, amt) for ts, amt in _store[vendor] if ts >= cutoff]


def record_invoice(vendor_domain: str, amount: float, timestamp: float | None = None) -> None:
    """Record a new invoice amount for a vendor."""
    ts = timestamp or time.time()
    _store[vendor_domain].append((ts, amount))
    _prune(vendor_domain, ts)


def get_baseline(vendor_domain: str) -> Optional[Dict[str, Any]]:
    """Return rolling mean, std, count for a vendor.  None if insufficient data."""
    _prune(vendor_domain)
    entries = _store.get(vendor_domain, [])
    if len(entries) < _MIN_SAMPLES:
        return None
    amounts = [a for _, a in entries]
    n = len(amounts)
    mean = sum(amounts) / n
    variance = sum((a - mean) ** 2 for a in amounts) / n
    std = math.sqrt(variance) if variance > 0 else 0.0
    return {
        "vendor_domain": vendor_domain,
        "count": n,
        "mean": round(mean, 2),
        "std": round(std, 2),
        "min": round(min(amounts), 2),
        "max": round(max(amounts), 2),
        "window_days": _WINDOW_DAYS,
    }


def check_anomaly(vendor_domain: str, amount: float) -> Dict[str, Any]:
    """Check whether ``amount`` is anomalous relative to the vendor baseline.

    Returns a dict with:
    - ``anomaly``: bool
    - ``z_score``: float (how many std deviations from mean)
    - ``baseline``: the baseline dict or None
    - ``reason``: human-readable explanation
    """
    baseline = get_baseline(vendor_domain)
    if baseline is None:
        return {
            "anomaly": False,
            "z_score": 0.0,
            "baseline": None,
            "reason": f"Insufficient data for {vendor_domain} (need >= {_MIN_SAMPLES} invoices)",
        }
    mean = baseline["mean"]
    std = baseline["std"]
    if std == 0:
        z = 0.0 if amount == mean else float("inf")
    else:
        z = (amount - mean) / std

    is_anomaly = abs(z) >= _Z_THRESHOLD
    return {
        "anomaly": is_anomaly,
        "z_score": round(z, 3),
        "baseline": baseline,
        "reason": (
            f"Amount ${amount:,.2f} is {abs(z):.1f}σ from vendor mean ${mean:,.2f} (threshold {_Z_THRESHOLD}σ)"
            if is_anomaly
            else f"Amount ${amount:,.2f} is within normal range for {vendor_domain}"
        ),
    }


def list_vendors() -> List[str]:
    """Return list of vendor domains with recorded baselines."""
    return sorted(_store.keys())


def clear_vendor(vendor_domain: str) -> None:
    """Remove all baseline data for a vendor."""
    _store.pop(vendor_domain, None)


def clear_all() -> None:
    """Remove all baseline data (for testing)."""
    _store.clear()
