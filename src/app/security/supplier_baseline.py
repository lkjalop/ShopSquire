"""Per-supplier email behavioural baseline.

Builds a time-series profile per (tenant, sender_domain) that tracks:
- Send frequency (messages per rolling window)
- Typical send hours (hour-of-day histogram)
- Invoice amount statistics (mean / stddev → z-score for anomaly)
- Attachment count baseline

Anomalies are flagged when current email deviates significantly from
the learned baseline, providing an additional BEC-detection signal.

ENV configuration
-----------------
BASELINE_WINDOW_DAYS       – Rolling window for frequency stats (default 90)
BASELINE_FREQUENCY_ZSCORE  – Z-score threshold for frequency anomaly (default 2.5)
BASELINE_AMOUNT_ZSCORE     – Z-score threshold for invoice amount anomaly (default 2.5)
BASELINE_HOUR_DEVIATION    – Max hours from mean send hour before flagging (default 6)
BASELINE_MIN_OBSERVATIONS  – Minimum data points before baseline applies (default 5)
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from src.app.models.db import db_session

logger = logging.getLogger("shopsquire.supplier_baseline")


def _env_float(key: str, default: float) -> float:
    try:
        v = os.getenv(key)
        if v is None or str(v).strip() == "":
            return default
        return float(str(v).strip())
    except Exception:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        v = os.getenv(key)
        if v is None or str(v).strip() == "":
            return default
        return max(1, int(float(str(v).strip())))
    except Exception:
        return default


def _hash16(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------

def _ensure_tables() -> None:
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS supplier_baseline_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tenant_id TEXT NOT NULL,
                        sender_domain_hash TEXT NOT NULL,
                        event_ts TEXT NOT NULL,
                        hour_of_day INTEGER NOT NULL,
                        invoice_amount REAL,
                        attachment_count INTEGER DEFAULT 0,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            db.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_sbe_tenant_sender "
                    "ON supplier_baseline_events(tenant_id, sender_domain_hash)"
                )
            )
            db.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_sbe_ts "
                    "ON supplier_baseline_events(event_ts)"
                )
            )
            db.commit()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Record an email event
# ---------------------------------------------------------------------------

def record_email_event(
    *,
    tenant_id: str,
    sender_domain: str,
    event_datetime: datetime | str | None = None,
    invoice_amount: float | None = None,
    attachment_count: int = 0,
) -> None:
    """Record an email event for baseline learning."""
    _ensure_tables()
    tenant = str(tenant_id or "default")
    sdh = _hash16(sender_domain) or "unknown"

    if event_datetime is None:
        dt = datetime.now(timezone.utc)
    elif isinstance(event_datetime, str):
        try:
            s = event_datetime.strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
        except Exception:
            dt = datetime.now(timezone.utc)
    else:
        dt = event_datetime

    hour = dt.hour
    ts_iso = dt.isoformat()

    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    INSERT INTO supplier_baseline_events
                    (tenant_id, sender_domain_hash, event_ts, hour_of_day, invoice_amount, attachment_count)
                    VALUES (:tenant, :sdh, :ts, :hour, :amount, :att_count)
                    """
                ),
                {
                    "tenant": tenant,
                    "sdh": sdh,
                    "ts": ts_iso,
                    "hour": hour,
                    "amount": invoice_amount,
                    "att_count": int(attachment_count or 0),
                },
            )
            db.commit()
    except Exception as exc:
        logger.warning("baseline record failed: %s", exc)


# ---------------------------------------------------------------------------
# Baseline analysis
# ---------------------------------------------------------------------------

