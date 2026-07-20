"""Market Intelligence Store (agnostic CORE) — deck Module 2 historical entities.

The persistent MEMORY of the market-intel subsystem: it turns the M3 Analysis Engine's transient findings
into durable, queryable history so the system can reconstruct trends, validate past decisions, and replay.
Three entities from the deck (slide 6 / slide 12):

  • trend_indicator      — a persisted demand/interest trend (direction + value vs baseline over time).
  • competitor_snapshot  — a point-in-time competitor price observation (ours vs theirs).
  • offer_policy         — a recorded offer/discount DECISION (what we chose + the margin floor + why).

Dual-mode by construction: low-latency point reads for real-time decisioning, ordered history reads for
analysis. Vertical-blind: entity_ref is an OPAQUE ref (sku / category / channel token); everything else is a
number, an enum, or a timestamp — NO product vocabulary. Best-effort writers never raise into ingest.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger("shopsquire.market_store")

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS trend_indicator (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT DEFAULT 'default',
        entity_ref TEXT,
        indicator_type TEXT,
        direction TEXT,
        value REAL,
        baseline REAL,
        confidence REAL,
        observed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS competitor_snapshot (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT DEFAULT 'default',
        entity_ref TEXT,
        our_price_cents INTEGER,
        competitor_price_cents INTEGER,
        competitor TEXT,
        observed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS offer_policy (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT DEFAULT 'default',
        entity_ref TEXT,
        action TEXT,
        discount_pct REAL,
        floor_margin_pct REAL,
        rationale TEXT,
        decided_at TEXT
    )
    """,
)
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_ti_entity ON trend_indicator(tenant_id, entity_ref, observed_at)",
    "CREATE INDEX IF NOT EXISTS ix_cs_entity ON competitor_snapshot(tenant_id, entity_ref, observed_at)",
    "CREATE INDEX IF NOT EXISTS ix_op_entity ON offer_policy(tenant_id, entity_ref, decided_at)",
)


def ensure_tables(db) -> None:
    from src.app.services.schema_policy import runtime_ddl_allowed
    if not runtime_ddl_allowed():
        return
    for ddl in _DDL:
        db.execute(text(ddl))
    for idx in _INDEXES:
        db.execute(text(idx))


def _tid(tenant_id: Any) -> str:
    return str(tenant_id or "default").strip() or "default"


def record_trend_indicator(db, *, entity_ref: str, indicator_type: str, direction: str,
                           value: Optional[float] = None, baseline: Optional[float] = None,
                           confidence: Optional[float] = None, observed_at: Optional[str] = None,
                           tenant_id: str = "default") -> bool:
    """Persist one trend point (e.g. demand rising for a category). Best-effort → False on any failure."""
    try:
        ensure_tables(db)
        db.execute(text(
            "INSERT INTO trend_indicator (tenant_id, entity_ref, indicator_type, direction, value, baseline, "
            "confidence, observed_at) VALUES (:t,:e,:it,:d,:v,:b,:c,:o)"),
            {"t": _tid(tenant_id), "e": str(entity_ref or ""), "it": str(indicator_type or ""),
             "d": str(direction or ""), "v": _num(value), "b": _num(baseline), "c": _num(confidence),
             "o": str(observed_at or "")})
        db.commit()
        return True
    except Exception as exc:
        logger.debug("record_trend_indicator skipped: %s", exc)
        _rollback(db)
        return False


def record_competitor_snapshot(db, *, entity_ref: str, our_price_cents: Optional[int] = None,
                               competitor_price_cents: Optional[int] = None, competitor: Optional[str] = None,
                               observed_at: Optional[str] = None, tenant_id: str = "default") -> bool:
    try:
        ensure_tables(db)
        db.execute(text(
            "INSERT INTO competitor_snapshot (tenant_id, entity_ref, our_price_cents, competitor_price_cents, "
            "competitor, observed_at) VALUES (:t,:e,:op,:cp,:c,:o)"),
            {"t": _tid(tenant_id), "e": str(entity_ref or ""), "op": _int(our_price_cents),
             "cp": _int(competitor_price_cents), "c": str(competitor or ""), "o": str(observed_at or "")})
        db.commit()
        return True
    except Exception as exc:
        logger.debug("record_competitor_snapshot skipped: %s", exc)
        _rollback(db)
        return False


