"""Market Analysis Engine (M3, agnostic CORE) — market_signal → typed findings.

Consumes recent market_signal rows (the Module-1 stream) and produces business-relevant
MarketFindings via DETERMINISTIC detectors — no LLM in finding generation (the deck: roll out
explainable detection first, before complex techniques). Reuses the existing AnomalyDetector for the
statistical leg (injectable for tests). Findings are PROPOSALS for the hippograph + dashboards; they
never act (any action re-enters policy → escalation → audit).

Detectors (v1, explainable):
  • demand_shift             — daily search/demand volume spike or slowdown vs baseline
  • conversion_anomaly       — daily conversion-rate (conversions/demand) DROP anomaly
  • inventory_demand_mismatch — recurring demand with zero result_count (catalog not meeting demand;
                                a proxy until a real inventory adapter sharpens it)

Vertical-blind: finding_type/entity_ref/evidence are opaque to product vocabulary. Never raises.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import text

FINDING_DEMAND_SHIFT = "demand_shift"
FINDING_CONVERSION_ANOMALY = "conversion_anomaly"
FINDING_INVENTORY_MISMATCH = "inventory_demand_mismatch"

_MIN_POINTS = 4  # need enough history before an anomaly finding is actionable


@dataclass(frozen=True)
class MarketFinding:
    finding_type: str
    entity_ref: Optional[str]   # sku / query token / category / None
    severity: str               # info | warn | critical
    confidence: float           # 0..1
    summary: str                # plain-English, evidence-grounded (no LLM)
    evidence: Dict[str, Any] = field(default_factory=dict)
    window: str = "recent"


def _day(occurred_at: Any) -> str:
    return str(occurred_at or "")[:10]  # YYYY-MM-DD bucket


def _default_anomaly_fn(series: List[float], domain: str):
    from src.app.services.anomaly_detector import AnomalyDetector
    return AnomalyDetector().score_series(series=series, domain=domain)


def _top_anomaly(results: Any):
    """The highest-confidence anomalous result, robust to score_series' return alignment."""
    anomalous = [r for r in (results or []) if getattr(r, "is_anomaly", False)]
    if not anomalous:
        return None
    return max(anomalous, key=lambda r: float(getattr(r, "confidence", 0.0) or 0.0))


def detect_demand_shift(signals, *, anomaly_fn: Optional[Callable] = None, min_points: int = _MIN_POINTS) -> List[MarketFinding]:
    fn = anomaly_fn or _default_anomaly_fn
    by_day: Dict[str, int] = {}
    for s in signals or []:
        if (s or {}).get("signal_type") != "demand":
            continue
        d = _day(s.get("occurred_at"))
        if d:
            by_day[d] = by_day.get(d, 0) + 1
    days = sorted(by_day)
    if len(days) < min_points:
        return []
    series = [float(by_day[d]) for d in days]
    top = _top_anomaly(fn(series, "market_demand"))
    if not top:
        return []
    latest = series[-1]
    base = sum(series[:-1]) / max(1, len(series) - 1)
    direction = "spike" if latest >= base else "slowdown"
    return [MarketFinding(
        FINDING_DEMAND_SHIFT, None, str(getattr(top, "severity", "warn")), float(getattr(top, "confidence", 0.5)),
        f"Search demand {direction}: {int(latest)} vs ~{base:.0f} baseline.",
        {"latest": latest, "baseline": round(base, 2), "z_score": getattr(top, "z_score", None), "days": days[-min_points:]},
        "daily",
    )]


def detect_conversion_anomaly(signals, *, anomaly_fn: Optional[Callable] = None, min_points: int = _MIN_POINTS) -> List[MarketFinding]:
    fn = anomaly_fn or _default_anomaly_fn
    conv: Dict[str, int] = {}
    demand: Dict[str, int] = {}
    for s in signals or []:
        st = (s or {}).get("signal_type")
        d = _day(s.get("occurred_at"))
        if not d:
            continue
        if st == "conversion":
            conv[d] = conv.get(d, 0) + 1
        elif st == "demand":
            demand[d] = demand.get(d, 0) + 1
    days = sorted(set(conv) | set(demand))
    if len(days) < min_points:
        return []
    series = [conv.get(d, 0) / max(1.0, float(demand.get(d, 0) or 1)) for d in days]
    top = _top_anomaly(fn(series, "market_conversion"))
    if not top:
        return []
    latest = series[-1]
    base = sum(series[:-1]) / max(1, len(series) - 1)
    if latest >= base:
        return []  # only a DROP is the actionable signal (a rise is good news)
    return [MarketFinding(
        FINDING_CONVERSION_ANOMALY, None, str(getattr(top, "severity", "warn")), float(getattr(top, "confidence", 0.5)),
        f"Conversion-rate drop: {latest:.2f} vs ~{base:.2f} baseline.",
        {"latest": round(latest, 4), "baseline": round(base, 4), "z_score": getattr(top, "z_score", None)},
        "daily",
    )]


