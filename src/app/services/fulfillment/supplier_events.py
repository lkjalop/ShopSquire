"""Supplier out-of-band event write-bus (agnostic CORE) — the WRITE twin of supplier_inbox_reader.

A supplier often contacts the merchant OUTSIDE the system (phone, in person): "lead time slipped to 3
weeks", "price changed", "out of stock". That fact must re-enter the bitemporal record and propagate to
every open procurement case that references the supplier — so an operator working a case sees it, and the
buyer-facing journey reflects reality.

This module:
  • records the event durably in ``supplier_oob_events`` (queryable per supplier domain), and
  • FANS OUT a durable trace event onto every OPEN, non-terminal case whose recipient_domain matches, so it
    appears in each case's journey/decision trace (the case carries its PO/receipt, so a case-level note
    covers those too).

It NEVER mutates an issued PO/receipt (bitemporal: the past is preserved; a new fact is appended) and never
contacts anyone. Vertical-blind: domain · kind · note are opaque strings — no product vocabulary.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger("shopsquire.supplier_events")

# the recognised out-of-band event kinds (governance vocabulary, not product flavour). "general" is the
# catch-all; the set is a guard so a typo doesn't silently create a new kind.
KINDS = frozenset({"lead_time_change", "price_change", "out_of_stock", "back_in_stock",
                   "contact_change", "general"})

_DDL = """
CREATE TABLE IF NOT EXISTS supplier_oob_events (
    id                  TEXT PRIMARY KEY,
    tenant_id           TEXT,
    sender_domain_hash  TEXT,
    domain              TEXT,
    kind                TEXT,
    note                TEXT,
    actor_id            TEXT,
    event_ts            TEXT
)
"""


def _hash16(domain: str) -> str:
    return hashlib.sha256(domain.encode("utf-8")).hexdigest()[:16]


def _now_iso(now_iso: Optional[str]) -> str:
    if now_iso:
        return str(now_iso)
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _open_cases_for_domain(db, domain: str, tenant_id: str) -> List[Dict[str, Any]]:
    """OPEN, non-terminal cases whose resolved recipient_domain matches — the fan-out targets. Returns
    [{case_id, source_trace_id, state}]. Best-effort; [] on error."""
    try:
        from src.app.services.fulfillment.domain import TERMINAL_STATES
        from src.app.services.fulfillment.repository import ensure_tables
        ensure_tables(db)
        terminal = [s.value for s in TERMINAL_STATES]
        placeholders = ", ".join(f":st{i}" for i in range(len(terminal)))
        params: Dict[str, Any] = {"t": str(tenant_id or "default"), "p": f'%"recipient_domain"%{domain}%'}
        params.update({f"st{i}": v for i, v in enumerate(terminal)})
        rows = db.execute(text(
            "SELECT DISTINCT v.case_id, c.source_trace_id, v.state "
            "FROM fulfillment_case_version v JOIN fulfillment_case c ON c.id = v.case_id "
            f"WHERE v.tenant_id=:t AND v.valid_to IS NULL AND v.state_json LIKE :p "
            f"AND v.state NOT IN ({placeholders})"),
            params).fetchall()
        return [{"case_id": str(r[0]), "source_trace_id": r[1], "state": r[2]} for r in (rows or []) if r and r[0]]
    except Exception as exc:
        logger.debug("_open_cases_for_domain failed for %s: %s", domain, exc)
        return []


def record_supplier_event(db, *, supplier_domain: str, kind: str = "general", note: str,
                          actor_id: str = "operator", tenant_id: str = "default",
                          now_iso: Optional[str] = None) -> Dict[str, Any]:
    """Record an out-of-band supplier contact and fan it out to every open case for that supplier domain.
    Returns {event_id, domain, kind, affected_cases:[case_id], note}. Best-effort fan-out — a per-case
    trace failure never loses the recorded event."""
    domain = str(supplier_domain or "").strip().lower()
    note = str(note or "").strip()
    k = kind if kind in KINDS else "general"
    if not domain or not note or db is None:
        return {"event_id": None, "domain": domain, "kind": k, "affected_cases": [], "note": note}

    ts = _now_iso(now_iso)
    event_id = f"soob-{uuid.uuid4().hex[:12]}"
    try:
        db.execute(text(_DDL))
        db.execute(text(
            "INSERT INTO supplier_oob_events (id, tenant_id, sender_domain_hash, domain, kind, note, actor_id, event_ts) "
            "VALUES (:i, :t, :sdh, :d, :k, :n, :a, :ts)"),
            {"i": event_id, "t": tenant_id, "sdh": _hash16(domain), "d": domain, "k": k,
             "n": note, "a": str(actor_id or "operator"), "ts": ts})
        db.commit()
    except Exception as exc:
        logger.debug("record_supplier_event insert failed for %s: %s", domain, exc)
        try:
            db.rollback()
        except Exception:
            pass

    affected: List[str] = []
    for case in _open_cases_for_domain(db, domain, tenant_id):
        affected.append(case["case_id"])
        trace_id = case.get("source_trace_id")
        if not trace_id:
            continue
        try:
            from src.app.services.decision_log import log_trace_event
            log_trace_event(trace_id=trace_id, event_type="supplier_oob_event", source_type="agent",
                            source_id="Supplier_OOB_Agent", target_type="fulfillment_case",
                            target_id=case["case_id"],
                            payload={"domain": domain, "kind": k, "note": note, "event_id": event_id},
                            durable=True)
        except Exception as exc:
            logger.debug("supplier_oob fan-out trace failed for case %s: %s", case["case_id"], exc)
    return {"event_id": event_id, "domain": domain, "kind": k, "affected_cases": affected, "note": note}


def recent_supplier_oob_events(db, *, supplier_domain: str, tenant_id: str = "default",
                               limit: int = 20) -> List[Dict[str, Any]]:
    """The recent out-of-band events recorded for a supplier domain (newest first). Best-effort; []."""
    domain = str(supplier_domain or "").strip().lower()
    if not domain or db is None:
        return []
    try:
        db.execute(text(_DDL))
        rows = db.execute(text(
            "SELECT id, kind, note, actor_id, event_ts FROM supplier_oob_events "
            "WHERE tenant_id=:t AND sender_domain_hash=:sdh ORDER BY event_ts DESC LIMIT :lim"),
            {"t": tenant_id, "sdh": _hash16(domain), "lim": int(limit)}).fetchall()
        return [{"event_id": r[0], "kind": r[1], "note": r[2], "actor_id": r[3], "event_ts": r[4]}
                for r in (rows or [])]
    except Exception as exc:
        logger.debug("recent_supplier_oob_events failed for %s: %s", domain, exc)
        return []
