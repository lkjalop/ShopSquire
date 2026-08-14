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

from collections import Counter
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Dict, Iterable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import inspect, text

from src.app.services.market_signal import (
    MarketSignal, ensure_table, ingest_with_receipt, normalize,
)


class SourceBackfillReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["market-source-backfill-v1"] = "market-source-backfill-v1"
    source: str
    status: Literal["completed", "source_unavailable", "query_failed"]
    rows_read: int = 0
    accepted: int = 0
    outcomes: dict[str, int] = Field(default_factory=dict)
    error_code: str | None = None
    latency_ms: float = 0.0
    watermark_before: str | None = None
    watermark_after: str | None = None
    authority: Literal["ingestion_receipt_only"] = "ingestion_receipt_only"


def from_order(row: Dict[str, Any]) -> Optional[MarketSignal]:
    oid = str((row.get("order_id") or row.get("id")) or "").strip()
    if not oid:
        return None
    return normalize(
        signal_type="order", source="orders",
        payload={"order_id": oid, "total_cents": row.get("total_cents"), "status": row.get("status")},
        occurred_at=row.get("created_at"), trust_score=1.0, dedup_fields=["order_id"],
        tenant_id=row.get("tenant_id"),
    )


def from_conversion(row: Dict[str, Any]) -> Optional[MarketSignal]:
    oid = str(row.get("order_id") or "").strip()
    if not oid:
        return None
    return normalize(
        signal_type="conversion", source="conversion_event",
        payload={"order_id": oid, "decision_id": row.get("decision_id"), "value_cents": row.get("value_cents")},
        occurred_at=row.get("converted_at"), trust_score=1.0, dedup_fields=["order_id"],
        tenant_id=row.get("tenant_id"),
    )


def from_return(row: Dict[str, Any]) -> Optional[MarketSignal]:
    oid = str((row.get("order_id") or row.get("id")) or "").strip()
    if not oid:
        return None
    return normalize(
        signal_type="return", source="orders",
        payload={"order_id": oid, "status": row.get("status")},
        occurred_at=row.get("updated_at") or row.get("created_at"), trust_score=1.0,
        dedup_fields=["order_id"], tenant_id=row.get("tenant_id"),
    )


def from_search(row: Dict[str, Any]) -> Optional[MarketSignal]:
    eid = str(row.get("id") or "").strip()
    if not eid:
        return None
    return normalize(
        signal_type="demand", source="search_events",
        # carry the (hashed) identity so the unmet-demand detector can gate on DISTINCT users, not raw count —
        # a single actor scripting a zero-result query must not manufacture a customer-visible finding.
        payload={"event_id": eid, "query": row.get("query"), "result_count": row.get("result_count"),
                 "uid_hash": row.get("uid_hash"), "session": row.get("session_id")},
        occurred_at=row.get("event_time"), trust_score=0.8, dedup_fields=["event_id"],
        tenant_id=row.get("tenant_id"),
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
        tenant_id=row.get("tenant_id"),
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
        tenant_id=row.get("tenant_id"),
    )


def from_funnel(row: Dict[str, Any]) -> Optional[MarketSignal]:
    """A purchase-funnel observation → funnel signal. row: {obs_id, stage, entered, abandoned,
    observed_at?}. ``stage`` is an opaque label (cart / shipping / payment / ...)."""
    oid = str((row.get("obs_id") or row.get("id")) or "").strip()
    stage = str(row.get("stage") or "").strip()
    if not oid or not stage:
        return None
    return normalize(
        signal_type="funnel", source="funnel_events",
        payload={"obs_id": oid, "stage": stage, "entered": row.get("entered"),
                 "abandoned": row.get("abandoned")},
        occurred_at=row.get("observed_at"), trust_score=0.7, dedup_fields=["obs_id"],
        tenant_id=row.get("tenant_id"),
    )