def record_offer_policy(db, *, entity_ref: str, action: str, discount_pct: Optional[float] = None,
                        floor_margin_pct: Optional[float] = None, rationale: Optional[str] = None,
                        decided_at: Optional[str] = None, tenant_id: str = "default") -> bool:
    """Persist an offer/discount DECISION (the audit history of what we chose + why)."""
    try:
        ensure_tables(db)
        db.execute(text(
            "INSERT INTO offer_policy (tenant_id, entity_ref, action, discount_pct, floor_margin_pct, "
            "rationale, decided_at) VALUES (:t,:e,:a,:d,:f,:r,:o)"),
            {"t": _tid(tenant_id), "e": str(entity_ref or ""), "a": str(action or ""), "d": _num(discount_pct),
             "f": _num(floor_margin_pct), "r": str(rationale or "")[:500], "o": str(decided_at or "")})
        db.commit()
        return True
    except Exception as exc:
        logger.debug("record_offer_policy skipped: %s", exc)
        _rollback(db)
        return False


def list_trend_indicators(db, *, entity_ref: Optional[str] = None, limit: int = 200,
                          tenant_id: str = "default") -> List[Dict[str, Any]]:
    return _list(db, "trend_indicator", "observed_at",
                 ("entity_ref", "indicator_type", "direction", "value", "baseline", "confidence", "observed_at"),
                 entity_ref=entity_ref, limit=limit, tenant_id=tenant_id)


def list_competitor_snapshots(db, *, entity_ref: Optional[str] = None, limit: int = 200,
                              tenant_id: str = "default") -> List[Dict[str, Any]]:
    return _list(db, "competitor_snapshot", "observed_at",
                 ("entity_ref", "our_price_cents", "competitor_price_cents", "competitor", "observed_at"),
                 entity_ref=entity_ref, limit=limit, tenant_id=tenant_id)


def list_offer_policies(db, *, entity_ref: Optional[str] = None, limit: int = 200,
                        tenant_id: str = "default") -> List[Dict[str, Any]]:
    return _list(db, "offer_policy", "decided_at",
                 ("entity_ref", "action", "discount_pct", "floor_margin_pct", "rationale", "decided_at"),
                 entity_ref=entity_ref, limit=limit, tenant_id=tenant_id)


def persist_history(db, findings: Optional[List[Any]], *, observed_at: Optional[str] = None,
                    tenant_id: str = "default") -> Dict[str, int]:
    """The M3→M2 write path: turn the analysis engine's findings into durable HISTORY — demand findings
    become trend_indicators, competitor findings become competitor_snapshots. Named distinctly from
    market_analysis.persist_findings (which writes the findings table) to avoid confusion. Idempotent enough
    for replay (append-only history). Returns {trends, competitors} counts. Best-effort; never raises."""
    trends = competitors = 0
    for f in (findings or []):
        try:
            ftype = str(_attr(f, "finding_type") or "")
            ev = _attr(f, "evidence") or {}
            ev = ev if isinstance(ev, dict) else {}
            ent = str(_attr(f, "entity_ref") or ev.get("query") or ev.get("sku") or ev.get("entity_ref") or "market")
            if ftype in ("demand_shift", "demand_forecast", "seasonal_demand"):
                if record_trend_indicator(db, entity_ref=ent, indicator_type="demand",
                                          direction=str(ev.get("direction") or ""),
                                          value=_num(ev.get("latest") if ev.get("latest") is not None else ev.get("projected")),
                                          baseline=_num(ev.get("baseline")),
                                          confidence=_num(_attr(f, "confidence")),
                                          observed_at=observed_at, tenant_id=tenant_id):
                    trends += 1
            elif ftype == "competitor_undercut":
                if record_competitor_snapshot(db, entity_ref=ent,
                                              our_price_cents=_int(ev.get("our_price_cents")),
                                              competitor_price_cents=_int(ev.get("competitor_price_cents")),
                                              competitor=str(ev.get("competitor") or ""),
                                              observed_at=observed_at, tenant_id=tenant_id):
                    competitors += 1
        except Exception as exc:
            logger.debug("persist_findings row skipped: %s", exc)
    return {"trends": trends, "competitors": competitors}


# ── helpers ───────────────────────────────────────────────────────────────────
def _list(db, table: str, order_col: str, cols, *, entity_ref, limit, tenant_id) -> List[Dict[str, Any]]:
    try:
        ensure_tables(db)
        sql = f"SELECT {', '.join(cols)} FROM {table} WHERE tenant_id=:t"
        params: Dict[str, Any] = {"t": _tid(tenant_id), "lim": int(limit)}
        if entity_ref:
            sql += " AND entity_ref=:e"
            params["e"] = str(entity_ref)
        sql += f" ORDER BY {order_col} DESC LIMIT :lim"
        rows = db.execute(text(sql), params).fetchall()
        return [dict(zip(cols, r)) for r in (rows or [])]
    except Exception as exc:
        logger.debug("_list(%s) skipped: %s", table, exc)
        return []


def _attr(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _num(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _rollback(db) -> None:
    try:
        db.rollback()
    except Exception:
        pass
