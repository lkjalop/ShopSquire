"""Fulfilment case persistence (agnostic CORE) — the durable, BITEMPORAL source of procurement state.

Holds two tables:
  • fulfillment_case          — the case identity + its current status (a fast read).
  • fulfillment_case_version  — one immutable row PER transition, bitemporally versioned
       (valid_from/valid_to = business time; system_from/system_to = when we recorded it). The prior
       open version is CLOSED on each transition (SCD-2), so the full history is preserved and an
       as-of read reconstructs the state at any business time.

This module ONLY persists; the rules live in domain.py and the enforcement in workflow.py. The audit
narrative (who/why/evidence) lives in decision_trace_events — this is the domain state, not the log.
Vertical-blind: state/state_json/evidence are opaque. Best-effort reads; never raises into a caller.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

SCHEMA_VERSION = 1
DEFAULT_TENANT = "default"

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS fulfillment_case (
        id TEXT PRIMARY KEY,
        tenant_id TEXT DEFAULT 'default',
        buyer_uid_hash TEXT,
        source_trace_id TEXT,
        status TEXT,
        requested_by TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fulfillment_case_version (
        id TEXT PRIMARY KEY,
        case_id TEXT,
        tenant_id TEXT DEFAULT 'default',
        schema_version INTEGER DEFAULT 1,
        state TEXT,
        state_json TEXT,
        event TEXT,
        reason_code TEXT,
        actor_type TEXT,
        actor_id TEXT,
        idempotency_key TEXT,
        evidence_json TEXT,
        valid_from TEXT,
        valid_to TEXT,
        system_from TEXT,
        system_to TEXT,
        supersedes_version_id TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
)
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_fc_case_status ON fulfillment_case(tenant_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_fcv_open ON fulfillment_case_version(case_id, valid_to)",
    "CREATE INDEX IF NOT EXISTS ix_fcv_idem ON fulfillment_case_version(case_id, event, idempotency_key)",
)


def _now_iso(now_iso: Optional[str]) -> str:
    if now_iso:
        return str(now_iso)
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _tid(tenant_id: Any) -> str:
    return str(tenant_id).strip() or DEFAULT_TENANT


def ensure_tables(db) -> None:
    for ddl in _DDL:
        db.execute(text(ddl))
    for idx in _INDEXES:
        db.execute(text(idx))


@dataclass(frozen=True)
class CaseVersion:
    version_id: str
    case_id: str
    state: str
    state_json: Dict[str, Any] = field(default_factory=dict)
    event: str = ""
    actor_type: str = ""
    actor_id: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    valid_from: str = ""
    valid_to: Optional[str] = None
    source_trace_id: Optional[str] = None


def _loads(s: Any) -> Dict[str, Any]:
    try:
        v = json.loads(s) if s else {}
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def create_case(db, *, initial_state: str, buyer_uid_hash: Optional[str], source_trace_id: Optional[str],
                requested_by: str, tenant_id: str = DEFAULT_TENANT, now_iso: Optional[str] = None,
                state_json: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Open a case at ``initial_state`` and write its first version. Returns the case_id, or None."""
    if db is None:
        return None
    try:
        ensure_tables(db)
        tid = _tid(tenant_id)
        now = _now_iso(now_iso)
        cid = str(uuid.uuid4())
        db.execute(text("INSERT INTO fulfillment_case (id, tenant_id, buyer_uid_hash, source_trace_id, "
                        "status, requested_by, created_at, updated_at) VALUES (:i,:t,:b,:s,:st,:rb,:n,:n)"),
                   {"i": cid, "t": tid, "b": buyer_uid_hash, "s": source_trace_id, "st": initial_state,
                    "rb": requested_by, "n": now})
        _insert_version(db, case_id=cid, tenant_id=tid, state=initial_state, event="case_opened",
                        reason_code="", actor_type="system", actor_id=requested_by,
                        state_json=dict(state_json or {}), evidence={}, idempotency_key=None,
                        supersedes=None, now=now)
        return cid
    except Exception:
        return None


def _insert_version(db, *, case_id, tenant_id, state, event, reason_code, actor_type, actor_id,
                    state_json, evidence, idempotency_key, supersedes, now) -> str:
    vid = str(uuid.uuid4())
    db.execute(
        text("INSERT INTO fulfillment_case_version (id, case_id, tenant_id, schema_version, state, "
             "state_json, event, reason_code, actor_type, actor_id, idempotency_key, evidence_json, "
             "valid_from, valid_to, system_from, system_to, supersedes_version_id) "
             "VALUES (:i,:c,:t,:sv,:st,:sj,:ev,:rc,:at,:ai,:ik,:ej,:vf,NULL,:sf,NULL,:su)"),
        {"i": vid, "c": case_id, "t": tenant_id, "sv": int(SCHEMA_VERSION), "st": state,
         "sj": json.dumps(state_json, default=str), "ev": event, "rc": reason_code,
         "at": actor_type, "ai": actor_id, "ik": idempotency_key,
         "ej": json.dumps(evidence, default=str), "vf": now, "sf": now, "su": supersedes},
    )
    return vid