# name -> (sql, row->dict mapper, dict->MarketSignal mapper)
_SOURCES = {
    "orders": (
        "SELECT id, total_cents, status, created_at, tenant_id FROM orders "
        "WHERE COALESCE(tenant_id,'default')=:tenant "
        "AND (:watermark IS NULL OR created_at > :watermark) ORDER BY created_at ASC LIMIT :lim",
        lambda r: {"id": r[0], "total_cents": r[1], "status": r[2], "created_at": r[3],
                   "tenant_id": r[4]},
        from_order,
    ),
    "conversion_event": (
        "SELECT order_id, decision_id, value_cents, converted_at, tenant_id FROM conversion_event "
        "WHERE COALESCE(tenant_id,'default')=:tenant "
        "AND (:watermark IS NULL OR converted_at > :watermark) ORDER BY converted_at ASC LIMIT :lim",
        lambda r: {"order_id": r[0], "decision_id": r[1], "value_cents": r[2],
                   "converted_at": r[3], "tenant_id": r[4]},
        from_conversion,
    ),
    "search_events": (
        "SELECT id, query, result_count, event_time, uid_hash, session_id, tenant_id FROM search_events "
        "WHERE COALESCE(tenant_id,'default')=:tenant "
        "AND (:watermark IS NULL OR event_time > :watermark) ORDER BY event_time ASC LIMIT :lim",
        lambda r: {"id": r[0], "query": r[1], "result_count": r[2], "event_time": r[3],
                   "uid_hash": r[4], "session_id": r[5], "tenant_id": r[6]},
        from_search,
    ),
    "returns": (
        "SELECT id, status, updated_at, created_at, tenant_id FROM orders "
        "WHERE COALESCE(tenant_id,'default')=:tenant AND status IN ('refunded','chargebacked') "
        "AND (:watermark IS NULL OR updated_at > :watermark) ORDER BY updated_at ASC LIMIT :lim",
        lambda r: {"id": r[0], "status": r[1], "updated_at": r[2], "created_at": r[3],
                   "tenant_id": r[4]},
        from_return,
    ),
    # competitor: a REAL source — joins the rival observation to OUR canonical price_book retail, so the
    # detect_competitor_undercut detector fires on live data. No-op when either table is absent.
    "competitor": (
        "SELECT co.id, co.sku, pb.list_cents, co.competitor_price_cents, co.competitor, "
        "co.observed_at, co.tenant_id "
        "FROM competitor_observation co LEFT JOIN price_book_entry pb "
        "ON pb.sku = co.sku AND COALESCE(pb.tenant_id,'default') = COALESCE(co.tenant_id,'default') "
        "AND pb.channel = 'default' AND pb.currency = 'AUD' "
        "WHERE COALESCE(co.tenant_id,'default')=:tenant "
        "AND (:watermark IS NULL OR co.observed_at > :watermark) "
        "ORDER BY co.observed_at ASC LIMIT :lim",
        lambda r: {"obs_id": r[0], "entity_ref": r[1], "our_price_cents": r[2],
                   "competitor_price_cents": r[3], "competitor": r[4], "observed_at": r[5],
                   "tenant_id": r[6]},
        from_competitor,
    ),
    # support objections: a REAL source — recurring buyer objections on a theme feed
    # detect_objection_cluster. No-op when the table is absent.
    "support_objection": (
        "SELECT id, theme, entity_ref, raised_at, tenant_id FROM support_objection "
        "WHERE COALESCE(tenant_id,'default')=:tenant "
        "AND (:watermark IS NULL OR raised_at > :watermark) ORDER BY raised_at ASC LIMIT :lim",
        lambda r: {"obs_id": r[0], "theme": r[1], "entity_ref": r[2], "raised_at": r[3],
                   "tenant_id": r[4]},
        from_support_objection,
    ),
    # funnel: a REAL source — purchase-funnel stage drop-off feeds detect_funnel_dropoff. No-op when absent.
    "funnel": (
        "SELECT id, stage, entered, abandoned, observed_at, tenant_id FROM cart_funnel_event "
        "WHERE COALESCE(tenant_id,'default')=:tenant "
        "AND (:watermark IS NULL OR observed_at > :watermark) ORDER BY observed_at ASC LIMIT :lim",
        lambda r: {"obs_id": r[0], "stage": r[1], "entered": r[2], "abandoned": r[3],
                   "observed_at": r[4], "tenant_id": r[5]},
        from_funnel,
    ),
}


def _source_table(sql: str) -> str | None:
    tokens = str(sql).replace("\n", " ").split()
    try:
        return tokens[tokens.index("FROM") + 1]
    except (ValueError, IndexError):
        return None


