"""Source adapters: existing events → market_signal (agnostic CORE) — Module 1 producers.

Turns the market_signal envelope into a live stream. Each pure mapper converts one source row into a
normalized MarketSignal; backfill_from_db reads recent rows from the source tables and ingests them
idempotently (the dedup_key makes re-runs safe). Read-mostly + best-effort; never raises. Trust is
per-source — a confirmed order/conversion outranks a raw search event.

WIRING (both idempotent via dedup):
  • batch (default): a Celery task (tasks/market_signal_tasks) calls backfill_from_db on a cadence,
    decoupled from the request path.
  • inline (optional): call a mapper + market_signal.ingest at a write site (fire-and-forget).

Sources: orders, conversion_event (the reward), search_events (demand). consumer_signals is NOT a
table here (it routes to event_log), so search_events is the behavioral/demand source.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from sqlalchemy import text

from src.app.services.market_signal import MarketSignal, ensure_table, ingest, normalize


def from_order(row: Dict[str, Any]) -> Optional[MarketSignal]:
    oid = str((row.get("order_id") or row.get("id")) or "").strip()
    if not oid:
        return None
    return normalize(
        signal_type="order", source="orders",
        payload={"order_id": oid, "total_cents": row.get("total_cents"), "status": row.get("status")},
        occurred_at=row.get("created_at"), trust_score=1.0, dedup_fields=["order_id"],
    )


def from_conversion(row: Dict[str, Any]) -> Optional[MarketSignal]:
    oid = str(row.get("order_id") or "").strip()
    if not oid:
        return None
    return normalize(
        signal_type="conversion", source="conversion_event",
        payload={"order_id": oid, "decision_id": row.get("decision_id"), "value_cents": row.get("value_cents")},
        occurred_at=row.get("converted_at"), trust_score=1.0, dedup_fields=["order_id"],
    )


def from_return(row: Dict[str, Any]) -> Optional[MarketSignal]:
    oid = str((row.get("order_id") or row.get("id")) or "").strip()
    if not oid:
        return None
    return normalize(
        signal_type="return", source="orders",
        payload={"order_id": oid, "status": row.get("status")},
        occurred_at=row.get("updated_at") or row.get("created_at"), trust_score=1.0, dedup_fields=["order_id"],
    )


def from_search(row: Dict[str, Any]) -> Optional[MarketSignal]:
    eid = str(row.get("id") or "").strip()
    if not eid:
        return None
    return normalize(
        signal_type="demand", source="search_events",
        payload={"event_id": eid, "query": row.get("query"), "result_count": row.get("result_count")},
        occurred_at=row.get("event_time"), trust_score=0.8, dedup_fields=["event_id"],
    )


# ── INLINE producers (no backfill source table yet) — call at the write site / a future feed adapter.
# Kept out of _SOURCES because there is no canonical competitor-price / objection-capture table to scan;
# the detectors (market_analysis.detect_competitor_undercut / detect_objection_cluster) consume these
# the moment a producer ingests them. Trust is below behavioural sources — an external/derived claim.
def from_competitor(row: Dict[str, Any]) -> Optional[MarketSignal]:
    """A competitor price observation → competitor signal. row: {obs_id, entity_ref|sku, our_price_cents,
    competitor_price_cents, competitor?, observed_at?}."""
    oid = str((row.get("obs_id") or row.get("id")) or "").strip()
    ent = str((row.get("entity_ref") or row.get("sku")) or "").strip()
    if not oid or not ent:
        return None
    return normalize(
        signal_type="competitor", source="competitor_feed",
        payload={"obs_id": oid, "entity_ref": ent, "our_price_cents": row.get("our_price_cents"),
                 "competitor_price_cents": row.get("competitor_price_cents"),
                 "competitor": row.get("competitor")},
        occurred_at=row.get("observed_at"), trust_score=0.6, dedup_fields=["obs_id"],
    )


def from_support_objection(row: Dict[str, Any]) -> Optional[MarketSignal]:
    """A support objection (chat/ticket/review) → support_objection signal. row: {obs_id, theme,
    entity_ref?, raised_at?}. ``theme`` is an opaque cluster label (price / delivery_time / ...)."""
    oid = str((row.get("obs_id") or row.get("id")) or "").strip()
    theme = str(row.get("theme") or row.get("reason") or "").strip()
    if not oid or not theme:
        return None
    return normalize(
        signal_type="support_objection", source="support_inbox",
        payload={"obs_id": oid, "theme": theme, "entity_ref": row.get("entity_ref")},
        occurred_at=row.get("raised_at"), trust_score=0.7, dedup_fields=["obs_id"],
    )


# name -> (sql, row->dict mapper, dict->MarketSignal mapper)
_SOURCES = {
    "orders": (
        "SELECT id, total_cents, status, created_at FROM orders ORDER BY created_at DESC LIMIT :lim",
        lambda r: {"id": r[0], "total_cents": r[1], "status": r[2], "created_at": r[3]},
        from_order,
    ),
    "conversion_event": (
        "SELECT order_id, decision_id, value_cents, converted_at FROM conversion_event "
        "ORDER BY created_at DESC LIMIT :lim",
        lambda r: {"order_id": r[0], "decision_id": r[1], "value_cents": r[2], "converted_at": r[3]},
        from_conversion,
    ),
    "search_events": (
        "SELECT id, query, result_count, event_time FROM search_events ORDER BY event_time DESC LIMIT :lim",
        lambda r: {"id": r[0], "query": r[1], "result_count": r[2], "event_time": r[3]},
        from_search,
    ),
    "returns": (
        "SELECT id, status, updated_at, created_at FROM orders "
        "WHERE status IN ('refunded','chargebacked') ORDER BY updated_at DESC LIMIT :lim",
        lambda r: {"id": r[0], "status": r[1], "updated_at": r[2], "created_at": r[3]},
        from_return,
    ),
    # competitor: a REAL source — joins the rival observation to OUR canonical price_book retail, so the
    # detect_competitor_undercut detector fires on live data. No-op when either table is absent.
    "competitor": (
        "SELECT co.id, co.sku, pb.list_cents, co.competitor_price_cents, co.competitor, co.observed_at "
        "FROM competitor_observation co LEFT JOIN price_book_entry pb "
        "ON pb.sku = co.sku AND COALESCE(pb.tenant_id,'default') = COALESCE(co.tenant_id,'default') "
        "AND pb.channel = 'default' AND pb.currency = 'AUD' "
        "ORDER BY co.observed_at DESC LIMIT :lim",
        lambda r: {"obs_id": r[0], "entity_ref": r[1], "our_price_cents": r[2],
                   "competitor_price_cents": r[3], "competitor": r[4], "observed_at": r[5]},
        from_competitor,
    ),
}


def _backfill_one(db, sql: str, row_map, sig_map, *, limit: int, min_trust: float,
                  max_age_seconds: Optional[float], now_iso: Optional[str]) -> int:
    n = 0
    try:
        rows = db.execute(text(sql), {"lim": int(limit)}).fetchall()
        for r in rows:
            sig = sig_map(row_map(r))
            if sig and ingest(db, sig, min_trust=min_trust,
                              max_age_seconds=max_age_seconds, now_iso=now_iso):
                n += 1
        return n
    except Exception:
        return n  # source table absent / query error → partial, never raise


def _safe_commit(db) -> None:
    try:
        db.commit()
    except Exception:
        return


def backfill_from_db(
    db,
    *,
    sources: Optional[Iterable[str]] = None,
    limit: int = 1000,
    min_trust: float = 0.0,
    max_age_seconds: Optional[float] = None,
    now_iso: Optional[str] = None,
    commit: bool = True,
) -> Dict[str, int]:
    """Ingest recent rows from each source into market_signal (idempotent). Trust- and (when
    ``max_age_seconds`` is set) freshness-gated at the write — bad/stale input is quarantined before it
    can drive autonomous behaviour. Returns {source: count}."""
    if db is None:
        return {}
    ensure_table(db)
    counts: Dict[str, int] = {}
    want = set(sources) if sources else None
    for name, (sql, row_map, sig_map) in _SOURCES.items():
        if want is not None and name not in want:
            continue
        counts[name] = _backfill_one(db, sql, row_map, sig_map, limit=limit, min_trust=min_trust,
                                     max_age_seconds=max_age_seconds, now_iso=now_iso)
    if commit:
        _safe_commit(db)
    return counts