def current_version(db, case_id: str, tenant_id: str = DEFAULT_TENANT) -> Optional[CaseVersion]:
    """The OPEN version (valid_to IS NULL) — the live state. None if the case is unknown."""
    if db is None:
        return None
    try:
        ensure_tables(db)
        row = db.execute(
            text("SELECT v.id, v.case_id, v.state, v.state_json, v.event, v.actor_type, v.actor_id, "
                 "v.evidence_json, v.valid_from, v.valid_to, c.source_trace_id "
                 "FROM fulfillment_case_version v JOIN fulfillment_case c ON c.id = v.case_id "
                 "WHERE v.case_id=:c AND v.tenant_id=:t AND v.valid_to IS NULL "
                 "ORDER BY v.system_from DESC LIMIT 1"),
            {"c": case_id, "t": _tid(tenant_id)},
        ).fetchone()
    except Exception:
        return None
    return _row_to_version(row) if row else None


def version_asof(db, case_id: str, as_of: str, tenant_id: str = DEFAULT_TENANT) -> Optional[CaseVersion]:
    """The version that was valid in BUSINESS time at ``as_of`` — the bitemporal reconstruction."""
    if db is None:
        return None
    try:
        ensure_tables(db)
        row = db.execute(
            text("SELECT v.id, v.case_id, v.state, v.state_json, v.event, v.actor_type, v.actor_id, "
                 "v.evidence_json, v.valid_from, v.valid_to, c.source_trace_id "
                 "FROM fulfillment_case_version v JOIN fulfillment_case c ON c.id = v.case_id "
                 "WHERE v.case_id=:c AND v.tenant_id=:t AND v.valid_from <= :a "
                 "AND (v.valid_to IS NULL OR v.valid_to > :a) "
                 "ORDER BY v.valid_from DESC LIMIT 1"),
            {"c": case_id, "t": _tid(tenant_id), "a": str(as_of)},
        ).fetchone()
    except Exception:
        return None
    return _row_to_version(row) if row else None


def _row_to_version(row) -> CaseVersion:
    return CaseVersion(version_id=row[0], case_id=row[1], state=row[2], state_json=_loads(row[3]),
                       event=row[4] or "", actor_type=row[5] or "", actor_id=row[6] or "",
                       evidence=_loads(row[7]), valid_from=row[8] or "", valid_to=row[9],
                       source_trace_id=row[10])


def find_idempotent_version(db, case_id: str, event: str, key: str,
                            tenant_id: str = DEFAULT_TENANT) -> Optional[str]:
    """The version id already written for this (case, event, idempotency_key), if any — so a retried
    command (a double-clicked send) does not apply twice."""
    if db is None or not key:
        return None
    try:
        ensure_tables(db)
        row = db.execute(
            text("SELECT id FROM fulfillment_case_version WHERE case_id=:c AND tenant_id=:t "
                 "AND event=:e AND idempotency_key=:k LIMIT 1"),
            {"c": case_id, "t": _tid(tenant_id), "e": event, "k": key},
        ).fetchone()
    except Exception:
        return None
    return row[0] if row else None


def append_version(db, *, case_id: str, new_state: str, event: str, reason_code: str, actor_type: str,
                   actor_id: str, evidence: Optional[Dict[str, Any]], state_patch: Optional[Dict[str, Any]],
                   idempotency_key: Optional[str] = None, tenant_id: str = DEFAULT_TENANT,
                   now_iso: Optional[str] = None) -> Optional[str]:
    """Close the current open version (SCD-2: valid_to=system_to=now) and insert the new one, merging
    ``state_patch`` into the prior state_json so the case accumulates domain data. Updates the case
    status. Returns the new version id, or None. Does NOT commit (the workflow owns the transaction)."""
    if db is None:
        return None
    try:
        ensure_tables(db)
        tid = _tid(tenant_id)
        now = _now_iso(now_iso)
        cur = current_version(db, case_id, tid)
        merged = dict(cur.state_json) if cur else {}
        merged.update(dict(state_patch or {}))
        if cur is not None:
            db.execute(text("UPDATE fulfillment_case_version SET valid_to=:n, system_to=:n "
                            "WHERE id=:v AND valid_to IS NULL"), {"n": now, "v": cur.version_id})
        vid = _insert_version(db, case_id=case_id, tenant_id=tid, state=new_state, event=event,
                              reason_code=reason_code, actor_type=actor_type, actor_id=actor_id,
                              state_json=merged, evidence=dict(evidence or {}),
                              idempotency_key=idempotency_key,
                              supersedes=(cur.version_id if cur else None), now=now)
        db.execute(text("UPDATE fulfillment_case SET status=:s, updated_at=:n WHERE id=:c"),
                   {"s": new_state, "n": now, "c": case_id})
        return vid
    except Exception:
        return None