def analyze_against_baseline(
    *,
    tenant_id: str,
    sender_domain: str,
    current_datetime: datetime | str | None = None,
    invoice_amount: float | None = None,
    attachment_count: int = 0,
) -> Dict[str, Any]:
    """Compare the current email against the sender's learned baseline.

    Returns a dict with anomaly indicators and baseline stats.
    """
    _ensure_tables()
    tenant = str(tenant_id or "default")
    sdh = _hash16(sender_domain) or "unknown"

    window_days = _env_int("BASELINE_WINDOW_DAYS", 90)
    freq_z = _env_float("BASELINE_FREQUENCY_ZSCORE", 2.5)
    amount_z = _env_float("BASELINE_AMOUNT_ZSCORE", 2.5)
    hour_dev = _env_int("BASELINE_HOUR_DEVIATION", 6)
    min_obs = _env_int("BASELINE_MIN_OBSERVATIONS", 5)

    if current_datetime is None:
        now = datetime.now(timezone.utc)
    elif isinstance(current_datetime, str):
        try:
            s = current_datetime.strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            now = datetime.fromisoformat(s)
        except Exception:
            now = datetime.now(timezone.utc)
    else:
        now = current_datetime

    cutoff = (now - timedelta(days=window_days)).isoformat()
    current_hour = now.hour

    # Fetch baseline data
    rows: List[Any] = []
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT event_ts, hour_of_day, invoice_amount, attachment_count
                    FROM supplier_baseline_events
                    WHERE tenant_id = :tenant
                      AND sender_domain_hash = :sdh
                      AND event_ts >= :cutoff
                    ORDER BY event_ts ASC
                    """
                ),
                {"tenant": tenant, "sdh": sdh, "cutoff": cutoff},
            ).fetchall()
    except Exception:
        rows = []

    n = len(rows)
    indicators: List[Dict[str, Any]] = []

    if n < min_obs:
        return {
            "baseline_available": False,
            "observation_count": n,
            "min_observations": min_obs,
            "indicators": [],
            "meta": {"sender_domain_hash": sdh, "window_days": window_days},
        }

    # 1) Frequency analysis: messages per week
    timestamps = []
    hours: List[int] = []
    amounts: List[float] = []
    att_counts: List[int] = []
    for r in rows:
        try:
            ts = datetime.fromisoformat(str(r[0]))
            timestamps.append(ts)
        except Exception:
            pass
        hours.append(int(r[1]))
        if r[2] is not None:
            amounts.append(float(r[2]))
        att_counts.append(int(r[3] or 0))

    if len(timestamps) >= 2:
        span_days = max(1, (timestamps[-1] - timestamps[0]).total_seconds() / 86400.0)
        msgs_per_week = (n / span_days) * 7.0
        # Compute per-week counts for stddev
        week_counts: Dict[int, int] = {}
        for ts in timestamps:
            week_key = int(ts.timestamp() // (7 * 86400))
            week_counts[week_key] = week_counts.get(week_key, 0) + 1
        wc_values = list(week_counts.values())
        wc_mean = sum(wc_values) / max(1, len(wc_values))
        wc_var = sum((x - wc_mean) ** 2 for x in wc_values) / max(1, len(wc_values))
        wc_std = math.sqrt(wc_var) if wc_var > 0 else 0.0

        # Check if current timing is anomalous (days since last message)
        days_since_last = (now - timestamps[-1]).total_seconds() / 86400.0
        expected_gap = span_days / max(1, n - 1) if n > 1 else span_days
        gap_std = wc_std * (expected_gap / max(0.1, wc_mean)) if wc_mean > 0 else 0.0
        if gap_std > 0 and days_since_last > 0:
            gap_zscore = (days_since_last - expected_gap) / max(0.01, gap_std)
            if gap_zscore > freq_z:
                indicators.append({
                    "type": "baseline_frequency_anomaly",
                    "value": round(days_since_last, 1),
                    "reason": f"Days since last email ({round(days_since_last, 1)}) exceeds baseline (expected ~{round(expected_gap, 1)}d, z={round(gap_zscore, 1)})",
                })
    else:
        msgs_per_week = 0.0

    # 2) Hour-of-day analysis
    if hours:
        mean_hour = sum(hours) / len(hours)
        hour_diff = min(abs(current_hour - mean_hour), 24 - abs(current_hour - mean_hour))
        if hour_diff > hour_dev:
            indicators.append({
                "type": "baseline_unusual_send_hour",
                "value": current_hour,
                "reason": f"Send hour {current_hour}:00 deviates from typical ~{round(mean_hour)}:00 (diff={round(hour_diff)}h)",
            })
    else:
        mean_hour = None

    # 3) Invoice amount z-score
    amount_zscore = None
    if invoice_amount is not None and len(amounts) >= min_obs:
        amt_mean = sum(amounts) / len(amounts)
        amt_var = sum((a - amt_mean) ** 2 for a in amounts) / len(amounts)
        amt_std = math.sqrt(amt_var) if amt_var > 0 else 0.0
        if amt_std > 0:
            amount_zscore = (invoice_amount - amt_mean) / amt_std
            if abs(amount_zscore) > amount_z:
                indicators.append({
                    "type": "baseline_amount_anomaly",
                    "value": round(invoice_amount, 2),
                    "reason": (
                        f"Invoice amount ${round(invoice_amount, 2)} deviates from "
                        f"baseline mean ${round(amt_mean, 2)} (z={round(amount_zscore, 1)})"
                    ),
                })

    # 4) Attachment count anomaly
    if att_counts:
        att_mean = sum(att_counts) / len(att_counts)
        att_var = sum((a - att_mean) ** 2 for a in att_counts) / len(att_counts)
        att_std = math.sqrt(att_var) if att_var > 0 else 0.0
        if att_std > 0 and attachment_count > 0:
            att_z = (attachment_count - att_mean) / att_std
            if att_z > freq_z:
                indicators.append({
                    "type": "baseline_attachment_count_anomaly",
                    "value": attachment_count,
                    "reason": f"Attachment count {attachment_count} exceeds baseline mean {round(att_mean, 1)} (z={round(att_z, 1)})",
                })

    return {
        "baseline_available": True,
        "observation_count": n,
        "indicators": indicators,
        "stats": {
            "msgs_per_week": round(msgs_per_week, 2) if msgs_per_week else None,
            "mean_send_hour": round(mean_hour, 1) if mean_hour is not None else None,
            "amount_mean": round(sum(amounts) / len(amounts), 2) if amounts else None,
            "amount_stddev": round(math.sqrt(sum((a - sum(amounts) / len(amounts)) ** 2 for a in amounts) / len(amounts)), 2) if amounts else None,
            "amount_zscore": round(amount_zscore, 2) if amount_zscore is not None else None,
        },
        "meta": {
            "sender_domain_hash": sdh,
            "window_days": window_days,
            "min_observations": min_obs,
        },
    }
