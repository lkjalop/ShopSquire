"""Market signal envelope + ingestion (agnostic CORE) — David Module 1 (Signal Ingestion).

Normalizes ANY internal event (clickstream, search, order, conversion, support objection, ...) into
ONE canonical envelope so the analysis engine reads a single shape. Carries the deck's per-pipeline
reliability controls — the deck's thesis is "bad input → bad autonomous behaviour", so reliability is
first-class, not an afterthought:

  schema validation  — signal_type + source + dict payload required (else dropped)
  timestamp normalize — occurred_at coerced to a string form
  trust scoring       — trust_score in [0,1]; ingest can quarantine below a floor
  dedup               — deterministic dedup_key → idempotent insert
  freshness           — is_fresh() rejects stale signals (best-effort, tolerant)

VERTICAL-BLIND: signal_type/source are opaque labels, payload is opaque JSON. Idempotent +
best-effort; never raises into the request path.

Table: market_signal(id, signal_type, source, dedup_key, trust_score, payload_json, occurred_at,
                      ingested_at)
"""
from __future__ import annotations

import hashlib
import json
import uuid
import weakref
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import inspect as _sa_inspect
from sqlalchemy import text

from src.app.services.schema_policy import runtime_ddl_allowed

SCHEMA_VERSION = 1  # bump when the envelope shape changes; stored per row so old rows stay readable
DEFAULT_TENANT = "default"  # single-tenant today; the column isolates a future multi-tenant deployment

_DDL = """
CREATE TABLE IF NOT EXISTS market_signal (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    schema_version INTEGER DEFAULT 1,
    signal_type TEXT,
    source TEXT,
    dedup_key TEXT,
    trust_score REAL,
    payload_json TEXT,
    occurred_at TEXT,
    ingested_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""

# Columns added AFTER the table first shipped — applied to pre-existing tables on upgrade.
_UPGRADE_COLS = (
    ("tenant_id", "TEXT DEFAULT 'default'"),
    ("schema_version", "INTEGER DEFAULT 1"),
)


@dataclass(frozen=True)
class MarketSignal:
    signal_type: str          # demand | conversion | support_objection | competitor | ...
    source: str               # consumer_signals | search_events | orders | conversion_event | ...
    payload: Dict[str, Any]
    occurred_at: str          # normalized string (may be "")
    trust_score: float        # 0..1
    dedup_key: str
    tenant_id: str = DEFAULT_TENANT
    schema_version: int = SCHEMA_VERSION


# Dedup is per-tenant (UNIQUE on tenant_id+dedup_key) so two tenants with identical payloads keep
# distinct rows; the content hash stays tenant-blind. Plus query indexes for time/type/source scans.
# NOTE: no DROP INDEX here — that ran on EVERY ingest, dropping+recreating the unique index per event
# (table lock + a window with no dedup protection). The one-time conversion of a legacy single-column
# ix_market_signal_dedup → the composite lives in the Alembic migration (20260626_market_autonomy),
# which runs once. CREATE ... IF NOT EXISTS here is a cheap catalog no-op once the index exists.
_INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_market_signal_dedup ON market_signal(tenant_id, dedup_key)",
    "CREATE INDEX IF NOT EXISTS ix_market_signal_type ON market_signal(signal_type)",
    "CREATE INDEX IF NOT EXISTS ix_market_signal_source ON market_signal(source)",
    "CREATE INDEX IF NOT EXISTS ix_market_signal_occurred ON market_signal(occurred_at)",
)


_COLS_INTROSPECTED = weakref.WeakSet()  # engines whose column-upgrade check has already run


def _ensure_columns(db, table: str, coldefs) -> None:
    """Add missing columns to a pre-existing table (portable upgrade). Introspects first so the normal
    path issues no failing DDL (a duplicate-column ALTER can poison a transaction on some backends).
    The reflection is memoized per-engine — fresh tables already have every column, and a real upgrade
    only needs to run once, so we don't pay get_columns() on every ingest/read."""
    try:
        bind = db.get_bind()
    except Exception:
        bind = None
    if bind is not None and bind in _COLS_INTROSPECTED:
        return  # already checked this engine — skip the reflection cost
    try:
        # introspect via the session's OWN connection — never the engine (a pooled checkout would be
        # returned + rolled back, discarding the session's uncommitted inserts).
        have = {c["name"] for c in _sa_inspect(db.connection()).get_columns(table)}
    except Exception:
        return  # table not present yet (CREATE above will include every column) → don't memoize, retry
    for name, decl in coldefs:
        if name not in have:
            db.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {decl}"))
    if bind is not None:
        _COLS_INTROSPECTED.add(bind)


