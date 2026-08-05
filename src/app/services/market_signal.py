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
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import inspect as _sa_inspect
from sqlalchemy import text

SCHEMA_VERSION = 1  # bump when the envelope shape changes; stored per row so old rows stay readable
DEFAULT_TENANT = "default"  # single-tenant today; the column isolates a future multi-tenant deployment

# Columns added AFTER the table first shipped — applied to pre-existing tables on upgrade.
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


def ensure_table(db) -> None:
    """Assert Alembic-owned schema without mutating it at request time."""
    inspector = _sa_inspect(db.connection())
    if not inspector.has_table("market_signal"):
        raise RuntimeError("market_signal schema missing; run Alembic migrations")
    required = {"id", "tenant_id", "schema_version", "dedup_key", "payload_json"}
    present = {column["name"] for column in inspector.get_columns("market_signal")}
    missing = sorted(required - present)
    if missing:
        raise RuntimeError(
            "market_signal schema incompatible; run Alembic migrations: " + ",".join(missing)
        )


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
