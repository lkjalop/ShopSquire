"""Synthetic market replay (agnostic CORE, DEMO) — deterministic signals → real M3 analysis.

Drives the existing market-intelligence path (market_signal → analyze → market_finding) with a
reproducible, COMPRESSED 7-day fixture so the operator's Market Intelligence view shows demand rising
while conversion drops and stock falls — and the findings change as days advance. The INGESTION,
ANALYSIS, and FINDING path is the real one; only the events are synthetic (label it SYNTHETIC REPLAY).

Tenant-ISOLATED: everything is written under tenant_id='replay-demo' and analyzed from there, so a
replay never touches a real tenant's signals or findings (the deck's "replay does not modify non-demo
tenants"). Deterministic anomaly_fn (no ~1.6s models) so a replay is reproducible. Never raises.
"""
from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import text

from src.app.services import market_analysis as ma
from src.app.services import market_signal as ms

REPLAY_TENANT = "replay-demo"
REPLAY_ITEM = "demo-sku"
_DATES = ["2026-06-20", "2026-06-21", "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26"]
_DEMAND = [10, 11, 10, 12, 11, 25, 60]      # demand index per day — spikes on days 6-7
_CONV = [8, 8, 7, 8, 8, 6, 2]               # conversions per day — drops on day 7
_RESULT_COUNT = [5, 5, 5, 5, 5, 0, 0]       # later days return no results → inventory mismatch
TOTAL_DAYS = len(_DATES)

# As the market heats up (day 6+) a rival undercuts us and objections cluster — so the operator view
# also shows competitor_undercut + objection_cluster + the forward demand_forecast, not just the
# backward anomalies. Ingested once (idempotent via dedup), tenant-scoped like everything else.
_HEAT_DAY = 6
_COMPETITOR = {"entity_ref": REPLAY_ITEM, "our_price_cents": 150000,
               "competitor_price_cents": 124900, "competitor": "rival-store.example"}  # ~17% under → critical
_OBJECTIONS = (("price", 6), ("delivery_time", 3))   # price cluster → critical, delivery → warn


def _det_anomaly(series: List[float], domain: str):
    """Deterministic: flag the last point anomalous when it deviates >50% from the rest's mean."""
    rest = series[:-1] or [0.0]
    base = sum(rest) / len(rest) if rest else 0.0
    last = series[-1] if series else 0.0
    is_anom = base > 0 and (last > base * 1.5 or last < base * 0.5)

    class _R:
        is_anomaly = is_anom
        confidence = 0.95
        severity = "critical" if (base > 0 and (last > base * 2 or last < base * 0.4)) else "warn"
        z_score = 3.1
    return [_R()]


def reset(db, *, tenant: str = REPLAY_TENANT) -> Dict[str, int]:
    """Clear all replay signals + findings for the demo tenant. Best-effort."""
    if db is None:
        return {}
    out = {}
    for tbl in ("market_signal", "market_finding"):
        try:
            ms.ensure_table(db) if tbl == "market_signal" else ma.ensure_finding_table(db)
            r = db.execute(text(f"DELETE FROM {tbl} WHERE tenant_id = :t"), {"t": tenant})
            out[tbl] = int(getattr(r, "rowcount", 0) or 0)
        except Exception:
            out[tbl] = 0
    try:
        db.commit()
    except Exception:
        return out
    return out