def ensure_table(db) -> None:
    if not runtime_ddl_allowed():
        return
    db.execute(text(_DDL))
    _ensure_columns(db, "market_signal", _UPGRADE_COLS)  # before the composite index needs tenant_id
    for stmt in _INDEXES:
        db.execute(text(stmt))


def _norm_ts(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _dedup_key(source: str, signal_type: str, payload: Dict[str, Any],
               dedup_fields: Optional[Iterable[str]]) -> str:
    parts = [str(source), str(signal_type)]
    if dedup_fields:
        for f in dedup_fields:
            parts.append(f"{f}={payload.get(f)!r}")
    else:
        parts.append(json.dumps(payload, sort_keys=True, default=str))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


def normalize(
    *,
    signal_type: Any,
    source: Any,
    payload: Any,
    occurred_at: Any = None,
    trust_score: Any = 1.0,
    dedup_fields: Optional[Iterable[str]] = None,
    tenant_id: Any = DEFAULT_TENANT,
) -> Optional[MarketSignal]:
    """Validate + normalize a raw event into a MarketSignal. Returns None on schema-validation
    failure (missing type/source or non-dict payload). ``dedup_fields`` names the payload keys that
    identify uniqueness (else the whole payload is hashed). ``tenant_id`` scopes dedup + isolation."""
    st = str(signal_type or "").strip()
    src = str(source or "").strip()
    if not st or not src or not isinstance(payload, dict):
        return None
    try:
        trust = float(trust_score if trust_score is not None else 1.0)
    except Exception:
        trust = 1.0
    trust = max(0.0, min(1.0, trust))
    return MarketSignal(
        signal_type=st,
        source=src,
        payload=dict(payload),
        occurred_at=_norm_ts(occurred_at),
        trust_score=trust,
        dedup_key=_dedup_key(src, st, payload, dedup_fields),
        tenant_id=(str(tenant_id).strip() or DEFAULT_TENANT),
    )


def is_fresh(signal: Optional[MarketSignal], *, max_age_seconds: float, now_iso: Optional[str]) -> bool:
    """True when occurred_at is within max_age_seconds of now. Tolerant: if either timestamp is
    missing/unparseable, returns True (never wrongly drop a signal we can't date)."""
    if signal is None or not signal.occurred_at or not now_iso:
        return True
    try:
        from datetime import datetime

        def _p(s: str):
            s = str(s).strip().replace("Z", "").replace("T", " ")
            return datetime.fromisoformat(s)

        occ = _p(signal.occurred_at)
        now = _p(now_iso)
        return (now - occ).total_seconds() <= float(max_age_seconds)
    except Exception:
        return True


def ingest(
    db,
    signal: Optional[MarketSignal],
    *,
    min_trust: float = 0.0,
    max_age_seconds: Optional[float] = None,
    now_iso: Optional[str] = None,
) -> bool:
    """Idempotent insert (skips a duplicate dedup_key) gated by trust (quarantine below min_trust)
    and, when ``max_age_seconds`` is given, by freshness (drop stale signals). Returns True only when
    a new row is written. Never raises. A concurrent race is closed by the UNIQUE dedup index — the
    losing insert raises and is caught → False."""
    if db is None or signal is None:
        return False
    if signal.trust_score < float(min_trust):
        return False  # quarantine low-trust signal
    if max_age_seconds is not None and not is_fresh(signal, max_age_seconds=max_age_seconds, now_iso=now_iso):
        return False  # quarantine stale signal
    try:
        ensure_table(db)
        existing = db.execute(
            text("SELECT 1 FROM market_signal WHERE tenant_id = :t AND dedup_key = :k LIMIT 1"),
            {"t": signal.tenant_id, "k": signal.dedup_key},
        ).fetchone()
        if existing:
            return False
        db.execute(
            text(
                "INSERT INTO market_signal "
                "(id, tenant_id, schema_version, signal_type, source, dedup_key, trust_score, "
                "payload_json, occurred_at) VALUES (:id,:tn,:sv,:st,:src,:k,:tr,:pl,:occ)"
            ),
            {
                "id": str(uuid.uuid4()),
                "tn": signal.tenant_id,
                "sv": int(signal.schema_version),
                "st": signal.signal_type,
                "src": signal.source,
                "k": signal.dedup_key,
                "tr": signal.trust_score,
                "pl": json.dumps(signal.payload, default=str),
                "occ": signal.occurred_at or None,
            },
        )
        return True
    except Exception:
        return False