def _backfill_one(db, source: str, sql: str, row_map, sig_map, *, limit: int, min_trust: float,
                  max_age_seconds: Optional[float], now_iso: Optional[str],
                  tenant_id: str) -> SourceBackfillReceipt:
    started = perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()
    from src.app.services.market_ingestion_observability import load_watermark
    watermark_before = load_watermark(db, tenant_id=tenant_id, source=source)
    table_name = _source_table(sql)
    if table_name and not inspect(db.connection()).has_table(table_name):
        receipt = SourceBackfillReceipt(
            source=source, status="source_unavailable", error_code="table_missing",
            latency_ms=round((perf_counter() - started) * 1000, 3),
            watermark_before=watermark_before,
        )
        _persist_source_receipt(db, tenant_id, receipt, started_at)
        return receipt
    outcomes: Counter[str] = Counter()
    watermark: str | None = None
    try:
        with db.begin_nested():
            rows = db.execute(text(sql), {
                "lim": int(limit), "tenant": tenant_id, "watermark": watermark_before,
            }).fetchall()
            for r in rows:
                sig = sig_map(row_map(r))
                receipt = ingest_with_receipt(
                    db, sig, min_trust=min_trust,
                    max_age_seconds=max_age_seconds, now_iso=now_iso,
                )
                outcomes[receipt.status] += 1
                if sig and sig.occurred_at and (watermark is None or sig.occurred_at > watermark):
                    watermark = sig.occurred_at
                if receipt.status not in {"accepted", "duplicate"}:
                    from src.app.services.market_ingestion_observability import record_dead_letter
                    record_dead_letter(
                        db, tenant_id=tenant_id, source=source, signal=sig,
                        reason_code=receipt.status,
                        source_schema_version=int(getattr(sig, "schema_version", 1) or 1),
                    )
        result = SourceBackfillReceipt(
            source=source, status="completed", rows_read=len(rows),
            accepted=outcomes["accepted"], outcomes=dict(sorted(outcomes.items())),
            latency_ms=round((perf_counter() - started) * 1000, 3),
            watermark_before=watermark_before,
            watermark_after=watermark,
        )
        _persist_source_receipt(db, tenant_id, result, started_at)
        return result
    except Exception as exc:
        result = SourceBackfillReceipt(
            source=source, status="query_failed", error_code=type(exc).__name__,
            outcomes=dict(sorted(outcomes.items())),
            latency_ms=round((perf_counter() - started) * 1000, 3),
            watermark_before=watermark_before,
            watermark_after=watermark,
        )
        _persist_source_receipt(db, tenant_id, result, started_at)
        return result


def _persist_source_receipt(db, tenant_id: str, receipt: SourceBackfillReceipt,
                            started_at: str) -> None:
    try:
        from src.app.services.market_ingestion_observability import persist_run
        persist_run(
            db, tenant_id=tenant_id, receipt=receipt, started_at=started_at,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception:
        # Observability must not break canonical ingestion. Its own absence is
        # exposed by the health endpoint as not_configured.
        return


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
    tenant_id: Optional[str] = None,
    commit: bool = True,
) -> Dict[str, int]:
    """Ingest recent rows from each source into market_signal (idempotent). Trust- and (when
    ``max_age_seconds`` is set) freshness-gated at the write — bad/stale input is quarantined before it
    can drive autonomous behaviour. Returns {source: count}."""
    receipts = backfill_from_db_with_receipts(
        db, sources=sources, limit=limit, min_trust=min_trust,
        max_age_seconds=max_age_seconds, now_iso=now_iso, tenant_id=tenant_id,
        commit=commit,
    )
    return {receipt.source: receipt.accepted for receipt in receipts}


def backfill_from_db_with_receipts(
    db,
    *,
    sources: Optional[Iterable[str]] = None,
    limit: int = 1000,
    min_trust: float = 0.0,
    max_age_seconds: Optional[float] = None,
    now_iso: Optional[str] = None,
    tenant_id: Optional[str] = None,
    commit: bool = True,
) -> list[SourceBackfillReceipt]:
    """Auditable source-by-source ingestion without changing the legacy count API."""
    if db is None:
        return []
    if not tenant_id:
        from src.app.platform.tenant_context import current_tenant_id
        tenant_id = current_tenant_id()
    tenant_id = str(tenant_id or "default").strip() or "default"
    ensure_table(db)
    receipts: list[SourceBackfillReceipt] = []
    want = set(sources) if sources else None
    for name, (sql, row_map, sig_map) in _SOURCES.items():
        if want is not None and name not in want:
            continue
        receipts.append(_backfill_one(
            db, name, sql, row_map, sig_map, limit=limit, min_trust=min_trust,
            max_age_seconds=max_age_seconds, now_iso=now_iso, tenant_id=tenant_id,
        ))
    if commit:
        _safe_commit(db)
    return receipts
