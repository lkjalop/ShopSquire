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
# Lifecycle: a fresh batch run SUPERSEDES the prior active finding for the same (tenant, type, entity,
# window) — so re-running analysis updates rather than duplicates, and load returns only status='active'
# (or human-'corrected' rows kept as a learning record, never auto-overwritten).
SCHEMA_VERSION = 1
DEFAULT_TENANT = "default"

_FINDING_DDL = """
CREATE TABLE IF NOT EXISTS market_finding (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    schema_version INTEGER DEFAULT 1,
    finding_type TEXT,
    entity_ref TEXT,
    severity TEXT,
    confidence REAL,
    summary TEXT,
    evidence_json TEXT,
    window TEXT,
    dedup_key TEXT,
    status TEXT DEFAULT 'active',
    corrected_by_human INTEGER DEFAULT 0,
    correction_note TEXT,
    superseded_by TEXT,
    detected_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
# Columns added after the table first shipped — applied to pre-existing tables on upgrade.
_FINDING_UPGRADE_COLS = (
    ("tenant_id", "TEXT DEFAULT 'default'"),
    ("schema_version", "INTEGER DEFAULT 1"),
    ("dedup_key", "TEXT"),
    ("status", "TEXT DEFAULT 'active'"),
    ("corrected_by_human", "INTEGER DEFAULT 0"),
    ("correction_note", "TEXT"),
    ("superseded_by", "TEXT"),
)
_FINDING_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_market_finding_type ON market_finding(finding_type)",
    "CREATE INDEX IF NOT EXISTS ix_market_finding_detected ON market_finding(detected_at)",
    "CREATE INDEX IF NOT EXISTS ix_market_finding_dedup ON market_finding(tenant_id, dedup_key, status)",
)


def _finding_dedup_key(tenant_id: str, finding_type: str, entity_ref: Any, window: str) -> str:
    import hashlib
    raw = "|".join([str(tenant_id), str(finding_type), str(entity_ref or ""), str(window or "")])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


import weakref as _weakref

_FINDING_COLS_INTROSPECTED = _weakref.WeakSet()  # engines whose finding-column upgrade has run


def _ensure_finding_columns(db) -> None:
    """Add post-ship columns to a pre-existing market_finding (portable upgrade; no failing DDL).
    Reflection memoized per-engine so load_recent_findings() (hot path) doesn't pay get_columns()
    every call — fresh tables already have every column; a real upgrade runs once."""
    from sqlalchemy import inspect as _sa_inspect
    try:
        bind = db.get_bind()
    except Exception:
        bind = None
    if bind is not None and bind in _FINDING_COLS_INTROSPECTED:
        return
    try:
        # session's OWN connection, not the engine — a pooled checkout would roll back pending inserts.
        have = {c["name"] for c in _sa_inspect(db.connection()).get_columns("market_finding")}
    except Exception:
        return  # table not present yet → don't memoize, retry next call
    for name, decl in _FINDING_UPGRADE_COLS:
        if name not in have:
            db.execute(text(f"ALTER TABLE market_finding ADD COLUMN {name} {decl}"))
    if bind is not None:
        _FINDING_COLS_INTROSPECTED.add(bind)


def ensure_finding_table(db) -> None:
    db.execute(text(_FINDING_DDL))
    _ensure_finding_columns(db)
    for stmt in _FINDING_INDEXES:
        db.execute(text(stmt))


def persist_findings(db, findings: List[MarketFinding], *, tenant_id: str = DEFAULT_TENANT) -> int:
    """Write a batch run's findings, SUPERSEDING the prior active finding per (tenant,type,entity,window)
    so re-runs update rather than accumulate. Human-corrected rows are left untouched (the human wins).
    Returns the count written. Best-effort; never raises."""
    if db is None or not findings:
        return 0
    try:
        import json
        import uuid
        ensure_finding_table(db)
        tid = str(tenant_id).strip() or DEFAULT_TENANT
        n = 0
        for f in findings:
            dk = _finding_dedup_key(tid, f.finding_type, f.entity_ref, f.window)
            new_id = str(uuid.uuid4())
            # supersede the prior active machine finding for this key (never a human-corrected one)
            db.execute(
                text("UPDATE market_finding SET status='superseded', superseded_by=:nid "
                     "WHERE tenant_id=:t AND dedup_key=:dk AND status='active' "
                     "AND COALESCE(corrected_by_human,0)=0"),
                {"nid": new_id, "t": tid, "dk": dk},
            )
            db.execute(
                text("INSERT INTO market_finding (id, tenant_id, schema_version, finding_type, entity_ref, "
                     "severity, confidence, summary, evidence_json, window, dedup_key, status) "
                     "VALUES (:i,:tn,:sv,:t,:e,:s,:c,:m,:j,:w,:dk,'active')"),
                {"i": new_id, "tn": tid, "sv": int(SCHEMA_VERSION), "t": f.finding_type, "e": f.entity_ref,
                 "s": f.severity, "c": float(f.confidence), "m": f.summary,
                 "j": json.dumps(f.evidence, default=str), "w": f.window, "dk": dk},
            )
            n += 1
        return n
    except Exception:
        return 0


def correct_finding(db, finding_id: str, *, note: str = "", tenant_id: str = DEFAULT_TENANT) -> bool:
    """Human-in-the-loop correction: flag a finding as human-corrected so future batch runs never
    silently overwrite it. The correction becomes a learning signal (projected as a weighted hippograph
    edge by the human-correction learner). Returns True when a row was updated. Never raises."""
    if db is None or not finding_id:
        return False
    try:
        ensure_finding_table(db)
        res = db.execute(
            text("UPDATE market_finding SET corrected_by_human=1, status='corrected', correction_note=:n "
                 "WHERE id=:i AND tenant_id=:t"),
            {"n": str(note or ""), "i": str(finding_id), "t": str(tenant_id).strip() or DEFAULT_TENANT},
        )
        return bool(getattr(res, "rowcount", 0) or 0)
    except Exception:
        return False


def load_recent_findings(db, *, limit: int = 50, tenant_id: str = DEFAULT_TENANT) -> List[MarketFinding]:
    """Read recent ACTIVE persisted findings (fast — the hot-path read), tenant-scoped. Superseded and
    human-corrected rows are excluded from the live read. Best-effort."""
    if db is None:
        return []
    try:
        ensure_finding_table(db)
        rows = db.execute(
            text("SELECT finding_type, entity_ref, severity, confidence, summary, evidence_json, window "
                 "FROM market_finding "
                 "WHERE COALESCE(status,'active')='active' AND COALESCE(tenant_id,'default')=:t "
                 "ORDER BY detected_at DESC LIMIT :lim"),
            {"lim": int(limit), "t": str(tenant_id).strip() or DEFAULT_TENANT},
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