def journey(db, case_id: str, tenant_id: str = DEFAULT_TENANT, limit: int = 200) -> List[Dict[str, Any]]:
    """The full ordered version history (the Fulfilment Journey). Best-effort."""
    if db is None:
        return []
    try:
        ensure_tables(db)
        rows = db.execute(
            text("SELECT id, supersedes_version_id, state, event, actor_type, actor_id, reason_code, "
                 "evidence_json, valid_from, valid_to, system_from FROM fulfillment_case_version "
                 "WHERE case_id=:c AND tenant_id=:t ORDER BY system_from ASC, id ASC LIMIT :lim"),
            {"c": case_id, "t": _tid(tenant_id), "lim": int(limit)},
        ).fetchall()
    except Exception:
        return []
    raw = [{
        "id": r[0], "supersedes_version_id": r[1], "state": r[2], "event": r[3], "actor_type": r[4],
        "actor_id": r[5], "reason_code": r[6], "evidence": _loads(r[7]), "valid_from": r[8],
        "valid_to": r[9], "system_from": r[10],
    } for r in rows]
    by_prev: Dict[str, List[Dict[str, Any]]] = {}
    roots: List[Dict[str, Any]] = []
    for row in raw:
        prev = row.get("supersedes_version_id")
        if prev:
            by_prev.setdefault(str(prev), []).append(row)
        else:
            roots.append(row)
    for vals in by_prev.values():
        vals.sort(key=lambda x: (str(x.get("system_from") or ""), str(x.get("id") or "")))
    roots.sort(key=lambda x: (0 if x.get("event") == "case_opened" else 1,
                              str(x.get("system_from") or ""), str(x.get("id") or "")))
    ordered: List[Dict[str, Any]] = []
    seen = set()
    cur = roots[0] if roots else (raw[0] if raw else None)
    while cur and cur.get("id") not in seen:
        ordered.append(cur)
        seen.add(cur.get("id"))
        nxt = by_prev.get(str(cur.get("id")), [])
        cur = nxt[0] if nxt else None
    for row in raw:
        if row.get("id") not in seen:
            ordered.append(row)
    return [{"state": r["state"], "event": r["event"], "actor_type": r["actor_type"],
             "actor_id": r["actor_id"], "reason_code": r["reason_code"], "evidence": r["evidence"],
             "valid_from": r["valid_from"], "valid_to": r["valid_to"]} for r in ordered]


def list_cases(db, *, tenant_id: str = DEFAULT_TENANT, limit: int = 100) -> List[Dict[str, Any]]:
    if db is None:
        return []
    try:
        ensure_tables(db)
        rows = db.execute(
            text("SELECT id, buyer_uid_hash, status, requested_by, source_trace_id, updated_at "
                 "FROM fulfillment_case WHERE tenant_id=:t ORDER BY updated_at DESC LIMIT :lim"),
            {"t": _tid(tenant_id), "lim": int(limit)},
        ).fetchall()
    except Exception:
        return []
    return [{"case_id": r[0], "buyer_uid_hash": r[1], "status": r[2], "requested_by": r[3],
             "source_trace_id": r[4], "updated_at": r[5]} for r in rows]


def case_id_by_trace(db, trace_id: str, tenant_id: str = DEFAULT_TENANT) -> Optional[str]:
    """The most recent case opened from a given decision trace_id (the link between the agent trace and
    the procurement journey). None if none. Best-effort."""
    if db is None or not trace_id:
        return None
    try:
        ensure_tables(db)
        row = db.execute(
            text("SELECT id FROM fulfillment_case WHERE tenant_id=:t AND source_trace_id=:s "
                 "ORDER BY updated_at DESC LIMIT 1"),
            {"t": _tid(tenant_id), "s": str(trace_id)},
        ).fetchone()
        return row[0] if row else None
    except Exception:
        return None