def detect_inventory_demand_mismatch(signals, *, min_unmet: int = 3) -> List[MarketFinding]:
    unmet: Dict[str, int] = {}
    for s in signals or []:
        if (s or {}).get("signal_type") != "demand":
            continue
        p = s.get("payload") or {}
        rc = p.get("result_count")
        q = str(p.get("query") or "").strip().lower()
        if q and rc is not None and int(rc) <= 0:
            unmet[q] = unmet.get(q, 0) + 1
    out: List[MarketFinding] = []
    for q, n in sorted(unmet.items(), key=lambda x: (-x[1], x[0])):
        if n < min_unmet:
            continue
        severity = "warn" if n < min_unmet * 2 else "critical"
        out.append(MarketFinding(
            FINDING_INVENTORY_MISMATCH, q, severity, min(1.0, n / float(min_unmet * 3)),
            f"Unmet demand: '{q}' searched {n}x with no results (catalog gap).",
            {"query": q, "zero_result_searches": n}, "recent",
        ))
    return out


def _safe(fn: Callable, *args, **kw) -> List[MarketFinding]:
    try:
        return fn(*args, **kw)
    except Exception:
        return []  # one detector failing must not sink the rest


def analyze(signals, *, anomaly_fn: Optional[Callable] = None) -> List[MarketFinding]:
    """Run every detector over a market_signal window. Never raises."""
    out: List[MarketFinding] = []
    out += _safe(detect_demand_shift, signals, anomaly_fn=anomaly_fn)
    out += _safe(detect_conversion_anomaly, signals, anomaly_fn=anomaly_fn)
    out += _safe(detect_inventory_demand_mismatch, signals)
    return out


def load_recent_signals(db, *, limit: int = 2000) -> List[Dict[str, Any]]:
    """Read recent market_signal rows into the dict shape the detectors expect. Best-effort."""
    if db is None:
        return []
    try:
        rows = db.execute(
            text("SELECT signal_type, source, payload_json, occurred_at FROM market_signal "
                 "ORDER BY occurred_at DESC LIMIT :lim"),
            {"lim": int(limit)},
        ).fetchall()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        try:
            payload = json.loads(r[2]) if r[2] else {}
        except Exception:
            payload = {}
        out.append({"signal_type": r[0], "source": r[1],
                    "payload": payload if isinstance(payload, dict) else {}, "occurred_at": r[3]})
    return out


def run_analysis(db, *, limit: int = 2000, anomaly_fn: Optional[Callable] = None) -> List[MarketFinding]:
    """Load recent market_signal rows + analyze them. The DB entry point for the BATCH task.

    NOTE: analysis runs the real statistical models (~1.6s) — batch-only, never the request path.
    The hot path reads PERSISTED findings via load_recent_findings()."""
    return analyze(load_recent_signals(db, limit=limit), anomaly_fn=anomaly_fn)


# ── findings persistence (batch writes, hot path reads) ──────────────────────
_FINDING_DDL = """
CREATE TABLE IF NOT EXISTS market_finding (
    id TEXT PRIMARY KEY,
    finding_type TEXT,
    entity_ref TEXT,
    severity TEXT,
    confidence REAL,
    summary TEXT,
    evidence_json TEXT,
    window TEXT,
    detected_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
_FINDING_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_market_finding_type ON market_finding(finding_type)",
    "CREATE INDEX IF NOT EXISTS ix_market_finding_detected ON market_finding(detected_at)",
)


def ensure_finding_table(db) -> None:
    db.execute(text(_FINDING_DDL))
    for stmt in _FINDING_INDEXES:
        db.execute(text(stmt))


def persist_findings(db, findings: List[MarketFinding]) -> int:
    """Write a batch run's findings. Returns the count written. Best-effort; never raises."""
    if db is None or not findings:
        return 0
    try:
        import json
        import uuid
        ensure_finding_table(db)
        n = 0
        for f in findings:
            db.execute(
                text("INSERT INTO market_finding (id, finding_type, entity_ref, severity, confidence, "
                     "summary, evidence_json, window) VALUES (:i,:t,:e,:s,:c,:m,:j,:w)"),
                {"i": str(uuid.uuid4()), "t": f.finding_type, "e": f.entity_ref, "s": f.severity,
                 "c": float(f.confidence), "m": f.summary, "j": json.dumps(f.evidence, default=str), "w": f.window},
            )
            n += 1
        return n
    except Exception:
        return 0


def load_recent_findings(db, *, limit: int = 50) -> List[MarketFinding]:
    """Read recent PERSISTED findings (fast — the hot-path read). Best-effort."""
    if db is None:
        return []
    try:
        rows = db.execute(
            text("SELECT finding_type, entity_ref, severity, confidence, summary, evidence_json, window "
                 "FROM market_finding ORDER BY detected_at DESC LIMIT :lim"),
            {"lim": int(limit)},
        ).fetchall()
    except Exception:
        return []
    import json
    out: List[MarketFinding] = []
    for r in rows:
        try:
            ev = json.loads(r[5]) if r[5] else {}
        except Exception:
            ev = {}
        out.append(MarketFinding(r[0], r[1], r[2], float(r[3] or 0.0), r[4] or "",
                                 ev if isinstance(ev, dict) else {}, r[6] or "recent"))
    return out