def load_days(db, *, up_to_day: int, tenant: str = REPLAY_TENANT) -> Dict[str, int]:
    """Ingest the synthetic signals for days 1..up_to_day (1-indexed, inclusive). Idempotent via dedup."""
    if db is None:
        return {"ingested": 0}
    n = 0
    upto = max(0, min(int(up_to_day), TOTAL_DAYS))
    for d in range(upto):
        date = _DATES[d]
        for i in range(_DEMAND[d]):
            sig = ms.normalize(signal_type="demand", source="search_events",
                               payload={"event_id": f"{date}-d{i}", "query": REPLAY_ITEM,
                                        "result_count": _RESULT_COUNT[d]},
                               occurred_at=f"{date}T10:00:00", dedup_fields=["event_id"], tenant_id=tenant)
            if ms.ingest(db, sig):
                n += 1
        for i in range(_CONV[d]):
            sig = ms.normalize(signal_type="conversion", source="conversion_event",
                               payload={"event_id": f"{date}-c{i}", "order_id": f"{date}-o{i}"},
                               occurred_at=f"{date}T11:00:00", dedup_fields=["event_id"], tenant_id=tenant)
            if ms.ingest(db, sig):
                n += 1
    if upto >= _HEAT_DAY:  # competitor + objection signals once the market heats up
        heat_date = _DATES[_HEAT_DAY - 1]
        csig = ms.normalize(signal_type="competitor", source="competitor_feed",
                            payload={"event_id": "cmp-1", **_COMPETITOR},
                            occurred_at=f"{heat_date}T09:00:00", dedup_fields=["event_id"], tenant_id=tenant)
        if ms.ingest(db, csig):
            n += 1
        k = 0
        for theme, cnt in _OBJECTIONS:
            for _ in range(cnt):
                osig = ms.normalize(signal_type="support_objection", source="support_inbox",
                                    payload={"event_id": f"obj-{k}", "theme": theme},
                                    occurred_at=f"{heat_date}T12:00:00", dedup_fields=["event_id"], tenant_id=tenant)
                if ms.ingest(db, osig):
                    n += 1
                k += 1
    try:
        db.commit()
    except Exception:
        return {"ingested": n}
    return {"ingested": n, "through_day": upto}


def _load_signals(db, tenant: str) -> List[Dict[str, Any]]:
    try:
        rows = db.execute(
            text("SELECT signal_type, source, payload_json, occurred_at FROM market_signal "
                 "WHERE tenant_id = :t ORDER BY occurred_at ASC"), {"t": tenant}).fetchall()
    except Exception:
        return []
    import json
    out = []
    for st, src, pj, occ in rows:
        try:
            payload = json.loads(pj) if pj else {}
        except Exception:
            payload = {}
        out.append({"signal_type": st, "source": src, "payload": payload, "occurred_at": occ})
    return out


def run(db, *, tenant: str = REPLAY_TENANT) -> Dict[str, Any]:
    """Analyze the loaded replay signals with the REAL detectors (deterministic anomaly_fn) and persist
    findings tenant-scoped (expiring ones no longer observed). Returns {findings, persisted}."""
    if db is None:
        return {"findings": 0, "persisted": 0}
    signals = _load_signals(db, tenant)
    findings = ma.analyze(signals, anomaly_fn=_det_anomaly)
    persisted = ma.persist_findings(db, findings, tenant_id=tenant, expire_unobserved=True)
    try:
        db.commit()
    except Exception:
        return {"findings": len(findings), "persisted": persisted}
    return {"findings": len(findings), "persisted": persisted}


def state(db, *, tenant: str = REPLAY_TENANT) -> Dict[str, Any]:
    """Counts for the operator view: signals, active findings, and a per-day demand/conversion series."""
    if db is None:
        return {"signals": 0, "active_findings": 0, "findings": []}
    try:
        sig_n = db.execute(text("SELECT COUNT(*) FROM market_signal WHERE tenant_id=:t"),
                           {"t": tenant}).scalar() or 0
    except Exception:
        sig_n = 0
    findings = ma.load_recent_findings(db, limit=20, tenant_id=tenant)
    return {
        "signals": int(sig_n),
        "active_findings": len(findings),
        "findings": [{"type": f.finding_type, "severity": f.severity, "summary": f.summary,
                      "entity_ref": f.entity_ref} for f in findings],
        "series": {"demand": _DEMAND, "conversion": _CONV, "dates": _DATES},
        "label": "SYNTHETIC REPLAY",
    }
